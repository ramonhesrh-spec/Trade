"""Wist alle berichten, signalen, bronniveaus, eigen getekende lijnen en
logboekregels, voor een frisse start. Laat accounts, portfolio-instellingen,
de gevolgde coinlijst en de website-instellingen ongemoeid.

Onomkeerbaar. Draai met: python3 scripts/fresh_start.py
"""
import sys
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

    if sum(counts.values()) == 0:
        print("Er staat al niets, geen actie nodig.")
        return

    confirm = input("Typ WISSEN om door te gaan: ").strip()
    if confirm != "WISSEN":
        print("Geannuleerd, niets verwijderd.")
        return

    with db.session() as conn:
        conn.execute("DELETE FROM journal_entries")
        conn.execute("DELETE FROM signals")
        conn.execute("DELETE FROM source_levels")
        conn.execute("DELETE FROM trendlines")
        conn.execute("DELETE FROM messages")

    print("\nGewist. Iedereen begint weer met een leeg dashboard, eigen instellingen blijven staan.")

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
