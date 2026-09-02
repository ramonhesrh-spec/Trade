"""Maakt een dashboard account aan, of werkt een bestaand account bij.
Draai met: python3 scripts/create_user.py
Geen open registratie: dit script draai je zelf op de server, voor jezelf
en voor iedereen die je toegang wil geven, bijvoorbeeld een vriend die zijn
eigen logboek wil bijhouden op dezelfde signalen.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, repo
from app.security import hash_password


def ask_float(prompt: str, default: float) -> float:
    raw = input(f"{prompt} [{default}]: ").strip()
    return float(raw) if raw else default


def main() -> None:
    db.init_db()

    username = input("Gebruikersnaam: ").strip()
    if not username:
        print("Gebruikersnaam mag niet leeg zijn.")
        sys.exit(1)

    password = getpass.getpass("Wachtwoord: ")
    confirm = getpass.getpass("Herhaal het wachtwoord: ")
    if password != confirm:
        print("Wachtwoorden komen niet overeen.")
        sys.exit(1)

    portfolio_eur = ask_float("Portfolio omvang in euro's", 0.0)
    risk_percent = ask_float("Risico per trade in procenten", config.DEFAULT_RISK_PERCENT)
    telegram_chat_id = input("Telegram chat ID (leeg = geen Telegram meldingen): ").strip() or None

    user_id = repo.create_user(
        username=username,
        password_hash=hash_password(password),
        portfolio_eur=portfolio_eur,
        risk_percent=risk_percent,
        telegram_chat_id=telegram_chat_id,
    )

    print(f"\nAccount klaar: {username} (id {user_id})")
    print("Deze gebruiker kan nu inloggen op het dashboard met dit wachtwoord.")
    if not telegram_chat_id:
        print("Geen Telegram chat ID ingevuld, deze gebruiker krijgt geen Telegram meldingen "
              "totdat dit alsnog wordt ingevuld (in het dashboard, onder Portfolio).")


if __name__ == "__main__":
    main()
