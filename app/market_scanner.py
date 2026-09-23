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
from typing import Optional

from app import exchange, indicators, patterns, push_notify, repo, risk
from app.anthropic_interpret import Interpretation
from app.signal_processor import compute_full_confirmation, fanout_confirmed_signal, process_day_trading_signal

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

    async def notify() -> None:
        # Geen telegram_chat_id-gate meer (Taak 11): push_notify.send_push
        # slaat een gebruiker zonder push-abonnement zelf al stilzwijgend
        # over, en telegram_chat_id wordt sinds de overstap naar push nooit
        # meer ingevuld voor nieuwe gebruikers.
        for user in repo.list_users():
            if repo.is_coin_muted(user["id"], coin):
                continue
            force_silent = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
            try:
                title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, uitbraak + terugtest"
                body = f"Entry {ind.price:.4f} · Stop {stop_take.stop_loss:.4f} · Take profit {stop_take.take_profit:.4f}"
                await push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=force_silent)
            except Exception:
                logger.exception(
                    "Pushmelding (uitbraak-terugtest) voor %s naar gebruiker %s is mislukt", coin, user["username"],
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

    async def notify() -> None:
        # Geen telegram_chat_id-gate meer (Taak 11): push_notify.send_push
        # slaat een gebruiker zonder push-abonnement zelf al stilzwijgend
        # over, en telegram_chat_id wordt sinds de overstap naar push nooit
        # meer ingevuld voor nieuwe gebruikers.
        for user in repo.list_users():
            if repo.is_coin_muted(user["id"], coin):
                continue
            force_silent = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
            try:
                title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, trendlijn-terugtest"
                body = f"Entry {ind.price:.4f} · Stop {stop_take.stop_loss:.4f} · Take profit {stop_take.take_profit:.4f}"
                await push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=force_silent)
            except Exception:
                logger.exception(
                    "Pushmelding (trendlijn-terugtest) voor %s naar gebruiker %s is mislukt", coin, user["username"],
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


async def _find_chart_pattern_candidate(coin: str, df, ind) -> Optional[dict]:
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
    if divergence:
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
        _, factor_breakdown, factor_pass_pct, factor_hard_gates_ok = await compute_full_confirmation(
            coin, match.direction, df, ind, zones,
        )

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
            return (
                f"{level_label} · "
                f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            )

        # premise_level = match.neckline: de uitbraak/trigger-prijs van het
        # patroon is de premisse van deze trade (net als watch["price_level"]
        # bij een swing-watch), niet ind.price (de live prijs op het moment
        # van detectie, die intussen al verder kan zijn doorgelopen).
        await fanout_confirmed_signal(
            signal_id, coin, match.direction, ind.price, stop_loss, take_profit, match.neckline,
            title=f"{push_notify.coin_symbol(coin)} {coin} {match.direction}, {match.name}",
            make_body=_pattern_body,
        )
        repo.set_pattern_key(coin, key)

    return {
        "kind": f"patroon ({match.name})", "direction": match.direction,
        "score": _candidate_score(ind.price, stop_loss, take_profit),
        "notify": notify,
    }


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
    try:
        btc_df = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC")
        btc_ind = indicators.compute_indicators(btc_df)
        btc_flat = indicators.btc_is_flat(btc_ind)
        if btc_flat:
            logger.info("BTC is zijwaarts deze cyclus, altcoin-signalering overgeslagen")
    except Exception:
        logger.exception("Kon BTC's eigen trend niet ophalen, ga verder zonder de vlak-check")

    for coin_row in coins:
        coin = coin_row["symbol"]
        if btc_flat and coin != "BTC":
            continue
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"

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
            pattern_candidate = await _find_chart_pattern_candidate(coin, df, ind)
            if pattern_candidate:
                structural.append(pattern_candidate)

            by_direction: dict[str, list[dict]] = {}
            for candidate in structural:
                by_direction.setdefault(candidate["direction"], []).append(candidate)

            structural_directions_signaled: set = set()
            for cand_direction, group in by_direction.items():
                winner = max(group, key=lambda c: c["score"])
                if len(group) > 1:
                    logger.info(
                        "%s: %s structurele kandidaten voor richting %s, '%s' wint (risk:reward %.2f)",
                        coin, len(group), cand_direction, winner["kind"], winner["score"],
                    )
                await winner["notify"]()
                structural_directions_signaled.add(cand_direction)

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
            # notify_on_reject=False: een autonoom afgewezen kans ("nog geen
            # sterke kans") hoeft geen Telegram-melding te sturen zoals een
            # door de gebruiker gedeeld bericht dat wel altijd krijgt — dat
            # zou elke cyclus voor tientallen coins een afwijzingsbericht
            # opleveren. De logboekregel en de trackrecord blijven gewoon
            # bestaan, alleen de melding zelf wordt overgeslagen.
            await process_day_trading_signal(None, interp, notify_on_update=False, notify_on_reject=False)
        except Exception:
            # Eén coin die faalt (bijvoorbeeld een tijdelijke Binance-storing)
            # mag de rest van de scan niet blokkeren.
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
