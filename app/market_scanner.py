"""Autonome marktscan: HesPulse ontdekt zelf een day-trading-kans, zonder
dat een gebruiker eerst een Discord-bericht doorstuurt. Draait elk uur via
een systemd-timer (zie deploy/crypto-market-scan.service en .timer), niet
elke 4 uur zoals de underlying candle-timeframe: de laatste 4u-candle is
bij Binance nog "in wording" totdat hij sluit, dus tussentijds checken
vangt een beweging eerder op. Zelfde soort redenering als level_check.py,
die ook vaker draait dan de candle zelf.

Voor elke coin in de bestaande dynamische lijst (repo.list_coins()) wordt
zelf een richting bepaald via de trend (EMA9 t.o.v. EMA21) en hergebruikt
process_day_trading_signal() de bestaande toetsings- en fan-out-logica —
geen tweede implementatie ernaast. Zie
docs/superpowers/specs/2026-09-14-autonome-marktscan-design.md.
"""
import asyncio
import logging
from typing import Optional

from app import exchange, indicators, push_notify, repo, risk
from app.anthropic_interpret import Interpretation
from app.signal_processor import process_day_trading_signal

logger = logging.getLogger("market_scanner")

# Twaalf van de vierentwintig scan-cycli per dag overslaan na een verlies
# op dezelfde coin+richting is een reële afkoelperiode zonder een kans
# dagenlang te blokkeren. Zie de spec, sectie 4.
AUTO_SCAN_LOSS_COOLDOWN_HOURS = 12

# Whiplash-rem: een NIEUWE richting moet dit aantal scan-cycli achter
# elkaar aanhouden voor er gemeld wordt. Voorkomt dat een EMA9/EMA21-
# kruising die binnen een uur alweer terugklapt eerst een long en dan een
# short melding oplevert voor dezelfde coin.
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


async def _check_breakout_retest(coin: str, direction: str, df, ind) -> None:
    """Los van de trend-confirmatie hieronder: een uitbraak-dan-terugtest
    is een eigen, sterk entry-patroon (een zone die eerder steun/weerstand
    was, doorbroken is, en nu opnieuw getest wordt) en verdient een eigen
    melding, ongeacht of confirms_direction deze cyclus ja of nee zegt.
    Dedupliceert op coin+richting+zone via coins.last_breakout_retest_key,
    met een ATR-marge (_same_breakout_retest_zone): een zone die dicht
    genoeg bij de vorig gemelde zone ligt telt als dezelfde, een echt
    nieuwe uitbraak (andere zone, of de andere richting) stuurt opnieuw."""
    zones = indicators.detect_sr_zones(df)
    hits = indicators.find_breakout_retest(df, zones, ind.atr, direction)
    if not hits:
        return
    zone, candles_since = max(hits, key=lambda h: h[0].touches)
    key = f"{direction}:{zone.price_low:.8f}:{zone.price_high:.8f}"
    if _same_breakout_retest_zone(repo.get_breakout_retest_key(coin), direction, zone, ind.atr):
        return  # binnen de dedup-marge van de vorige melding, geen herhaling

    stop_take = risk.compute_stop_take(
        direction, ind.price, ind.atr,
        swing_low=zone.price_low if direction == "long" else None,
        swing_high=zone.price_high if direction == "short" else None,
    )
    # Geen telegram_chat_id-gate meer (Taak 11): push_notify.send_push slaat
    # een gebruiker zonder push-abonnement zelf al stilzwijgend over, en
    # telegram_chat_id wordt sinds de overstap naar push nooit meer
    # ingevuld voor nieuwe gebruikers.
    for user in repo.list_users():
        if repo.is_coin_muted(user["id"], coin):
            continue
        force_silent = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, zelf gedetecteerd"
            body = f"Entry {ind.price:.4f} · Stop {stop_take.stop_loss:.4f} · Take profit {stop_take.take_profit:.4f}"
            await push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=force_silent)
        except Exception:
            logger.exception(
                "Pushmelding (uitbraak-terugtest) voor %s naar gebruiker %s is mislukt", coin, user["username"],
            )
    repo.set_breakout_retest_key(coin, key)


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


async def _check_trendline_retest(coin: str, direction: str, df, ind) -> None:
    """Los van _check_breakout_retest: een diagonale trendlijn (steun of
    weerstand) is een ander patroon dan een horizontale zone, met een
    eigen melding. Zelfde striktheid (crossing op closing-prijs, moet
    standhouden) en zelfde ATR-dedup-marge als de optie-C-fix van
    vandaag, zie docs/superpowers/specs/2026-09-15-trendlijn-uitbraak-design.md."""
    trendlines = indicators.detect_trendlines(df, ind.atr)
    hits = indicators.find_trendline_breakout_retest(df, trendlines, ind.atr, direction)
    if not hits:
        return
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
        return

    stop_take = risk.compute_stop_take(
        direction, ind.price, ind.atr,
        swing_low=current_value if direction == "long" else None,
        swing_high=current_value if direction == "short" else None,
    )
    # Geen telegram_chat_id-gate meer (Taak 11): push_notify.send_push slaat
    # een gebruiker zonder push-abonnement zelf al stilzwijgend over, en
    # telegram_chat_id wordt sinds de overstap naar push nooit meer
    # ingevuld voor nieuwe gebruikers.
    for user in repo.list_users():
        if repo.is_coin_muted(user["id"], coin):
            continue
        force_silent = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, zelf gedetecteerd"
            body = f"Entry {ind.price:.4f} · Stop {stop_take.stop_loss:.4f} · Take profit {stop_take.take_profit:.4f}"
            await push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=force_silent)
        except Exception:
            logger.exception(
                "Pushmelding (trendlijn-terugtest) voor %s naar gebruiker %s is mislukt", coin, user["username"],
            )
    repo.set_trendline_retest_key(coin, key)


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

            await _check_breakout_retest(coin, direction, df, ind)
            await _check_trendline_retest(coin, direction, df, ind)

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
            # afgewezen rij in `signals` achterlaat (elk uur, voor
            # tientallen coins, zou dat de tabel vervuilen zonder dat er
            # ooit een kans was). process_day_trading_signal doet hierna
            # nog steeds zijn eigen volledige toetsing (incl. eventuele
            # advanced factors) en blijft de enige bron van waarheid voor
            # technical_confirmed. Een coin met een al bestaand open
            # signaal slaat deze check over en gaat altijd door: die moet
            # elke cyclus ververst blijven, ook als hij nu niet meer
            # bevestigt.
            confirmed, _ = indicators.confirms_direction(ind, direction)
            if not confirmed and not was_open_before:
                continue

            interp = Interpretation(
                coin=coin, direction=direction, category="day_trading", unclear=False, reason="",
            )
            # notify_on_reject=False: een autonoom afgewezen kans ("nog geen
            # sterke kans") hoeft geen Telegram-melding te sturen zoals een
            # door de gebruiker gedeeld bericht dat wel altijd krijgt — dat
            # zou elk uur voor tientallen coins een afwijzingsbericht
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
