"""Startpunt voor de Discord bot, de Telegram /start listener, en de
verwerkingspijplijn.

Draai dit als achtergrondproces op de VPS, bijvoorbeeld via systemd met
Restart=always (zie deploy/crypto-bot.service). Het webdashboard draait
apart, zie web/main.py en deploy/crypto-web.service.
"""
import asyncio
import logging

from app import config, db
from app.discord_bot import DMListenerBot
from app.signal_processor import handle_message
from app.telegram_notify import run_telegram_listener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("main")


async def main() -> None:
    db.init_db()
    if not config.DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN ontbreekt in .env")

    discord_bot = DMListenerBot(on_dm=handle_message)
    tasks = [asyncio.create_task(discord_bot.start(config.DISCORD_BOT_TOKEN))]

    if config.TELEGRAM_BOT_TOKEN:
        tasks.append(asyncio.create_task(run_telegram_listener()))
    else:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen /start listener gestart")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
