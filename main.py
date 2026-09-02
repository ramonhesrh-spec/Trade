"""Startpunt voor de Discord bot en de verwerkingspijplijn.

Draai dit als achtergrondproces op de VPS, bijvoorbeeld via systemd met
Restart=always (zie deploy/crypto-bot.service). Het webdashboard draait
apart, zie web/main.py en deploy/crypto-web.service.
"""
import logging

from app import db
from app.discord_bot import run_bot
from app.signal_processor import handle_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    db.init_db()
    run_bot(on_dm=handle_message)
