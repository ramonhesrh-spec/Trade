"""Eenmalig broadcast-script: meldt alle gebruikers over de puur-signalen-
herziening (nieuwe /signalen- en /account-pagina's, automatisch trackrecord).
Draai dit één keer handmatig op de VPS na het updaten, niet vanuit main.py.

Draai met: python3 scripts/broadcast_puur_signalen_update.py

Stuurt een rustige melding (repo.create_notification) naar ELKE gebruiker,
zichtbaar op /meldingen ongeacht push-status, plus een echte pushmelding
(app.push_notify.send_push) naar wie een geregistreerd apparaat heeft — wie
geen push heeft ziet het bericht alsnog zodra hij inlogt."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import push_notify, repo

TITLE = "HesPulse is opgeschoond: puur signalen"

BODY = (
    "Grote update: de site draait nu puur om signalen. Na inloggen zie je "
    "meteen de Signalen-pagina, hoogste percentage bovenaan, geen journaal "
    "of instellingen meer ertussen. Journaal, winrate en je bevestigings-"
    "drempel staan voortaan op Mijn account. Je winrate wordt nu volledig "
    "automatisch bijgehouden op de live koers, geen Genomen/Negeren meer "
    "nodig. Kijk gerust rond, alles werkt zoals je gewend bent, alleen "
    "overzichtelijker."
)

URL = "/signalen"


async def main() -> None:
    users = repo.list_users()
    notified = pushed = 0
    for user in users:
        repo.create_notification(user["id"], "puur_signalen_update", TITLE, BODY, URL)
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
