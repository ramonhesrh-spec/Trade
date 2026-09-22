"""Eenmalig broadcast-script: meldt alle gebruikers over de kritischere
signaaltoetsing (R:R-ondergrens, dagtrend-eis, zone-cooldown, entry-suggestie).
Draai dit één keer handmatig op de VPS na het updaten, niet vanuit main.py.

Draai met: python3 scripts/broadcast_kritischere_toetsing_update.py

Stuurt een rustige melding (repo.create_notification) naar ELKE gebruiker,
zichtbaar op /meldingen ongeacht push-status, plus een echte pushmelding
(app.push_notify.send_push) naar wie een geregistreerd apparaat heeft — wie
geen push heeft ziet het bericht alsnog zodra hij inlogt."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import push_notify, repo

TITLE = "HesPulse toetst signalen nu strenger"

BODY = (
    "De toetsing zelf is kritischer geworden, niet de site eromheen. Vier "
    "wijzigingen: een signaal met minder dan 1.5 tegen 1 risico/rendement "
    "wordt afgewezen. De dagtrend van de coin zelf telt nu altijd mee als "
    "harde eis, met een uitzondering voor een vlakke markt. Een steun- of "
    "weerstandszone die de laatste 3 dagen al een stop loss veroorzaakte "
    "blokkeert een nieuw signaal op diezelfde zone. En je ziet nu soms een "
    "'mogelijk betere entry' bij een signaal, puur als suggestie naast de "
    "live prijs, telt nergens mee in je positiegrootte of trackrecord. "
    "Verwacht iets minder signalen, maar wel scherpere."
)

URL = "/signalen"


async def main() -> None:
    users = repo.list_users()
    notified = pushed = 0
    for user in users:
        repo.create_notification(user["id"], "kritischere_toetsing_update", TITLE, BODY, URL)
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
