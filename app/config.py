"""Centrale configuratie, geladen uit .env. Geen geheimen in code."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


DISCORD_BOT_TOKEN = _get("DISCORD_BOT_TOKEN")

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-5")

# Eén gedeelde Telegram bot, stuurt elke gebruiker zijn eigen bericht naar
# zijn eigen chat ID (opgeslagen per gebruiker in de database).
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")

EXCHANGE_ID = _get("EXCHANGE_ID", "binance")
QUOTE_CURRENCY = _get("QUOTE_CURRENCY", "USDT")
TIMEFRAME = "4h"

# Dashboard accounts staan in de database (tabel users), aangemaakt via
# scripts/create_user.py. Geen open registratie.
JWT_SECRET = _get("JWT_SECRET", "change-me-to-a-random-secret")
JWT_ALGORITHM = "HS256"
SESSION_HOURS = 24 * 7

# Standaard risicopercentage voor een nieuwe gebruiker, aan te passen per
# gebruiker in het dashboard.
DEFAULT_RISK_PERCENT = float(_get("DEFAULT_RISK_PERCENT", "1.0"))

DATABASE_PATH = str(BASE_DIR / _get("DATABASE_PATH", "data/trading.db"))
IMAGE_STORAGE_PATH = str(BASE_DIR / _get("IMAGE_STORAGE_PATH", "data/images"))
BACKUP_PATH = str(BASE_DIR / _get("BACKUP_PATH", "data/backups"))
# Externe locatie voor de dagelijkse back-up, via rsync over SSH,
# bijvoorbeeld user@andere-server:/pad/naar/backups/. Leeg = geen externe
# kopie, alleen lokaal op de VPS.
BACKUP_REMOTE = _get("BACKUP_REMOTE")

MAX_LOGIN_ATTEMPTS = int(_get("MAX_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(_get("LOGIN_LOCKOUT_MINUTES", "15"))

# Vaste toelichting, op elk Telegram bericht en onderaan het dashboard.
DISCLAIMER = "Geen advies. Regels, geen garantie. Jij beslist zelf."
