"""Eenmalig broadcast-script: excuus + uitleg voor de opeenstapeling van
pushmeldingen, en wat er nu is aangepast (geen melding meer bij laag
vertrouwen of een patroon onder de kansdrempel). Draai dit één keer
handmatig op de VPS na het updaten, niet vanuit main.py.

Draai met: python3 scripts/broadcast_minder_meldingen_update.py

Stuurt een rustige melding (repo.create_notification) naar ELKE gebruiker,
zichtbaar op /meldingen ongeacht push-status, plus een echte pushmelding
(app.push_notify.send_push) naar wie een geregistreerd apparaat heeft — wie
geen push heeft ziet het bericht alsnog zodra hij inlogt."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import push_notify, repo

TITLE = "Sorry voor alle meldingen, dat is nu aangepast"

BODY = (
    "De laatste tijd kreeg je te veel pushmeldingen, ook bij zwakke kansen. "
    "Dat is niet de bedoeling en is nu aangepast. Voortaan krijg je alleen nog "
    "een pushmelding bij een écht bevestigd signaal, of bij een duidelijke "
    "uitbraak + terugtest of trendlijn + terugtest. Een afgewezen signaal, of "
    "een patroon met een lage kansberekening, verschijnt nog gewoon in je "
    "journaal en op het dashboard voor je trackrecord, maar stuurt geen "
    "melding meer naar je telefoon. Merk je alsnog te veel of verkeerde "
    "meldingen, laat het weten."
)

URL = "/signalen"


async def main() -> None:
    users = repo.list_users()
    notified = pushed = 0
    for user in users:
        repo.create_notification(user["id"], "minder_meldingen_update", TITLE, BODY, URL)
        notified += 1
        try:
            await push_notify.send_push(user["id"], TITLE, BODY, URL, silent=False)
            if repo.list_push_subscriptions(user["id"]):
                pushed += 1
                print(f"pushmelding + /meldingen-rij verstuurd naar {user['username']}")
            else:
                print(f"alleen /meldingen-rij (geen push-abonnement) voor {user['username']}")
        except Exception as exc:
            print(f"MISLUKT (push) voor {user['username']}: {exc}")
    print(f"\nKlaar: {notified} gebruikers kregen een /meldingen-rij, {pushed} daarvan ook een pushmelding.")


if __name__ == "__main__":
    asyncio.run(main())
