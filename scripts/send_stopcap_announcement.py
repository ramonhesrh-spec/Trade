"""Eenmalig broadcast-script: meldt alle gebruikers met een gekoppelde
Telegram over de evaluatie-sizing/stop-cap update en hoe meldingen nu
werken. Draai dit één keer handmatig op de VPS, niet vanuit main.py."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot

from app import config, repo

TEXT = (
    "📢 Update: sizing en stop loss bij een evaluatie\n"
    f"{'━' * 14}\n\n"
    "Heb je een evaluatie lopen? Dan rekent HesPulse voortaan anders.\n\n"
    "Positiegrootte wordt nu bepaald door je evaluatie, niet door je eigen "
    "portfolio. Fees en hefboomkosten tellen mee in de berekening. Je "
    "dagbudget en je drawdown ruimte worden bewaakt, een trade die daar te "
    "veel van opeet wordt automatisch geblokkeerd voor je evaluatie.\n\n"
    "De stop loss zelf wordt krapper naarmate je evaluatie kleiner is. Bij "
    "10.000 euro of meer verandert er niets. Bij een kleinere evaluatie "
    "krimpt de maximale afstand tot 1 procent van de prijs. Take profit "
    "schaalt mee, je risico beloning verhouding blijft gelijk. Dit raakt "
    "nooit het gedeelde signaal, alleen jouw eigen kopie in je logboek.\n\n"
    "Zo werkt een melding nu. Je krijgt per coin een bericht met de prijs, "
    "stop loss, take profit en je eigen positiegrootte. Onder een "
    "bevestigde kans staan Genomen en Negeren knoppen. Is je stop verkrapt "
    "vanwege je evaluatie, dan zie je dat er apart bij staan. Wordt een "
    "openstaand signaal bijgewerkt door een nieuw bericht, dan krijg je nu "
    "ook daar je eigen, actuele cijfers te zien in plaats van het gedeelde "
    "signaal.\n\n"
    "Geen actie nodig. Dit werkt automatisch mee met je bestaande evaluatie."
)


async def main() -> None:
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    users = repo.list_users()
    sent = skipped = 0
    for user in users:
        chat_id = user.get("telegram_chat_id")
        if not chat_id:
            skipped += 1
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=TEXT, disable_notification=False)
            sent += 1
            print(f"verstuurd naar {user['username']} ({chat_id})")
        except Exception as exc:
            print(f"MISLUKT voor {user['username']} ({chat_id}): {exc}")
    print(f"\nKlaar: {sent} verstuurd, {skipped} overgeslagen (geen Telegram gekoppeld)")


if __name__ == "__main__":
    asyncio.run(main())
