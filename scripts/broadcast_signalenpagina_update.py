"""Eenmalig broadcast-script: meldt alle gebruikers wat ze nu kunnen
verwachten van de signalenpagina en de achterliggende scan.

Draai dit één keer handmatig op de VPS na het updaten, niet vanuit main.py.

Draai met: python3 scripts/broadcast_signalenpagina_update.py

Stuurt een rustige melding (repo.create_notification) naar ELKE gebruiker,
zichtbaar op /meldingen ongeacht push-status, plus een echte pushmelding
(app.push_notify.send_push) naar wie een geregistreerd apparaat heeft — wie
geen push heeft ziet het bericht alsnog zodra hij inlogt."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import push_notify, repo

TITLE = "Nieuw op Signalen"

BODY = (
    "Een paar dingen zijn net verbeterd. De marktscan draait nu elke 20 "
    "minuten in plaats van elk uur, dus je mist minder kansen. Elk signaal "
    "toont zijn eigen leeftijd en een 'waarom'-uitleg met het percentage "
    "erbij. Interesse niet? Tik op 'niet interessant' om het te verbergen, "
    "je trackrecord blijft gewoon meetellen. Komt de prijs terug in de "
    "betere-entry-zone van een signaal, dan krijg je daar nu een aparte "
    "melding voor. Een swing-kans (bevestigd op een bewaakt niveau, geen "
    "percentage) stond eerder helemaal niet op Signalen ondanks de "
    "pushmelding: dat is gefixt, die staat er nu bij met een SWING-label. "
    "En er was een bug waardoor een ververst signaal steeds 'net binnen' "
    "leek: dat is gefixt, de leeftijd klopt nu."
)

URL = "/signalen"


async def main() -> None:
    users = repo.list_users()
    notified = pushed = 0
    for user in users:
        repo.create_notification(user["id"], "signalenpagina_update", TITLE, BODY, URL)
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
