"""Wist alle berichten, signalen, bronniveaus, eigen getekende lijnen en
logboekregels, voor een frisse start. Laat accounts, portfolio-instellingen,
de gevolgde coinlijst en de website-instellingen ongemoeid.

Zet voor de zekerheid crypto-bot en crypto-web stil (sudo systemctl stop
crypto-bot crypto-web): komt er tijdens het wissen een nieuw bericht of
een actie op het dashboard binnen, dan botst die nieuwe rij met de tabel
die net leeggemaakt wordt. Alles gebeurt in één transactie, dus bij zo'n
botsing wordt automatisch alles teruggedraaid, er raakt nooit iets half
verwijderd. Dit script probeert het daarom ook gewoon een paar keer
opnieuw voor hij het opgeeft, voor het geval er nog één bericht
onderweg was op het moment van stoppen.

Onomkeerbaar. Draai met: python3 scripts/fresh_start.py
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def main() -> None:
    db.init_db()

    with db.session() as conn:
        counts = {
            "journal_entries": count(conn, "journal_entries"),
            "signals": count(conn, "signals"),
            "source_levels": count(conn, "source_levels"),
            "trendlines": count(conn, "trendlines"),
            "messages": count(conn, "messages"),
        }

    print("Dit wordt permanent verwijderd:")
    print(f"  {counts['messages']} berichten")
    print(f"  {counts['signals']} signalen")
    print(f"  {counts['journal_entries']} logboekregels (van alle gebruikers samen)")
    print(f"  {counts['source_levels']} bronniveaus")
    print(f"  {counts['trendlines']} zelf getekende lijnen")
    print()
    print("Accounts, portfolio-bedragen, risicopercentages, Telegram chat ID's, "
          "de gevolgde coinlijst en de website-instellingen blijven gewoon staan.")
    print()
    print("Zorg dat crypto-bot en crypto-web stilstaan voor je verder gaat: "
          "sudo systemctl stop crypto-bot crypto-web")
    print()

    if sum(counts.values()) == 0:
        print("Er staat al niets, geen actie nodig.")
        return

    confirm = input("Typ WISSEN om door te gaan: ").strip()
    if confirm != "WISSEN":
        print("Geannuleerd, niets verwijderd.")
        return

    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            with db.session() as conn:
                conn.execute("DELETE FROM journal_entries")
                conn.execute("DELETE FROM signals")
                conn.execute("DELETE FROM source_levels")
                conn.execute("DELETE FROM trendlines")
                conn.execute("DELETE FROM messages")
            break
        except sqlite3.IntegrityError:
            if attempt == attempts:
                print(f"\nOok na {attempts} pogingen komt er steeds een nieuwe rij tussendoor, "
                      "niets is gewist, alles staat nog precies zoals het was.")
                print("Check met 'ps aux | grep python3' of crypto-bot of crypto-web ergens nog "
                      "los draait buiten systemd om, en probeer dit script daarna nog een keer.")
                sys.exit(1)
            print(f"Poging {attempt} botste met een net binnengekomen rij, probeer opnieuw...")
            time.sleep(1.5)

    print("\nGewist. Iedereen begint weer met een leeg dashboard, eigen instellingen blijven staan.")
    print("Vergeet niet de services weer te starten: sudo systemctl start crypto-bot crypto-web")

    keep_images = input("Ook de opgeslagen screenshots verwijderen? (ja/nee) [nee]: ").strip().lower()
    if keep_images == "ja":
        removed = 0
        for path in Path(config.IMAGE_STORAGE_PATH).glob("*"):
            if path.is_file():
                path.unlink()
                removed += 1
        print(f"{removed} screenshot(s) verwijderd uit {config.IMAGE_STORAGE_PATH}.")
    else:
        print("Screenshots op schijf blijven staan (horen niet meer bij een zichtbaar bericht, "
              f"kun je later handmatig opruimen in {config.IMAGE_STORAGE_PATH}).")


if __name__ == "__main__":
    main()
