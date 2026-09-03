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

# De uitgebreide factoren (ADX, volatiliteit, BTC-trend, 1u bevestiging,
# divergentie, liquiditeit) staan standaard uit. De drempels zijn
# leerboek-standaarden, nog niet getoetst aan de eigen signaalgeschiedenis.
# Draai eerst scripts/backtest_factors.py en zet deze pas aan als dat
# overzicht laat zien dat de drempels niet bijna alles wegfilteren.
ENABLE_ADVANCED_FACTORS = _get("ENABLE_ADVANCED_FACTORS", "false").lower() == "true"

# Dashboard accounts staan in de database (tabel users). Open registratie
# staat aan op /registreer, daarnaast kan een account ook via
# scripts/create_user.py worden aangemaakt of bijgewerkt.
JWT_SECRET = _get("JWT_SECRET", "change-me-to-a-random-secret")
JWT_ALGORITHM = "HS256"
SESSION_HOURS = 24 * 7

# Maximum aantal registraties per IP per uur, tegen geautomatiseerde spam.
MAX_REGISTRATIONS_PER_HOUR = int(_get("MAX_REGISTRATIONS_PER_HOUR", "5"))

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

# Voor het welkomstbericht dat de Discord bot terugstuurt bij iemands eerste
# DM, en voor toekomstige links naar het dashboard vanuit een bot-bericht.
DASHBOARD_URL = _get("DASHBOARD_URL", "https://hespulse.duckdns.org")

# Kraken Pro referral, getoond op de openbare landingspagina.
KRAKEN_REFERRAL_URL = "https://proinvite.kraken.com/9f1e/4zto3wcm"
KRAKEN_REFERRAL_CODE = "dc992yg8"
