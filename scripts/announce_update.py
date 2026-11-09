"""Stuurt alle gebruikers één keer een "Wat is nieuw"-melding: een regel op /meldingen en een pushmelding.
Veilig om twee keer te draaien: wie dezelfde titel al heeft gekregen, wordt overgeslagen.
Draai: python3 scripts/announce_update.py [--dry-run] [--no-push]"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, push_notify, repo  # noqa: E402

TITLE = "Nieuw in HesPulse: Vandaag, markt-script, Radar en Bewijs"
BODY = (
    "Vandaag: jouw nieuwe startpagina met het markt-script per coin, de agenda van de komende 24 uur, gedwongen sluitingen en nieuws.\n"
    "Markt-script (ongetest): Claude schrijft elke 4 uur scenario's met een voorwaarde. Klopt die, dan krijg je een melding met limietorder, stop en take.\n"
    "Radar: elke SMC-kans als handelsplan met een live prijsladder en een melding zodra de koers in de zone komt.\n"
    "Bewijs: wat elk soort melding echt opleverde in R na kosten, ook de soorten die nog niets bewezen hebben."
)
URL = "/vandaag"


def already_sent(user_id: int) -> bool:
    return any(n["title"] == TITLE for n in repo.list_notifications(user_id, limit=200))


async def main(dry_run: bool, push: bool) -> None:
    db.init_db()
    sent = 0
    for user in repo.list_users():
        if already_sent(user["id"]):
            print(f"{user['username']}: al gehad, overgeslagen")
            continue
        print(f"{user['username']}: {'zou krijgen' if dry_run else 'melding aangemaakt'}")
        if dry_run:
            continue
        repo.create_notification(user["id"], "update", TITLE, BODY, URL)
        sent += 1
        if push:
            try:
                await push_notify.send_push(user["id"], TITLE, BODY.split("\n")[0], URL)
            except Exception as exc:
                print(f"  push mislukt: {exc}")
    print(f"Klaar: {sent} gebruiker(s) gemeld")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-push", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.dry_run, not a.no_push))
