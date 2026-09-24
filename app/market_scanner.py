"""Autonome marktscan: HesPulse ontdekt zelf een day-trading-kans, zonder
dat een gebruiker eerst een Discord-bericht doorstuurt. Draait elke 20
minuten via een systemd-timer (zie deploy/crypto-market-scan.service en
.timer), niet elke 4 uur zoals de underlying candle-timeframe: de laatste
4u-candle is bij Binance nog "in wording" totdat hij sluit, dus
tussentijds checken vangt een beweging eerder op. Zelfde soort
redenering als level_check.py, die ook vaker draait dan de candle zelf.

Voor elke coin in de bestaande dynamische lijst (repo.list_coins()) wordt
zelf een richting bepaald via de trend (EMA9 t.o.v. EMA21) en hergebruikt
process_day_trading_signal() de bestaande toetsings- en fan-out-logica —
geen tweede implementatie ernaast. Zie
docs/superpowers/specs/2026-09-14-autonome-marktscan-design.md.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app import exchange, indicators, patterns, push_notify, repo, risk
from app.anthropic_interpret import Interpretation
from app.signal_processor import (
    MIN_RISK_REWARD_RATIO,
    compute_full_confirmation,
    fanout_confirmed_signal,
    process_day_trading_signal,
)

logger = logging.getLogger("market_scanner")

# Twaalf uur overslaan na een verlies op dezelfde coin+richting is een
# reële afkoelperiode zonder een kans dagenlang te blokkeren. In uren, niet
# in cycli: blijft ongewijzigd correct ongeacht het scan-interval. Zie de
# spec, sectie 4.
AUTO_SCAN_LOSS_COOLDOWN_HOURS = 12

# Whiplash-rem: een NIEUWE richting moet dit aantal scan-cycli achter
# elkaar aanhouden voor er gemeld wordt. Voorkomt dat een EMA9/EMA21-
# kruising die binnen enkele tientallen minuten alweer terugklapt eerst
# een long en dan een short melding oplevert voor dezelfde coin. Bij het
# huidige 20-minuten-interval (deploy/crypto-market-scan.timer) is dat tot
# ~40 minuten vertraging voor een vers signaal — bewust ongewijzigd
# gelaten toen het interval van elk uur naar elke 20 minuten ging, dat is
# de betrouwbaarheidswaarborg, niet de knop om sneller te melden.
WHIPLASH_MIN_CONSECUTIVE_CYCLES = 2

# Maximum aantal structurele meldingen (uitbraak/trendlijn/patroon) dat één
# scan-cyclus daadwerkelijk pusht, over alle coins samen. Een cyclus die op
# meerdere coins tegelijk iets vindt (bv. een markbrede beweging die op tien
# coins een patroon triggert) meldde voorheen alles meteen — tot 17 losse
# pushes in 2,5 minuut, onduidelijk en overweldigend. De sterkste kandidaten
# (_candidate_score, risk:reward) winnen een plek; de rest wordt niet
# aangemaakt (geen signals-rij, geen dedup-key gezet) en dingt gewoon opnieuw
# mee in een volgende cyclus als de kans dan nog steeds geldig is — niets
# gaat blijvend verloren, het wordt alleen niet allemaal tegelijk gemeld.
MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE = 3


# Hoe dicht het middelpunt van een nieuw gevonden zone bij het middelpunt
# van de vorig gemelde zone moet liggen (in ATR) om als "dezelfde zone" te
# tellen. detect_sr_zones herberekent elke cyclus opnieuw over een
# schuivend venster van 100 candles, dus de exacte grenzen schuiven een
# fractie mee zonder dat het om een echt andere zone gaat — zonder deze
# marge stuurde een exacte-string-vergelijking dezelfde zone soms binnen
# een paar cycli opnieuw (AAVE en BTC allebei twee keer in één nacht).
BREAKOUT_RETEST_DEDUP_ATR_MULTIPLE = 1.0


def _same_breakout_retest_zone(existing_key: Optional[str], direction: str, zone, atr: float) -> bool:
    if not existing_key:
        return False
    try:
        prev_direction, prev_low_s, prev_high_s = existing_key.split(":")
        prev_low, prev_high = float(prev_low_s), float(prev_high_s)
    except (ValueError, AttributeError):
        return False
    if prev_direction != direction or not atr:
        return False
    prev_mid = (prev_low + prev_high) / 2
    new_mid = (zone.price_low + zone.price_high) / 2
    return abs(prev_mid - new_mid) <= BREAKOUT_RETEST_DEDUP_ATR_MULTIPLE * atr


def _candidate_score(entry_price: float, stop_loss: float, take_profit: float) -> float:
    """Risk:reward als vergelijkingsmaat tussen kandidaten van verschillende
    soorten (zone/lijn/patroon) die deze cyclus voor dezelfde coin en
    richting zouden melden: hoe verder de take t.o.v. de stop, hoe steviger
    de kans. Dit is de enige maat die voor alle drie soorten op dezelfde
    manier berekenbaar is — een patroonmatch heeft geen touches-telling
    zoals een zone of trendlijn dat wel heeft."""
    risk_amount = abs(entry_price - stop_loss)
    if risk_amount <= 0:
        return 0.0
    return abs(take_profit - entry_price) / risk_amount


async def _find_breakout_retest_candidate(coin: str, direction: str, df, ind) -> Optional[dict]:
    """Los van de trend-confirmatie verderop: een uitbraak-dan-terugtest is
    een eigen, sterk entry-patroon (een zone die eerder steun/weerstand
    was, doorbroken is, en nu opnieuw getest wordt) en verdient een eigen
    melding, ongeacht of confirms_direction deze cyclus ja of nee zegt.
    Dedupliceert op coin+richting+zone via coins.last_breakout_retest_key,
    met een ATR-marge (_same_breakout_retest_zone): een zone die dicht
    genoeg bij de vorig gemelde zone ligt telt als dezelfde, een echt
    nieuwe uitbraak (andere zone, of de andere richting) stuurt opnieuw.

    Meldt niet meteen: geeft een kandidaat terug (of None) zodat
    scan_market() eerst kan vergelijken met wat de andere structurele
    checks deze cyclus voor dezelfde coin en richting vinden, en alleen de
    sterkste daadwerkelijk meldt (zie _candidate_score)."""
    zones = indicators.detect_sr_zones(df)
    hits = indicators.find_breakout_retest(df, zones, ind.atr, direction)
    if not hits:
        return None
    zone, candles_since = max(hits, key=lambda h: h[0].touches)
    key = f"{direction}:{zone.price_low:.8f}:{zone.price_high:.8f}"
    if _same_breakout_retest_zone(repo.get_breakout_retest_key(coin), direction, zone, ind.atr):
        return None  # binnen de dedup-marge van de vorige melding, geen herhaling

    stop_take = risk.compute_stop_take(
        direction, ind.price, ind.atr,
        swing_low=zone.price_low if direction == "long" else None,
        swing_high=zone.price_high if direction == "short" else None,
    )
    pattern_label = "uitbraak + terugtest"

    async def notify() -> None:
        # Zelfde opzet als _find_chart_pattern_candidate's notify(): een
        # echte signals-rij + journaal-fanout in plaats van alleen een
        # kale pushmelding. Voorheen bleef uitbraak+terugtest volledig
        # onzichtbaar zodra de melding voorbij was — geen kaart op
        # /signalen of de coinpagina, geen trackrecord, geen winrate,
        # niets om op te wegen. compute_full_confirmation hier binnen
        # notify() (niet in de outer functie): draait toch al alleen voor
        # de winnende kandidaat van deze cyclus.
        _, factor_breakdown, factor_pass_pct, factor_hard_gates_ok = await compute_full_confirmation(
            coin, direction, df, ind, zones,
        )
        pattern_stats = repo.pattern_winrate_stats().get(pattern_label)
        kansberekening = repo.pattern_kansberekening(factor_pass_pct, pattern_stats)

        ignored = repo.auto_ignore_opposite_pending(coin, direction)
        if ignored:
            logger.info("%s nog niet genomen tegenovergestelde melding(en) voor %s automatisch genegeerd (uitbraak+terugtest)",
                         len(ignored), coin)
            for user in ignored:
                try:
                    repo.create_notification(
                        user["id"], "expired_signal",
                        f"Kans op {coin} vervallen",
                        f"Een nieuwe {direction}-melding op {coin} maakte de vorige kans achterhaald.",
                        f"/coins/{coin}",
                    )
                except Exception:
                    logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

        sniper = indicators.find_sniper_entry_price(direction, df)
        sniper_entry_price, sniper_reason = sniper if sniper else (None, None)

        signal_data = {
            "message_id": None, "coin": coin, "direction": direction,
            "category": "day_trading", "trade_type": "patroon", "pattern_name": pattern_label,
            "price": ind.price, "rsi": ind.rsi, "macd": ind.macd, "macd_signal": ind.macd_signal,
            "volume_ratio": ind.volume_ratio, "ema9": ind.ema9, "ema21": ind.ema21,
            "atr": ind.atr, "atr_avg20": ind.atr_avg20, "adx": ind.adx,
            "technical_confirmed": 1, "pass_pct": factor_pass_pct, "hard_gates_ok": factor_hard_gates_ok,
            "confidence": "patroon bevestigd",
            "reason": factor_breakdown,
            "stop_loss": stop_take.stop_loss, "take_profit": stop_take.take_profit,
            "context_note": None, "is_practice": 0, "plain_explanation": None,
            "suggested_entry_low": None, "suggested_entry_high": None,
            "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
        }
        signal_id = repo.insert_signal(signal_data)

        stale = repo.auto_ignore_stale_pending_for_coin(coin, exclude_signal_id=signal_id)
        if stale:
            logger.info("%s oude nog niet genomen melding(en) voor %s automatisch genegeerd (nieuw uitbraak+terugtest-signaal)",
                         len(stale), coin)
            for user in stale:
                try:
                    repo.create_notification(
                        user["id"], "expired_signal",
                        f"Kans op {coin} vervallen",
                        f"Een oude melding op {coin} is vervangen door een nieuw signaal.",
                        f"/coins/{coin}",
                    )
                except Exception:
                    logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

        def _breakout_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            base = f"Entry {ind.price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            if sniper_entry_price is not None:
                base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
            return base

        # premise_level = de zone-rand die doorbroken is (weerstand-tot-
        # steun bij long, steun-tot-weerstand bij short) — de trigger-prijs
        # van deze trade, niet ind.price die intussen verder kan zijn
        # doorgelopen. Zelfde rol als match.neckline bij een chart-patroon.
        premise_level = zone.price_high if direction == "long" else zone.price_low
        await fanout_confirmed_signal(
            signal_id, coin, direction, ind.price, stop_take.stop_loss, stop_take.take_profit, premise_level,
            title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, {pattern_label}",
            make_body=_breakout_body,
            kansberekening=kansberekening,
            hard_gates_ok=bool(factor_hard_gates_ok),
            reason=factor_breakdown,
        )
        repo.set_breakout_retest_key(coin, key)

    return {
        "kind": "uitbraak+terugtest", "direction": direction,
        "score": _candidate_score(ind.price, stop_take.stop_loss, stop_take.take_profit),
        "notify": notify,
    }


TRENDLINE_DEDUP_ATR_MULTIPLE = 1.0


def _same_trendline(existing_key: Optional[str], direction: str, line, atr: float) -> bool:
    if not existing_key:
        return False
    try:
        prev_direction, prev_kind, prev_value_s = existing_key.split(":")
        prev_value = float(prev_value_s)
    except (ValueError, AttributeError):
        return False
    if prev_direction != direction or prev_kind != line.kind or not atr:
        return False
    # Altijd line.value_at(line.last_index) — de lijn's eigen laatste
    # bevestigende pivot, een vast historisch punt — nooit "nu" (zie de
    # why-comment in _check_trendline_retest hieronder voor de reden).
    identity_value = line.value_at(line.last_index)
    return abs(prev_value - identity_value) <= TRENDLINE_DEDUP_ATR_MULTIPLE * atr


async def _find_trendline_retest_candidate(coin: str, direction: str, df, ind) -> Optional[dict]:
    """Los van _find_breakout_retest_candidate: een diagonale trendlijn
    (steun of weerstand) is een ander patroon dan een horizontale zone, met
    een eigen melding. Zelfde striktheid (crossing op closing-prijs, moet
    standhouden) en zelfde ATR-dedup-marge als de optie-C-fix van
    vandaag, zie docs/superpowers/specs/2026-09-15-trendlijn-uitbraak-design.md.

    Zelfde uitgestelde-melding-opzet als _find_breakout_retest_candidate:
    geeft een kandidaat terug (of None) in plaats van meteen te melden."""
    trendlines = indicators.detect_trendlines(df, ind.atr)
    hits = indicators.find_trendline_breakout_retest(df, trendlines, ind.atr, direction)
    if not hits:
        return None
    line, candles_since = max(hits, key=lambda h: h[0].touches)

    # last_index is HIER de laatste candle van het venster (de huidige
    # lijnwaarde), niet line.last_index (dat is de laatste PIVOT op de
    # lijn) — zelfde venster als find_trendline_breakout_retest intern
    # gebruikt, anders wijst value_at(last_index) een andere candle aan
    # dan waar de terugtest zojuist tegen getoetst is.
    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    last_index = len(window) - 1
    current_value = line.value_at(last_index)  # voor de melding/stop-take: "nu", blijft zo

    # why: dedup mag NIET op current_value vergelijken — line.value_at(last_index)
    # verschuift vanzelf elke cyclus, puur omdat er tijd verstrijkt (een
    # schuine lijn heeft per definitie een andere waarde op "nu" dan een
    # cyclus geleden). Vergeleken op "nu" zou dezelfde, ongewijzigde lijn
    # binnen ongeveer een dag opnieuw melden. identity_value gebruikt in
    # plaats daarvan de lijn's eigen laatste bevestigende pivot
    # (line.last_index): een vast historisch punt dat niet verschuift
    # zolang de lijn zelf dezelfde blijft. De melding zelf (current_value
    # hierboven, en de stop/take eronder) moet wél de live "nu"-waarde
    # gebruiken, dat blijft ongewijzigd correct.
    identity_value = line.value_at(line.last_index)
    key = f"{direction}:{line.kind}:{identity_value:.8f}"
    if _same_trendline(repo.get_trendline_retest_key(coin), direction, line, ind.atr):
        return None

    stop_take = risk.compute_stop_take(
        direction, ind.price, ind.atr,
        swing_low=current_value if direction == "long" else None,
        swing_high=current_value if direction == "short" else None,
    )
    pattern_label = "trendlijn + terugtest"

    async def notify() -> None:
        # Zelfde opzet als _find_breakout_retest_candidate hierboven: een
        # echte signals-rij + journaal-fanout in plaats van alleen een
        # kale pushmelding, zodat dit type ook op /signalen, de coinpagina
        # en het trackrecord verschijnt.
        zones = indicators.detect_sr_zones(df)
        _, factor_breakdown, factor_pass_pct, factor_hard_gates_ok = await compute_full_confirmation(
            coin, direction, df, ind, zones,
        )
        pattern_stats = repo.pattern_winrate_stats().get(pattern_label)
        kansberekening = repo.pattern_kansberekening(factor_pass_pct, pattern_stats)

        ignored = repo.auto_ignore_opposite_pending(coin, direction)
        if ignored:
            logger.info("%s nog niet genomen tegenovergestelde melding(en) voor %s automatisch genegeerd (trendlijn+terugtest)",
                         len(ignored), coin)
            for user in ignored:
                try:
                    repo.create_notification(
                        user["id"], "expired_signal",
                        f"Kans op {coin} vervallen",
                        f"Een nieuwe {direction}-melding op {coin} maakte de vorige kans achterhaald.",
                        f"/coins/{coin}",
                    )
                except Exception:
                    logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

        sniper = indicators.find_sniper_entry_price(direction, df)
        sniper_entry_price, sniper_reason = sniper if sniper else (None, None)

        signal_data = {
            "message_id": None, "coin": coin, "direction": direction,
            "category": "day_trading", "trade_type": "patroon", "pattern_name": pattern_label,
            "price": ind.price, "rsi": ind.rsi, "macd": ind.macd, "macd_signal": ind.macd_signal,
            "volume_ratio": ind.volume_ratio, "ema9": ind.ema9, "ema21": ind.ema21,
            "atr": ind.atr, "atr_avg20": ind.atr_avg20, "adx": ind.adx,
            "technical_confirmed": 1, "pass_pct": factor_pass_pct, "hard_gates_ok": factor_hard_gates_ok,
            "confidence": "patroon bevestigd",
            "reason": factor_breakdown,
            "stop_loss": stop_take.stop_loss, "take_profit": stop_take.take_profit,
            "context_note": None, "is_practice": 0, "plain_explanation": None,
            "suggested_entry_low": None, "suggested_entry_high": None,
            "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
        }
        signal_id = repo.insert_signal(signal_data)

        stale = repo.auto_ignore_stale_pending_for_coin(coin, exclude_signal_id=signal_id)
        if stale:
            logger.info("%s oude nog niet genomen melding(en) voor %s automatisch genegeerd (nieuw trendlijn+terugtest-signaal)",
                         len(stale), coin)
            for user in stale:
                try:
                    repo.create_notification(
                        user["id"], "expired_signal",
                        f"Kans op {coin} vervallen",
                        f"Een oude melding op {coin} is vervangen door een nieuw signaal.",
                        f"/coins/{coin}",
                    )
                except Exception:
                    logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

        def _trendline_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            base = f"Entry {ind.price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            if sniper_entry_price is not None:
                base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
            return base

        # premise_level = current_value: de lijnwaarde op het moment van
        # bevestiging, de trigger-prijs van deze trade — zelfde rol als
        # match.neckline bij een chart-patroon.
        await fanout_confirmed_signal(
            signal_id, coin, direction, ind.price, stop_take.stop_loss, stop_take.take_profit, current_value,
            title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, {pattern_label}",
            make_body=_trendline_body,
            kansberekening=kansberekening,
            hard_gates_ok=bool(factor_hard_gates_ok),
            reason=factor_breakdown,
        )
        repo.set_trendline_retest_key(coin, key)

    return {
        "kind": "trendlijn+terugtest", "direction": direction,
        "score": _candidate_score(ind.price, stop_take.stop_loss, stop_take.take_profit),
        "notify": notify,
    }


# Dedup-marge voor de patroon-melding: hoe dicht de neckline/stop van een
# nieuw gevonden patroon bij die van het laatst gemelde patroon voor deze
# coin+richting moet liggen om als "hetzelfde patroon" te tellen. Zelfde
# aanpak als TRENDLINE_DEDUP_ATR_MULTIPLE hierboven.
PATTERN_DEDUP_ATR_MULTIPLE = 1.0


def _same_pattern(existing_key: Optional[str], direction: str, match, atr: float) -> bool:
    if not existing_key:
        return False
    try:
        prev_direction, prev_name, prev_neckline_s = existing_key.split(":")
        prev_neckline = float(prev_neckline_s)
    except (ValueError, AttributeError):
        return False
    if prev_direction != direction or prev_name != match.name or not atr:
        return False
    return abs(prev_neckline - match.neckline) <= PATTERN_DEDUP_ATR_MULTIPLE * atr


def _valid_stop_take(direction: str, entry_price: float, stop_loss: float, take_profit: float) -> bool:
    """Ligt de stop aan de verliezende en de take aan de winnende kant van de
    prijs waarop we melden? Patroongeometrie (of een prijs die sinds de
    doorbraak flink is doorgelopen) kan anders een omgekeerde stop/take
    opleveren, en die gaat ongecontroleerd de positiegrootte en de
    automatische trackrecord in."""
    if direction == "long":
        return stop_loss < entry_price < take_profit
    return take_profit < entry_price < stop_loss


def _correlated_with_btc_divergence(coin: str, match, btc_divergence_direction: Optional[str]) -> bool:
    """True als dit een divergence-match is die waarschijnlijk gewoon BTC's
    eigen beweging weerspiegelt, niet een eigen kans van deze coin: altcoins
    bewegen sterk gecorreleerd met BTC op een 4u-timeframe, dus een korte
    BTC-dip (of -rally) kan op tien coins tegelijk als een "eigen" RSI-
    divergence gezien worden terwijl het één marktbeweging is die tien keer
    apart gemeld wordt (zie de burst van 9x "bearish divergence" in dezelfde
    cyclus die tot deze check leidde). Alleen van toepassing op divergence
    (top/bottom/wedge vereisen een eigen structuurbreuk, geen 2-punts
    RSI-vergelijking, en zijn dus minder gevoelig voor pure correlatie-ruis).
    BTC's eigen divergence wordt nooit tegen zichzelf onderdrukt."""
    if coin == "BTC" or btc_divergence_direction is None:
        return False
    if match.name not in ("bullish divergence", "bearish divergence"):
        return False
    return match.direction == btc_divergence_direction


async def _find_chart_pattern_candidate(
    coin: str, df, ind, btc_divergence_direction: Optional[str] = None,
) -> Optional[dict]:
    """Los van de dagtrading-richting van deze scan-cyclus: een chart-
    patroon (top/bottom, head & shoulders, kanaal/wedge, divergence) heeft
    zijn EIGEN richting uit de vorm zelf, niet uit ind.ema9/ind.ema21. Geen
    percentage-toets, geen harde eisen (R:R/dagtrend/BTC-trend) — een
    bevestigd patroon is zelf de bevestiging, zie
    docs/superpowers/specs/2026-09-22-patroonherkenning-design.md.

    Zelfde uitgestelde-melding-opzet als _find_breakout_retest_candidate:
    geeft een kandidaat terug (of None) in plaats van meteen te melden en
    de signals-rij aan te maken. Verliest deze kandidaat het van een
    sterkere structurele kandidaat voor dezelfde coin en richting, dan
    wordt er nooit een signals-rij voor aangemaakt — anders bleef er een
    verweesde rij zonder journaalregel of melding achter."""
    trendlines = indicators.detect_trendlines(df, ind.atr)
    window_len = len(df.tail(indicators.SR_ZONE_LOOKBACK))

    candidates: list = []
    candidates += patterns.find_reversal_patterns(df)
    wedge = patterns.classify_channel_wedge(df, trendlines, ind.atr)
    if wedge:
        candidates.append(wedge)
    divergence = patterns.find_divergence(df)
    if divergence and not _correlated_with_btc_divergence(coin, divergence, btc_divergence_direction):
        candidates.append(divergence)

    # Alle drie detectoren geven confirmed_index in dezelfde lokale
    # venster-ruimte terug, dus "hoe oud is deze match" is hier een eerlijke
    # vergelijking: een patroon dat al tientallen candles geleden bevestigde
    # is geen live kans meer, en mag ook niet de recentheids-selectie
    # hieronder winnen.
    candidates = [
        c for c in candidates
        if (window_len - 1) - c.confirmed_index <= patterns.NECKLINE_RETEST_MAX_WAIT_CANDLES
    ]
    if not candidates:
        return None
    match = max(candidates, key=lambda m: m.confirmed_index)

    key = f"{match.direction}:{match.name}:{match.neckline:.8f}"
    if _same_pattern(repo.get_pattern_key(coin), match.direction, match, ind.atr):
        return None

    entry_options = patterns.find_entry_options(df, match, ind.atr, trendlines=trendlines)

    used_pattern_stop_take = (
        match.stop_loss is not None and match.target is not None and _valid_stop_take(
            match.direction, ind.price, match.stop_loss, match.target,
        )
    )
    if used_pattern_stop_take:
        stop_loss, take_profit = match.stop_loss, match.target
    else:
        # geen structuurbevestigde match (divergence zonder structuurpivot
        # tussen de twee afwijkende pivots) of een patroon waarvan de
        # stop/take niet meer aan de juiste kant van de live prijs ligt:
        # terugval op de bestaande ATR-methode (zie de spec, sectie
        # "Stop/take").
        stop_take = risk.compute_stop_take(match.direction, ind.price, ind.atr)
        stop_loss, take_profit = stop_take.stop_loss, stop_take.take_profit

    async def notify() -> None:
        # Zones lokaal berekend, net als _find_breakout_retest_candidate
        # elders in dit bestand al doet — geen gedeelde cache tussen de
        # drie kandidaat-functies in dit bestand. Hier, binnen notify(),
        # in plaats van in de outer functie: compute_full_confirmation
        # doet een echte Binance-aanroep (dagcandle) en signal_data/
        # repo.insert_signal draaien toch al alleen voor de winnende
        # kandidaat van deze cyclus — de toetsing eerder draaien zou dat
        # werk verspillen voor elke kandidaat die deze cyclus verliest.
        #
        # Vóór auto_ignore_opposite_pending, niet erna: die stuurt gebruikers
        # al een "je vorige signaal is achterhaald"-melding, en patroon mag
        # nooit geblokkeerd worden (technical_confirmed blijft vast 1) — als
        # compute_full_confirmation hier zou knallen na de opruiming, zou de
        # gebruiker te horen krijgen dat zijn oude kans vervallen is zonder
        # dat er een nieuwe voor in de plaats komt.
        zones = indicators.detect_sr_zones(df)
        # daily_trend_hard_gate=False: een chart-patroon (top/bottom, head &
        # shoulders, wedge, divergence) is per definitie een omkeersignaal —
        # de dagtrend nog de oude kant op zien wijzen is dan geen zwakte,
        # dat is precies wanneer een omkeerpatroon zijn werk doet. Zie
        # indicators.confirms_direction's docstring voor de volledige
        # redenering. Uitbraak+terugtest/trendlijn+terugtest (hierboven in
        # dit bestand) zijn geen zuivere omkeersignalen en houden de harde
        # eis wel.
        _, factor_breakdown, factor_pass_pct, factor_hard_gates_ok = await compute_full_confirmation(
            coin, match.direction, df, ind, zones, daily_trend_hard_gate=False,
        )

        # Kansberekening (zelfde formule als web/main.py's weergave, zie
        # repo.pattern_kansberekening) bepaalt hier of de pushmelding
        # sowieso verstuurd wordt, per gebruiker tegen diens EIGEN drempel
        # (confirm_threshold_pct) — zie _fanout_confirmed_signal. Zonder
        # data (None) telt altijd als niet bevestigd, ongeacht de drempel.
        # De signals-rij en het journaal blijven wel gewoon bestaan
        # (technical_confirmed blijft vast 1, nooit blokkeren voor het
        # dashboard/trackrecord) — alleen de pushmelding zelf wordt per
        # gebruiker overgeslagen als die gebruiker deze kans niet als
        # bevestigd zou zien.
        pattern_stats = repo.pattern_winrate_stats().get(match.name)
        kansberekening = repo.pattern_kansberekening(factor_pass_pct, pattern_stats)

        # Een nog niet genomen melding voor de tegenovergestelde richting
        # van dezelfde coin is achterhaald zodra hier een nieuw patroon
        # bevestigt: je kan niet serieus tegelijk long en short op dezelfde
        # coin overwegen. Zelfde mechanisme als process_day_trading_signal,
        # hier voor de eigen patroon-kans (auto_ignore_opposite_pending
        # dekt zowel day_trading als patroon, swing blijft buiten schot).
        ignored = repo.auto_ignore_opposite_pending(coin, match.direction)
        if ignored:
            logger.info("%s nog niet genomen tegenovergestelde melding(en) voor %s automatisch genegeerd (patroon)",
                         len(ignored), coin)
            for user in ignored:
                try:
                    repo.create_notification(
                        user["id"], "expired_signal",
                        f"Kans op {coin} vervallen",
                        f"Een nieuwe {match.direction}-melding op {coin} maakte de vorige kans achterhaald.",
                        f"/coins/{coin}",
                    )
                except Exception:
                    logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

        # suggested_entry_low/high zijn bestaande kolommen (van een eerder
        # plan, daar gevuld met de dagtrading-entry-zone-suggestie) — hier
        # hergebruikt voor exact hetzelfde soort informatie (een optionele,
        # tweede entry-band naast de live prijs), in plaats van twee nieuwe
        # kolommen voor hetzelfde concept. Task 8 leest ze uit voor de
        # "Retest: ..."-regel op de kaart. None zolang er nog geen retest is.
        sniper = indicators.find_sniper_entry_price(match.direction, df)
        sniper_entry_price, sniper_reason = sniper if sniper else (None, None)

        signal_data = {
            "message_id": None, "coin": coin, "direction": match.direction,
            "category": "day_trading", "trade_type": "patroon", "pattern_name": match.name,
            "price": ind.price, "rsi": ind.rsi, "macd": ind.macd, "macd_signal": ind.macd_signal,
            "volume_ratio": ind.volume_ratio, "ema9": ind.ema9, "ema21": ind.ema21,
            "atr": ind.atr, "atr_avg20": ind.atr_avg20, "adx": ind.adx,
            "technical_confirmed": 1, "pass_pct": factor_pass_pct, "hard_gates_ok": factor_hard_gates_ok,
            "confidence": "patroon bevestigd",
            "reason": factor_breakdown,
            "stop_loss": stop_loss, "take_profit": take_profit,
            "context_note": None, "is_practice": 0, "plain_explanation": None,
            "suggested_entry_low": entry_options["retest_low"],
            "suggested_entry_high": entry_options["retest_high"],
            "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
        }
        signal_id = repo.insert_signal(signal_data)

        # Zelfde soort opruiming als hierboven, maar voor het geval een
        # oude nog niet genomen melding voor dezelfde coin en richting niet
        # meer als "open" gold (bv. iedereen had die kans al afgesloten) en
        # er dus een los nieuw signaal is aangemaakt in plaats van een
        # update.
        stale = repo.auto_ignore_stale_pending_for_coin(coin, exclude_signal_id=signal_id)
        if stale:
            logger.info("%s oude nog niet genomen melding(en) voor %s automatisch genegeerd (nieuw patroon-signaal)",
                         len(stale), coin)
            for user in stale:
                try:
                    repo.create_notification(
                        user["id"], "expired_signal",
                        f"Kans op {coin} vervallen",
                        f"Een oude melding op {coin} is vervangen door een nieuw signaal.",
                        f"/coins/{coin}",
                    )
                except Exception:
                    logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

        def _pattern_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            retest_note = (
                f" · Retest {entry_options['retest_low']:.4f}–{entry_options['retest_high']:.4f}"
                if entry_options["retest_low"] is not None else ""
            )
            # Als de patroon-eigen stop/take niet aan de juiste kant van de
            # live prijs bleken te liggen (C2-guard, used_pattern_stop_take=
            # False) is het uitbraakniveau van het patroon zelf niet meer de
            # premisse van deze trade — dan de live prijs tonen in plaats
            # van een uitbraakniveau dat niet meer bij de getoonde
            # stop/take past.
            level_label = (
                f"Uitbraak {entry_options['breakout_level']:.4f}{retest_note}"
                if used_pattern_stop_take else f"Prijs {ind.price:.4f}"
            )
            base = (
                f"{level_label} · "
                f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            )
            if sniper_entry_price is not None:
                base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
            return base

        # premise_level = match.neckline: de uitbraak/trigger-prijs van het
        # patroon is de premisse van deze trade (net als watch["price_level"]
        # bij een swing-watch), niet ind.price (de live prijs op het moment
        # van detectie, die intussen al verder kan zijn doorgelopen).
        await fanout_confirmed_signal(
            signal_id, coin, match.direction, ind.price, stop_loss, take_profit, match.neckline,
            title=f"{push_notify.coin_symbol(coin)} {coin} {match.direction}, {match.name}",
            make_body=_pattern_body,
            kansberekening=kansberekening,
            hard_gates_ok=bool(factor_hard_gates_ok),
            reason=factor_breakdown,
        )
        repo.set_pattern_key(coin, key)

    return {
        "kind": f"patroon ({match.name})", "direction": match.direction,
        "score": _candidate_score(ind.price, stop_loss, take_profit),
        "notify": notify,
    }


SMC_ZONE_SEARCH_LOOKBACK_30M = 60  # 30m-candles, ongeveer anderhalve dag


def _smc_last_candle_state(candle, zone_low: float, zone_high: float, direction: str) -> tuple[bool, bool, bool]:
    """Bepaalt voor één gesloten 15m-candle en één bouwende zone drie
    onafhankelijke toestanden: (in_zone, rejected, passed_without_rejection).
    in_zone: de candle raakte de zone (wick of volledige overlap).
    rejected: de candle raakte de zone EN sloot er weer buiten aan de
    kant die de setup ongeldig maakt voor voortzetting maar geldig maakt
    als entry-trigger (short: sluit onder zone_low, long: sluit boven
    zone_high) — dit is het moment waarop _complete_smc_setup het signaal
    maakt.
    passed_without_rejection: het SPIEGELBEELD van rejected, niet
    hetzelfde teken. Een short-zone ligt BOVEN de prijs die er van
    onderaf naartoe beweegt (na de bearish structuurbreuk) — 'voorbij
    zonder afwijzing' betekent dus dat de candle DOOR de top van de zone
    brak (close boven zone_high) zonder ooit een rejectie-close onder
    zone_low te laten zien: de supply hield niet stand, de setup is
    achterhaald. Long is het spiegelbeeld (close onder zone_low, door de
    bodem heen). Vóórdat de zone ooit bereikt is — bijvoorbeeld een
    short-setup waarvan de laatste close nog onder zone_low ligt, op weg
    naar boven — is dit nadrukkelijk GEEN 'passed': met hetzelfde teken
    als rejected zou elke net aangemaakte, nog nooit geraakte setup de
    cyclus erna meteen weer weggegooid worden."""
    in_zone = (
        zone_low <= candle["low"] <= zone_high
        or zone_low <= candle["high"] <= zone_high
        or (candle["low"] <= zone_low and candle["high"] >= zone_high)
    )
    rejected = in_zone and (
        (direction == "short" and candle["close"] < zone_low) or
        (direction == "long" and candle["close"] > zone_high)
    )
    passed_without_rejection = (
        (direction == "short" and candle["close"] > zone_high) or
        (direction == "long" and candle["close"] < zone_low)
    )
    return in_zone, rejected, passed_without_rejection


SMC_ENTRY_CANDLE_MINUTES = 15

# Hoeveel 15m-candles fase 1 hoogstens per bouwende setup beoordeelt: alle
# candles die sinds de vorige scan gesloten zijn. De scan draait elke 20
# minuten (deploy/crypto-market-scan.timer), dus er kunnen er twee sluiten
# tussen twee runs — alleen de allerlaatste bekijken sloeg zo één op de
# vier 15m-candles over, inclusief een afwijzing of doorbraak die precies
# daarop gebeurde. Begrensd (geen onbeperkte inhaalslag) zodat een
# afwijzing waar _complete_smc_setup geen geldige trade van kon maken niet
# elke volgende cyclus opnieuw als trigger terugkomt.
SMC_MAX_CANDLES_PER_CHECK = 2


def _smc_candles_since(closed_15m, since_iso: str) -> list:
    """Gesloten 15m-candles die NA since_iso sloten (updated_at: de
    sluittijd van de laatste candle waartegen de setup al beoordeeld is),
    oudste eerst, hoogstens
    SMC_MAX_CANDLES_PER_CHECK. Een candle die al sloot vóór de setup
    (opnieuw) gedefinieerd werd, heeft die zone nooit 'gezien' en mag hem
    dus ook niet afwijzen of ongeldig maken — dat werd bij het aanmaken al
    tegen de laatste gesloten candle getoetst."""
    since = datetime.fromisoformat(since_iso)
    close_times = closed_15m["timestamp"] + timedelta(minutes=SMC_ENTRY_CANDLE_MINUTES)
    fresh = closed_15m[close_times > since].tail(SMC_MAX_CANDLES_PER_CHECK)
    return [candle for _, candle in fresh.iterrows()]


async def _check_smc_setup(coin: str) -> Optional[dict]:
    """SMC/ICT-liquidity-setup: structuurbreuk + sweep op 30m, terugtrek
    naar een FVG/order-block-overlap op 15m. Volledig autonoom, los van
    de drie bestaande structurele detectoren (uitbraak+terugtest,
    trendlijn+terugtest, patroon) en van hun top-3-per-cyclus-cap. Geeft
    de smc_setups-rij terug zodra de zone geraakt EN afgewezen is
    (_complete_smc_setup maakt daar het echte signaal van), None in elk
    ander geval (geen structuurbreuk, geen sweep, geen confluence-zone, of
    wel een bouwende setup maar nog geen afwijzing).

    Alles wordt beoordeeld op GESLOTEN candles (iloc[:-1], zelfde conventie
    als de volume- en candlepatroon-factoren in indicators.py): de laatste
    candle van de exchange is nog in wording, een 'close onder de swing-low'
    of 'afwijzing' halverwege die candle kan voor het sluiten nog volledig
    omdraaien.

    Fase 1: bestaande bouwende setups voor deze coin toetsen tegen de
    15m-candles die sinds hun laatste bijwerking gesloten zijn,
    ONAFHANKELIJK van of er deze cyclus een nieuwe structuurbreuk gevonden
    wordt — een breuk is een eenmalige gebeurtenis op de candle die op dat
    moment de laatste was, een bouwende setup moet de cycli daarna blijven
    bestaan tot de zone geraakt of doorbroken wordt. Fase 2: pas daarna
    zoeken naar een nieuwe breuk."""
    df_15m = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="15m")
    closed_15m = df_15m.iloc[:-1]
    last_candle = closed_15m.iloc[-1]

    existing = [s for s in repo.list_forming_smc_setups() if s["coin"] == coin]
    for existing_setup in existing:
        for candle in _smc_candles_since(closed_15m, existing_setup["updated_at"]):
            in_zone, rejected, passed_without_rejection = _smc_last_candle_state(
                candle, existing_setup["zone_low"], existing_setup["zone_high"], existing_setup["direction"],
            )
            if rejected:
                return existing_setup
            # Geen extra in_zone-eis: de candle die door de zone heen sluit
            # heeft vrijwel altijd zelf een staart in de zone, en rejected en
            # passed_without_rejection sluiten elkaar al uit (close aan
            # tegenovergestelde kanten van de zone).
            if passed_without_rejection:
                repo.invalidate_smc_setup(existing_setup["id"])
                break

    # +1: de nog vormende candle valt hieronder weg voor de breuk-toets.
    df_30m = await asyncio.to_thread(
        exchange.fetch_ohlcv, coin, timeframe="30m", limit=SMC_ZONE_SEARCH_LOOKBACK_30M + 1,
    )
    closed_30m = df_30m.iloc[:-1]
    structure_break = indicators.find_structure_break(closed_30m)
    if structure_break is None:
        return None
    direction = structure_break.direction

    # Een nieuwe breuk in de TEGENGESTELDE richting van een bestaande
    # bouwende setup maakt die setup achterhaald (de markt heeft zijn
    # structuur omgedraaid voordat de oude zone geraakt werd).
    for existing_setup in existing:
        if existing_setup["direction"] != direction:
            repo.invalidate_smc_setup(existing_setup["id"])

    sweep = indicators.find_liquidity_sweep_before_break(closed_30m, structure_break)
    if sweep is None:
        return None

    fvgs = indicators.find_fair_value_gaps(closed_15m, direction)
    order_blocks = indicators.find_order_blocks(closed_15m, direction)
    zone = indicators.find_confluence_zone(fvgs, order_blocks)
    if zone is None:
        return None
    zone_low, zone_high = zone

    # Liquidity-doel: de dichtstbijzijnde tegengestelde pivot die de prijs
    # sinds de breuk nog NIET geraakt heeft, op hetzelfde 30m-venster als
    # de structuurbreuk zelf (dezelfde bron als structure_level en
    # sweep_price, geen extra candle-fetch). Alleen "voorbij de zone" was
    # niet genoeg: de net gebroken pivot zelf, en elke oudere pivot waar de
    # doorbraak-beweging al doorheen liep, ligt ook voorbij de zone maar
    # die liquidity is al opgehaald — zo'n doel gaf een take profit aan de
    # verkeerde kant van de entry zodra de afwijzing eronder sloot. Hier
    # WEL inclusief de nog vormende 30m-candle (df_30m, niet closed_30m):
    # een niveau waar de prijs al doorheen handelde is opgehaald, of die
    # candle nu al gesloten is of niet.
    since_break = df_30m.iloc[structure_break.break_index:]
    if direction == "long":
        untouched_from = max(zone_high, float(since_break["high"].max()))
    else:
        untouched_from = min(zone_low, float(since_break["low"].min()))
    target_kind = "high" if direction == "long" else "low"
    target_pivots = [
        p for p in indicators._find_pivots(closed_30m)
        if p.kind == target_kind and (
            (direction == "long" and p.price > untouched_from) or
            (direction == "short" and p.price < untouched_from)
        )
    ]
    if not target_pivots:
        return None
    liquidity_target_pivot = min(target_pivots, key=lambda p: abs(p.price - untouched_from))

    # Een bouwende setup is pas zinvol zolang de koers nog naar de zone
    # moet terugtrekken (short: nog eronder, long: nog erboven). Zonder
    # deze eis kon fase 1 hierboven een setup opruimen omdat de koers door
    # de zone heen sloot, en maakte deze fase dezelfde zone in dezelfde
    # cyclus meteen weer aan met alert_sent=0 — een tweede 'bouwt op'-push
    # voor een zone die net ongeldig was geworden.
    last_close = float(last_candle["close"])
    if (direction == "short" and last_close >= zone_low) or (direction == "long" and last_close <= zone_high):
        return None

    setup_id = repo.upsert_smc_setup(
        coin, direction, zone_low, zone_high,
        structure_level=structure_break.broken_pivot.price,
        sweep_price=sweep.price,
        liquidity_target=liquidity_target_pivot.price,
        seen_until=(last_candle["timestamp"] + timedelta(minutes=SMC_ENTRY_CANDLE_MINUTES)).isoformat(),
    )

    setups = repo.list_forming_smc_setups()
    setup = next((s for s in setups if s["id"] == setup_id), None)
    if setup is None:
        return None  # deze breuk + sweep leverde al een signaal op of is vervallen (zie upsert_smc_setup)

    _, rejected, _ = _smc_last_candle_state(last_candle, zone_low, zone_high, direction)
    if rejected:
        return setup

    if not setup["alert_sent"]:
        title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, SMC-setup bouwt op"
        body = (
            f"Structuur + sweep gezien ({direction}), zone {zone_low:.4f}-{zone_high:.4f}. "
            f"Zet je {direction} limit order klaar."
        )
        for user in repo.list_users():
            quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
            try:
                await push_notify.send_push(user["id"], title, body, "/smc", silent=quiet)
            except Exception:
                logger.exception("SMC-bouwend-melding voor %s naar gebruiker %s is mislukt", coin, user["username"])
        repo.mark_smc_alert_sent(setup_id)
    return None


STOP_MARGIN_PCT = 0.1    # procent, marge voorbij de sweep
TARGET_MARGIN_PCT = 0.5  # procent, marge vóór de liquidity


async def _complete_smc_setup(coin: str, setup: dict) -> Optional[int]:
    """Bouwt het echte signaal zodra _check_smc_setup een afgewezen zone
    teruggeeft, en geeft de nieuwe signal_id terug (None als er geen
    geldige trade van te maken was). Geen ATR: stop en doel zijn volledig
    structuur-gebaseerd, de hele premisse van een smc-setup is dat de
    sweep de stop en de volgende liquidity het doel bepaalt. sign is voor
    zowel stop als doel hetzelfde teken, dat is geen typefout: voor short
    ligt de stop BOVEN de geveegde high (verder van de entry af) en het
    doel ligt ook BOVEN de liquidity-low (dichter bij de entry, 'net
    vóór' het niveau) — voor long allebei eronder. Rekenvoorbeeld (short):
    sweep_price 2820, liquidity_target 2600 -> stop 2823, doel 2613."""
    direction = setup["direction"]
    sign = -1 if direction == "long" else 1
    stop_loss = setup["sweep_price"] + STOP_MARGIN_PCT / 100 * setup["sweep_price"] * sign
    take_profit = setup["liquidity_target"] + TARGET_MARGIN_PCT / 100 * setup["liquidity_target"] * sign

    df_15m = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="15m")
    entry_price = float(df_15m["close"].iloc[-1])

    # Stop en doel liggen vast sinds de setup bouwde, de live prijs niet:
    # een afwijzing die al voorbij het doel sloot, of een prijs die sinds de
    # afwijzing boven de stop (short) uitliep, is geen trade meer. Geen
    # ATR-terugval zoals bij patroon — smc's hele premisse is structuur-
    # gebaseerde stop/doel, dan liever geen signaal.
    if not _valid_stop_take(direction, entry_price, stop_loss, take_profit):
        logger.info(
            "SMC-setup %s voor %s niet gemeld: stop %.4f / doel %.4f liggen niet aan de juiste kant van entry %.4f (%s)",
            setup["id"], coin, stop_loss, take_profit, entry_price, direction,
        )
        return None

    # Zelfde ondergrens als het dagtrading-pad (signal_processor.py), zelfde
    # "geen signaal" in plaats van "signaal met lagere confidence" als
    # hierboven bij _valid_stop_take: smc heeft geen pass_pct/hard_gates_ok
    # confidence-schaal om een zwakke verhouding in te laten wegen, dus een
    # setup die er niet aan voldoet mag geen signaal worden.
    risk_distance = abs(entry_price - stop_loss)
    reward_distance = abs(take_profit - entry_price)
    risk_reward_ratio = (reward_distance / risk_distance) if risk_distance else 0.0
    if risk_reward_ratio < MIN_RISK_REWARD_RATIO:
        logger.info(
            "SMC-setup %s voor %s niet gemeld: risico/rendement %.2f tegen 1 ligt onder de ondergrens van %s "
            "(stop %.4f / doel %.4f / entry %.4f, %s)",
            setup["id"], coin, risk_reward_ratio, MIN_RISK_REWARD_RATIO,
            stop_loss, take_profit, entry_price, direction,
        )
        return None

    # Zelfde opruiming als de andere detectoren vóór hun insert_signal: een
    # nog niet genomen melding voor de andere richting op deze coin is
    # achterhaald zodra hier een smc-signaal ontstaat.
    ignored = repo.auto_ignore_opposite_pending(coin, direction)
    if ignored:
        logger.info("%s nog niet genomen tegenovergestelde melding(en) voor %s automatisch genegeerd (smc)",
                    len(ignored), coin)
        for user in ignored:
            try:
                repo.create_notification(
                    user["id"], "expired_signal",
                    f"Kans op {coin} vervallen",
                    f"Een nieuwe {direction}-melding op {coin} maakte de vorige kans achterhaald.",
                    f"/coins/{coin}",
                )
            except Exception:
                logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

    reason = (
        f"SMC-liquidity-setup: structuur brak op {setup['structure_level']:.4f}, "
        f"sweep op {setup['sweep_price']:.4f}, zone {setup['zone_low']:.4f}-{setup['zone_high']:.4f}, "
        f"doel bij liquidity {setup['liquidity_target']:.4f}."
    )

    sniper = indicators.find_sniper_entry_price(direction, df_15m)
    sniper_entry_price, sniper_reason = sniper if sniper else (None, None)

    signal_data = {
        "message_id": None, "coin": coin, "direction": direction,
        "category": "day_trading", "trade_type": "smc", "pattern_name": "SMC liquidity sweep",
        "price": entry_price, "rsi": None, "macd": None, "macd_signal": None,
        "volume_ratio": None, "ema9": None, "ema21": None,
        "atr": None, "atr_avg20": None, "adx": None,
        "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1,
        "confidence": "SMC-setup bevestigd",
        "reason": reason,
        "stop_loss": stop_loss, "take_profit": take_profit,
        "context_note": None, "is_practice": 0, "plain_explanation": None,
        "suggested_entry_low": None, "suggested_entry_high": None,
        "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
    }
    signal_id = repo.insert_signal(signal_data)
    repo.complete_smc_setup(setup["id"], signal_id)

    def _smc_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
        base = (
            f"Entry {entry_price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}\n"
            f"Zone {setup['zone_low']:.4f}-{setup['zone_high']:.4f}, doel bij liquidity {setup['liquidity_target']:.4f}"
        )
        if sniper_entry_price is not None:
            base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
        return base

    premise_level = setup["zone_high"] if direction == "short" else setup["zone_low"]
    await fanout_confirmed_signal(
        signal_id, coin, direction, entry_price, stop_loss, take_profit, premise_level,
        title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, SMC liquidity sweep",
        make_body=_smc_body,
        reason=reason,
    )
    return signal_id


async def _run_smc_check(coin: str) -> Optional[str]:
    """De SMC-check voor één coin, met een eigen try/except: een
    Binance-storing op 30m/15m mag de 4u-detectoren niet blokkeren, en
    omgekeerd (daarom draait scan_market dit vóór en buiten zijn 4u-blok).
    Geeft de richting terug als er deze cyclus een smc-signaal ontstond,
    zodat scan_market voor dezelfde coin geen tegenstrijdige melding meer
    stuurt."""
    try:
        setup = await _check_smc_setup(coin)
        if setup and await _complete_smc_setup(coin, setup) is not None:
            return setup["direction"]
    except Exception:
        logger.exception("SMC-check voor %s is mislukt, ga door met de rest van de cyclus", coin)
    return None


async def scan_market() -> None:
    if not repo.is_market_scan_enabled():
        logger.info("Marktscan staat uit (noodrem), niets gedaan")
        return

    coins = repo.list_coins()
    logger.info("Marktscan gestart, %s coins in de dynamische lijst", len(coins))

    # BTC's eigen trend eenmalig per cyclus ophalen (niet per altcoin
    # herhalen): als BTC zelf zijwaarts beweegt, is een altcoin-signaal
    # vaker ruis dan een echte kans. Kan deze ophaling zelf mislukken, dan
    # gaat de scan gewoon door zonder de vlak-check (fail-open), net als
    # elke andere Binance-storing hieronder per coin.
    btc_flat = False
    # BTC's eigen divergence deze cyclus, eenmalig herbruikt om te bepalen
    # of een altcoin's "eigen" divergence waarschijnlijk gewoon BTC's
    # correlatie is (zie _correlated_with_btc_divergence). None als BTC
    # zelf geen divergence toont, of als de ophaling hieronder al faalt.
    btc_divergence_direction: Optional[str] = None
    try:
        btc_df = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC")
        btc_ind = indicators.compute_indicators(btc_df)
        btc_flat = indicators.btc_is_flat(btc_ind)
        if btc_flat:
            logger.info("BTC is zijwaarts deze cyclus, altcoin-signalering overgeslagen")
        btc_own_divergence = patterns.find_divergence(btc_df)
        if btc_own_divergence:
            btc_divergence_direction = btc_own_divergence.direction
    except Exception:
        logger.exception("Kon BTC's eigen trend niet ophalen, ga verder zonder de vlak-check")

    # Structurele kandidaten (uitbraak/trendlijn/patroon) van de hele
    # cyclus, over alle coins heen — pas na de hele scan geëvalueerd tegen
    # MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE, zie de constante hierboven.
    cycle_structural_candidates: list[dict] = []

    for coin_row in coins:
        coin = coin_row["symbol"]
        # SMC vóór de BTC-vlak-rem en buiten het 4u-blok hieronder: de
        # vlak-rem beschermt de kwaliteit van de 4u-detectoren in een
        # zijwaartse markt, smc's structuur+sweep+zone werkt lokaal per coin
        # op 30m/15m en staat daar los van. Een 4u-fout voor deze coin mag
        # de smc-check evenmin overslaan.
        smc_direction = await _run_smc_check(coin)
        if btc_flat and coin != "BTC":
            continue
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"

            # Patronen in wording (nog niet doorbroken): puur informatief,
            # geen melding/signals-rij, alleen ververst in forming_patterns
            # zodat de coin-pagina en het dashboard-overzicht altijd de
            # actuele stand van deze cyclus tonen. df/ind hierboven al
            # opgehaald, geen extra Binance-aanroep nodig.
            forming_trendlines = indicators.detect_trendlines(df, ind.atr)
            forming: list[dict] = []
            wedge_forming = patterns.find_forming_wedge(df, forming_trendlines, ind)
            if wedge_forming:
                forming.append(wedge_forming)
            forming += patterns.find_forming_reversal_patterns(df)
            repo.replace_forming_patterns(coin, forming)

            # Drie structurele mechanismen (uitbraak+terugtest, trendlijn+
            # terugtest, patroon) draaien onafhankelijk van elkaar en
            # kunnen voor dezelfde coin dezelfde richting vinden, elk met
            # een eigen stop/take — zonder afstemming kreeg een gebruiker
            # dan twee tegenstrijdige meldingen voor dezelfde kans (bv. SOL
            # long met twee verschillende stops). Elke functie bepaalt hier
            # daarom alleen OF hij zou melden (geen melding, geen
            # DB-schrijving); pas hierna wordt per richting de sterkste
            # kandidaat daadwerkelijk gemeld (_candidate_score: risk:reward,
            # de enige maat die voor alle drie soorten gelijk berekenbaar is).
            structural: list[dict] = []
            breakout_candidate = await _find_breakout_retest_candidate(coin, direction, df, ind)
            if breakout_candidate:
                structural.append(breakout_candidate)
            trendline_candidate = await _find_trendline_retest_candidate(coin, direction, df, ind)
            if trendline_candidate:
                structural.append(trendline_candidate)
            pattern_candidate = await _find_chart_pattern_candidate(coin, df, ind, btc_divergence_direction)
            if pattern_candidate:
                structural.append(pattern_candidate)

            # Deze cyclus al een smc-signaal op deze coin gepusht: een
            # structurele kandidaat de andere kant op zou aan het eind van de
            # cyclus alsnog tegenovergesteld melden. Die kandidaat valt hier
            # af en dingt volgende cyclus gewoon opnieuw mee (zelfde als bij
            # de cyclus-limiet hieronder).
            if smc_direction:
                opposed = [c for c in structural if c["direction"] != smc_direction]
                if opposed:
                    logger.info(
                        "%s: %s structurele kandidaat/kandidaten tegen het smc-signaal (%s) in overgeslagen",
                        coin, len(opposed), smc_direction,
                    )
                    structural = [c for c in structural if c["direction"] == smc_direction]

            by_direction: dict[str, list[dict]] = {}
            for candidate in structural:
                by_direction.setdefault(candidate["direction"], []).append(candidate)

            # structural_directions_signaled: alle richtingen die deze coin
            # deze cyclus GEVONDEN heeft (niet per se gemeld, zie hieronder)
            # — genoeg om de generieke dagtrading-melding verderop te laten
            # wijken, ongeacht welke specifieke richting het was. Een
            # smc-signaal van deze cyclus telt ook mee: dat is al gepusht.
            structural_directions_signaled: set = set(by_direction.keys())
            if smc_direction:
                structural_directions_signaled.add(smc_direction)

            # Maar hoogstens ÉÉN kandidaat per coin dingt mee naar een
            # daadwerkelijke melding deze cyclus, ongeacht hoeveel
            # richtingen er gevonden zijn: uitbraak en trendlijn delen
            # altijd dezelfde EMA-richting en kunnen dus nooit onderling
            # botsen, maar een patroon heeft zijn EIGEN richting en kan wel
            # tegenovergesteld zijn aan wat uitbraak/trendlijn vinden (bv.
            # patroon short, trendlijn long voor dezelfde coin). Zonder deze
            # stap zou de cyclusbrede top-N hieronder (die alleen op score
            # sorteert, niet per coin dedupliceert) beide alsnog kunnen
            # melden — long én short voor dezelfde coin, tegenstrijdig.
            if structural:
                if len(by_direction) > 1:
                    logger.info(
                        "%s: structurele kandidaten in tegenstrijdige richtingen deze cyclus (%s)",
                        coin, ", ".join(f"{d} ({len(g)}x)" for d, g in by_direction.items()),
                    )
                overall_winner = max(structural, key=lambda c: c["score"])
                if len(structural) > 1:
                    logger.info(
                        "%s: %s structurele kandidaten totaal, '%s' (%s, risk:reward %.2f) wint",
                        coin, len(structural), overall_winner["kind"], overall_winner["direction"],
                        overall_winner["score"],
                    )
                cycle_structural_candidates.append({**overall_winner, "coin": coin})

            # Vóór de cooldown-check bepaald (in plaats van erna): een coin
            # met een al bestaand open signaal moet elke cyclus ververst
            # blijven, ook binnen de cooldown-periode na een verlies (zie
            # find_open_signal-dedup, spec Testen §2). Ook hergebruikt door
            # de confirms_direction-precheck verderop, in plaats van een
            # tweede find_open_signal-aanroep.
            was_open_before = repo.find_open_signal(coin, direction) is not None

            # Whiplash-rem: alleen relevant voor een NIEUW signaal, een
            # coin die al open staat moet net als bij de cooldown hierboven
            # altijd ververst blijven, ongeacht hoe vers de richting zelf
            # is. Elke cyclus geregistreerd (ook als dit een refresh is),
            # zodat de teller altijd de echte, actuele reeks weerspiegelt.
            consecutive = repo.record_scan_direction(coin, direction)
            if not was_open_before and consecutive < WHIPLASH_MIN_CONSECUTIVE_CYCLES:
                logger.info(
                    "%s %s overgeslagen: richting pas %s cyclus/cycli op rij, nog geen %s",
                    coin, direction, consecutive, WHIPLASH_MIN_CONSECUTIVE_CYCLES,
                )
                continue

            # Al een structureel signaal (zone/lijn/patroon) gemeld voor
            # deze coin deze cyclus, ONGEACHT de richting: een generieke
            # EMA-dagtrading-melding die de tegenovergestelde kant op wijst
            # is niet minder verwarrend dan eentje in dezelfde richting met
            # een ander stop/take (zie hierboven) — een gebruiker die long
            # én short op dezelfde coin tegelijk binnenkrijgt, snapt geen
            # van beide. Het bestaande auto_ignore_opposite_pending ruimt
            # zo'n tegenstelling later wel op in het journaal, maar de
            # pushmeldingen zelf zijn dan al verstuurd — dit voorkomt dat.
            # Specifiek (patroon/trendlijn/uitbraak) wint hier altijd van
            # generiek (EMA-trend), ook bij tegengestelde richtingen. Alleen
            # van toepassing op een NIEUW dagtrading-signaal — een al open
            # positie moet, net als bij whiplash/cooldown, altijd ververst
            # blijven.
            if not was_open_before and structural_directions_signaled:
                logger.info(
                    "%s %s overgeslagen: al een structureel signaal deze cyclus gemeld", coin, direction,
                )
                continue

            # Cooldown na een recent verlies op dezelfde coin+richting: mag
            # alleen een NIEUW signaal blokkeren (not was_open_before), nooit
            # het verversen van een signaal dat al open staat — dat zou een
            # gebruiker met een lopende trade zonder verse toetsing achter-
            # laten, alleen omdat er ooit eerder verlies op was.
            if not was_open_before and repo.recent_autonomous_loss(
                coin, direction, AUTO_SCAN_LOSS_COOLDOWN_HOURS,
            ):
                logger.info(
                    "%s %s overgeslagen: recent verlies binnen de cooldown", coin, direction,
                )
                continue

            # Cheap pre-filter, niet een tweede toetsing: alleen de
            # basisfactoren, zodat een coin die deze cyclus duidelijk niet
            # bevestigt en nog nooit een open signaal had geen kale,
            # afgewezen rij in `signals` achterlaat (elke cyclus, voor
            # tientallen coins, zou dat de tabel vervuilen zonder dat er
            # ooit een kans was). process_day_trading_signal doet hierna
            # nog steeds zijn eigen volledige toetsing (incl. eventuele
            # advanced factors) en blijft de enige bron van waarheid voor
            # technical_confirmed. Een coin met een al bestaand open
            # signaal slaat deze check over en gaat altijd door: die moet
            # elke cyclus ververst blijven, ook als hij nu niet meer
            # bevestigt.
            confirmed, _, _, _ = indicators.confirms_direction(ind, direction)
            if not confirmed and not was_open_before:
                continue

            interp = Interpretation(
                coin=coin, direction=direction, category="day_trading", unclear=False, reason="",
            )
            # Een afgewezen ("nog geen sterke kans") signaal krijgt nooit een
            # pushmelding, autonoom of gedeeld — zie process_day_trading_signal's
            # confirmed-check. De logboekregel en de trackrecord blijven
            # gewoon bestaan, alleen de melding zelf wordt overgeslagen.
            await process_day_trading_signal(None, interp, notify_on_update=False)
        except Exception:
            # Eén coin die faalt (bijvoorbeeld een tijdelijke Binance-storing)
            # mag de rest van de scan niet blokkeren.
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    # Nu pas, over de hele cyclus (alle coins) heen: de sterkste
    # MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE kandidaten daadwerkelijk
    # melden. De rest is deze cyclus gevonden maar wordt niet aangemaakt —
    # geen signals-rij, geen dedup-key — en dingt gewoon opnieuw mee in de
    # volgende cyclus als de kans dan nog geldig is.
    cycle_structural_candidates.sort(key=lambda c: c["score"], reverse=True)
    to_notify = cycle_structural_candidates[:MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE]
    skipped = cycle_structural_candidates[MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE:]
    if skipped:
        logger.info(
            "%s structurele kandidaten overgeslagen (cyclus-limiet %s bereikt): %s",
            len(skipped), MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE,
            ", ".join(f"{c['coin']} {c['direction']} {c['kind']} ({c['score']:.2f})" for c in skipped),
        )
    for candidate in to_notify:
        try:
            await candidate["notify"]()
        except Exception:
            logger.exception(
                "Melding voor %s %s (%s) is mislukt, ga door met de volgende",
                candidate["coin"], candidate["direction"], candidate["kind"],
            )

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
