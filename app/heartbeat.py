"""Dagelijks levensteken: stuurt elke gebruiker met een Telegram chat ID een
kort bericht dat het systeem nog draait. Zonder dit merk je een crash pas
op als er een tijd lang geen meldingen meer binnenkomen. Wordt aangeroepen
via een systemd timer, zie deploy/crypto-heartbeat.service en .timer.
"""
import asyncio
import logging

from telegram import Bot

from app import config, db, repo

logger = logging.getLogger("heartbeat")


async def send_heartbeats() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen levenstekens verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    timestamp = db.now_iso()[:16].replace("T", " ")
    text = f"Goedemorgen trader. Nieuwe dag, nieuwe kansen. HesPulse draait, laatste controle: {timestamp}."

    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        try:
            await bot.send_message(chat_id=user["telegram_chat_id"], text=text)
            logger.info("Levensteken verstuurd naar %s", user["username"])
        except Exception:
            logger.exception("Levensteken naar %s is mislukt", user["username"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(send_heartbeats())
