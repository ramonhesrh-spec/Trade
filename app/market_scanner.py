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

from app import exchange, indicators, repo, telegram_notify
from app.anthropic_interpret import Interpretation
from app.signal_processor import process_day_trading_signal

logger = logging.getLogger("market_scanner")

# Twaalf van de vierentwintig scan-cycli per dag overslaan na een verlies
# op dezelfde coin+richting is een reële afkoelperiode zonder een kans
# dagenlang te blokkeren. Zie de spec, sectie 4.
AUTO_SCAN_LOSS_COOLDOWN_HOURS = 12


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

    # Elke NIEUWE (niet: bijgewerkte) bevestigde autonome kans uit deze
    # cyclus, voor de sterkte-ranking hieronder. was_open_before, vóór de
    # cooldown-check bepaald (zie hieronder), beslist of dit een nieuw of
    # een bestaand signaal wordt.
    new_confirmed_this_cycle: list[dict] = []

    for coin_row in coins:
        coin = coin_row["symbol"]
        if btc_flat and coin != "BTC":
            continue
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"

            # Vóór de cooldown-check bepaald (in plaats van erna): een coin
            # met een al bestaand open signaal moet elke cyclus ververst
            # blijven, ook binnen de cooldown-periode na een verlies (zie
            # find_open_signal-dedup, spec Testen §2). Ook hergebruikt door
            # de confirms_direction-precheck verderop, in plaats van een
            # tweede find_open_signal-aanroep.
            was_open_before = repo.find_open_signal(coin, direction) is not None

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
            await process_day_trading_signal(None, interp, notify_on_update=False)

            if not was_open_before:
                fresh = repo.list_recent_signals(coin, limit=1)
                if fresh and fresh[0]["message_id"] is None and fresh[0]["technical_confirmed"]:
                    new_confirmed_this_cycle.append(
                        {"coin": coin, "direction": direction, "reason": fresh[0]["reason"] or ""}
                    )
        except Exception:
            # Eén coin die faalt (bijvoorbeeld een tijdelijke Binance-storing)
            # mag de rest van de scan niet blokkeren.
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    if len(new_confirmed_this_cycle) >= 2:
        ranked = sorted(
            new_confirmed_this_cycle, key=lambda item: item["reason"].count("✓"), reverse=True,
        )
        for user in repo.list_users():
            if not user["telegram_chat_id"]:
                continue
            try:
                await telegram_notify.send_scan_cycle_summary(ranked, chat_id=user["telegram_chat_id"])
            except Exception:
                logger.exception(
                    "Scan-cyclus-samenvatting voor gebruiker %s is mislukt", user["username"],
                )

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
