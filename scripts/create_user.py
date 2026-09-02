"""Genereert een bcrypt hash voor het dashboard wachtwoord.
Draai met: python3 scripts/create_user.py
Zet de output in .env als DASHBOARD_PASSWORD_HASH.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import hash_password


def main() -> None:
    password = getpass.getpass("Kies een wachtwoord voor het dashboard: ")
    confirm = getpass.getpass("Herhaal het wachtwoord: ")
    if password != confirm:
        print("Wachtwoorden komen niet overeen.")
        sys.exit(1)

    print("\nZet deze regel in je .env bestand:\n")
    print(f"DASHBOARD_PASSWORD_HASH={hash_password(password)}")


if __name__ == "__main__":
    main()
