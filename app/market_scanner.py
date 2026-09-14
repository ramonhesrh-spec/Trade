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

from app import exchange, indicators, repo
from app.anthropic_interpret import Interpretation
from app.signal_processor import process_day_trading_signal

logger = logging.getLogger("market_scanner")


async def scan_market() -> None:
    if not repo.is_market_scan_enabled():
        logger.info("Marktscan staat uit (noodrem), niets gedaan")
        return

    coins = repo.list_coins()
    logger.info("Marktscan gestart, %s coins in de dynamische lijst", len(coins))

    for coin_row in coins:
        coin = coin_row["symbol"]
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"

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
            # bevestigt (zie find_open_signal-dedup, spec Testen §2).
            confirmed, _ = indicators.confirms_direction(ind, direction)
            if not confirmed and repo.find_open_signal(coin, direction) is None:
                continue

            interp = Interpretation(
                coin=coin, direction=direction, category="day_trading", unclear=False, reason="",
            )
            await process_day_trading_signal(None, interp, notify_on_update=False)
        except Exception:
            # Eén coin die faalt (bijvoorbeeld een tijdelijke Binance-storing)
            # mag de rest van de scan niet blokkeren.
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
