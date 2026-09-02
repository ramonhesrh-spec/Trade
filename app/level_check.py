"""Periodieke check of een open trade zijn stop loss of take profit al
geraakt heeft, terwijl die nog niet gesloten is in het logboek. Zonder dit
moet je zelf onthouden een trade te sluiten zodra een niveau geraakt is.

Stuurt één seintje per open logboekregel, geen herhaalde meldingen. Sluit
niets automatisch, dat blijft een handmatige stap in het dashboard. Wordt
aangeroepen via een systemd timer, zie deploy/crypto-level-check.service
en .timer.
"""
import asyncio
import logging

from telegram import Bot

from app import config, exchange, repo

logger = logging.getLogger("level_check")


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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(check_open_trades())
