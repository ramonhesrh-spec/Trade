"""Periodieke check, in twee delen:

1. Heeft een open trade (eigen entry al ingevuld) zijn stop loss of take
   profit al geraakt, terwijl die nog niet gesloten is in het logboek.
2. Is de prijs weer dicht bij het niveau van een nog niet genomen signaal
   gekomen, zodat een gebruiker die een melding zag maar nog niet instapte
   een seintje krijgt als het weer interessant wordt, in plaats van dat
   alleen een nieuw binnenkomend Discord bericht tot een melding leidt.

Zonder dit moet je zelf continu de koers in de gaten houden. Stuurt één
seintje per logboekregel, geen herhaalde meldingen. Sluit of opent niets
automatisch, dat blijft een handmatige stap in het dashboard. Wordt
aangeroepen via een systemd timer, zie deploy/crypto-level-check.service
en .timer.
"""
import asyncio
import logging

from telegram import Bot

from app import config, exchange, repo

logger = logging.getLogger("level_check")

# Hoe dicht de prijs bij het oorspronkelijke signaalniveau moet komen voordat
# een nog niet genomen signaal een "weer interessant" seintje krijgt. In ATR,
# dezelfde maatstaf als de stop-afstand, zodat het meebeweegt met hoe
# volatiel de coin is in plaats van een vast percentage voor elke coin.
PENDING_LEVEL_ATR_MULTIPLIER = 0.5


def _level_hit(direction: str, current_price: float, stop_loss: float, take_profit: float) -> str:
    """Geeft "stop loss", "take profit" of "" terug."""
    if direction == "long":
        if stop_loss is not None and current_price <= stop_loss:
            return "stop loss"
        if take_profit is not None and current_price >= take_profit:
            return "take profit"
    else:
        if stop_loss is not None and current_price >= stop_loss:
            return "stop loss"
        if take_profit is not None and current_price <= take_profit:
            return "take profit"
    return ""


async def check_open_trades() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen seintjes verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    entries = repo.list_open_entries_with_levels()
    logger.info("%d open logboekregels om te checken", len(entries))

    coin_prices: dict[str, float] = {}

    for entry in entries:
        coin = entry["coin"]
        if coin not in coin_prices:
            try:
                coin_prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
            except Exception:
                logger.exception("Kon geen live prijs ophalen voor %s, sla over", coin)
                coin_prices[coin] = None
        current_price = coin_prices[coin]
        if current_price is None:
            continue

        hit = _level_hit(entry["direction"], current_price, entry["stop_loss"], entry["take_profit"])
        if not hit:
            continue

        if not entry["telegram_chat_id"]:
            repo.mark_level_alert_sent(entry["id"])
            continue

        text = (
            f"Je open {coin} {entry['direction'].upper()} trade heeft de {hit} geraakt.\n"
            f"Entry: {entry['entry_price']:.4f}\n"
            f"Huidige prijs: {current_price:.4f}\n\n"
            f"Sluit je hem, vul de exit in op het dashboard. {config.DISCLAIMER}"
        )
        try:
            await bot.send_message(chat_id=entry["telegram_chat_id"], text=text)
            logger.info("Seintje verstuurd naar %s voor %s (%s)", entry["username"], coin, hit)
        except Exception:
            logger.exception("Seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])


async def check_pending_signals() -> None:
    """Signalen die nog niet genomen zijn: als de prijs weer terugkomt naar
    het niveau waarop het signaal binnenkwam, is dat voor day trading vaak
    het beste instapmoment, niet het moment van de eerste melding zelf. Dit
    is de proactieve kant, naast de reactieve verwerking van een nieuw
    Discord bericht."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen seintjes verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    entries = repo.list_pending_entries_with_price()
    logger.info("%d nog niet genomen signalen om te checken", len(entries))

    coin_prices: dict[str, float] = {}

    for entry in entries:
        coin = entry["coin"]
        if not entry["signal_price"] or not entry["atr"]:
            continue
        if coin not in coin_prices:
            try:
                coin_prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
            except Exception:
                logger.exception("Kon geen live prijs ophalen voor %s, sla over", coin)
                coin_prices[coin] = None
        current_price = coin_prices[coin]
        if current_price is None:
            continue

        distance = abs(current_price - entry["signal_price"])
        if distance > entry["atr"] * PENDING_LEVEL_ATR_MULTIPLIER:
            continue

        if not entry["telegram_chat_id"]:
            repo.mark_level_alert_sent(entry["id"])
            continue

        text = (
            f"{coin} {entry['direction'].upper()} ({entry['confidence']}) is terug bij het niveau "
            f"van het eerdere signaal.\n"
            f"Signaalniveau: {entry['signal_price']:.4f}\n"
            f"Huidige prijs: {current_price:.4f}\n\n"
            f"Nog steeds interessant? Check het dashboard voor de actuele toetsing. {config.DISCLAIMER}"
        )
        try:
            await bot.send_message(chat_id=entry["telegram_chat_id"], text=text)
            logger.info("Niveau-seintje verstuurd naar %s voor %s", entry["username"], coin)
        except Exception:
            logger.exception("Niveau-seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])


async def run_all_checks() -> None:
    await check_open_trades()
    await check_pending_signals()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_all_checks())
