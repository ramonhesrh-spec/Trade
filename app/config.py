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

# Voor het herschrijven van al berekende feiten in gewone taal (explain.py:
# explain_signal, summarize_message) is het zwaardere ANTHROPIC_MODEL niet
# nodig, dat verzint toch niets nieuws, het herformuleert alleen. Dit pad
# wordt elk uur per gevolgde coin aangeroepen door de marktscan, ook bij
# een afwijzing die nooit gepusht wordt, dus de kosten lopen hier het
# snelst op.
ANTHROPIC_EXPLAIN_MODEL = _get("ANTHROPIC_EXPLAIN_MODEL", "claude-haiku-4-5-20251001")

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

# Vaste toelichting, onderaan het dashboard.
DISCLAIMER = "Geen advies. Regels, geen garantie. Jij beslist zelf."

# Openbaar adres van het dashboard, voor toekomstige links vanuit een
# melding of e-mail.
DASHBOARD_URL = _get("DASHBOARD_URL", "https://hespulse.duckdns.org")

# Web Push: eigen VAPID-sleutelpaar, één keer gegenereerd (zie het plan
# voor het genereercommando), bewijst aan Apple/Google dat een melding
# echt van HesPulse komt. VAPID_CLAIM_EMAIL is het contactadres dat de
# pushdienst mag gebruiken bij misbruik-signalen, vereist door de Web
# Push-standaard (RFC 8292).
VAPID_PUBLIC_KEY = _get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = _get("VAPID_PRIVATE_KEY")
VAPID_CLAIM_EMAIL = _get("VAPID_CLAIM_EMAIL", "mailto:admin@hespulse.duckdns.org")

# Gebruikersnaam van het admin-account (jijzelf): bepaalt wie de
# systeemgezondheid-sectie op /meldingen mag zien. Vervangt de oude
# ADMIN_TELEGRAM_CHAT_ID-vergelijking, nu Telegram helemaal weg is (Taak 11).
ADMIN_USERNAME = _get("ADMIN_USERNAME")

# Kraken Pro referral, getoond op de openbare landingspagina.
KRAKEN_REFERRAL_URL = "https://proinvite.kraken.com/9f1e/4zto3wcm"
KRAKEN_REFERRAL_CODE = "dc992yg8"
