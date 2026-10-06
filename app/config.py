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

# Vaste coinlijst (HesPulse-verkleinen, 2026-09-30): geen onbeperkte
# automatische groei meer zodra een nieuwe coin in Discord voorbijkomt,
# een handjevol coins waarop de marktscan (elke 20 min, alle detectoren)
# daadwerkelijk draait. repo.add_coin_if_new is het enige handhavingspunt
# — een coin hier niet in mag nooit toegevoegd worden, ongeacht wie
# aanroept (Discord-verwerking, bron-niveaus, dagtradinginterpretatie).
BASE_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "SUI"]
# Extra coins (komma-gescheiden in .env, bijvoorbeeld XRP,HBAR): alleen de SMC-check draait erop, niet de 4u-detectoren
# (patroon, uitbraak, trendlijn), want die verliezen op de basiscoins. Eerst met scripts/replay_smc_report.py toetsen.
EXTRA_COINS = [c.strip().upper() for c in _get("EXTRA_COINS", "").split(",") if c.strip() and c.strip().upper() not in BASE_COINS]
FIXED_COINS = BASE_COINS + EXTRA_COINS

# De uitgebreide factoren (ADX, volatiliteit, BTC-trend, 1u bevestiging,
# divergentie, liquiditeit) staan standaard uit. De drempels zijn
# leerboek-standaarden, nog niet getoetst aan de eigen signaalgeschiedenis.
# Draai eerst scripts/backtest_factors.py en zet deze pas aan als dat
# overzicht laat zien dat de drempels niet bijna alles wegfilteren.
ENABLE_ADVANCED_FACTORS = _get("ENABLE_ADVANCED_FACTORS", "false").lower() == "true"

# Minimale stopafstand van een SMC-signaal, in procenten van de entry. Uit het meetraam (12 maanden, 7 coins,
# 122 signalen): signalen met een stop onder 0,1% wonnen 6% en verloren gemiddeld -0,73R bruto, omdat zo'n
# stop binnen de ruis van een minuutcandle ligt. Vanaf 0,2% was het +0,12R bruto. 0 zet de toets uit.
SMC_MIN_STOP_PCT = float(_get("SMC_MIN_STOP_PCT", "0.2"))

# Kosten per rondreis (fee plus slippage, beide kanten samen) in procenten van de entry, voor de netto-cijfers op
# /bewijs en in het weekrapport. Een aanname: wat iemand echt betaalt hangt van de beurs af.
TRACK_RECORD_COST_PCT = float(_get("TRACK_RECORD_COST_PCT", "0.06"))

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


# Soorten die wel gemeten en getoond worden maar geen pushmelding meer geven (komma-gescheiden uit smc, patroon,
# swing, day_trading). Standaard leeg: niets gaat uit tenzij jij het kiest, zie Bewijs voor de cijfers per soort.
SIGNAL_TYPE_INFO_ONLY = {t.strip() for t in _get("SIGNAL_TYPE_INFO_ONLY", "").split(",") if t.strip()}

# Samenval: SMC-signaal en community-call op dezelfde coin en kant binnen dit aantal uren. Ongetest: gaat vanzelf
# uit zodra er SAMENVAL_MAX_NEGATIVE afgeronde samenvallen zijn met een negatieve som in R.
SAMENVAL_ENABLED = _get("SAMENVAL_ENABLED", "true").lower() == "true"
SAMENVAL_WINDOW_HOURS = float(_get("SAMENVAL_WINDOW_HOURS", "6"))
SAMENVAL_MAX_NEGATIVE = int(_get("SAMENVAL_MAX_NEGATIVE", "30"))


# Markt-script (app/market_script.py): elke 4 uur per coin een duiding met twee scenario's. Een scenario dat afgaat geeft
# een melding met het label ongetest. Gaat vanzelf uit als de laatste SCRIPT_MAX_NEGATIVE afgeronde scenario's negatief zijn.
SCRIPT_ENABLED = _get("SCRIPT_ENABLED", "true").lower() == "true"
SCRIPT_MODEL = _get("SCRIPT_MODEL", ANTHROPIC_MODEL)
SCRIPT_MAX_ALERTS_PER_DAY = int(_get("SCRIPT_MAX_ALERTS_PER_DAY", "6"))
SCRIPT_MAX_NEGATIVE = int(_get("SCRIPT_MAX_NEGATIVE", "30"))

# Structuur-setups (app/structure_live.py): breuk van een lijn of range op 30m, een oordeel van Claude en een melding vóórdat
# de limiet gevuld wordt. Altijd met het label ongetest. Gaat vanzelf uit als de laatste STRUCTURE_MAX_NEGATIVE afgeronde
# signalen samen negatief zijn.
STRUCTURE_ENABLED = _get("STRUCTURE_ENABLED", "true").lower() == "true"
STRUCTURE_MODEL = _get("STRUCTURE_MODEL", ANTHROPIC_MODEL)
STRUCTURE_MAX_ALERTS_PER_DAY = int(_get("STRUCTURE_MAX_ALERTS_PER_DAY", "8"))
STRUCTURE_MAX_NEGATIVE = int(_get("STRUCTURE_MAX_NEGATIVE", "30"))

# Trend plus pullback (app/trend_live.py): 4u en 1u trend, impuls op 15m, zone, bevestiging op 5m. Gemeten op een jaar: -0,06R netto, dus altijd ongetest en alleen als stille
# melding. Gaat vanzelf uit na TREND_MAX_NEGATIVE afgeronde signalen die samen negatief zijn.
TREND_ENABLED = _get("TREND_ENABLED", "true").lower() == "true"
TREND_MAX_PER_DAY = int(_get("TREND_MAX_PER_DAY", "6"))
TREND_MAX_NEGATIVE = int(_get("TREND_MAX_NEGATIVE", "40"))
TREND_RR = float(_get("TREND_RR", "2.0"))
