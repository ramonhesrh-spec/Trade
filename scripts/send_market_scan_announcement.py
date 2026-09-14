"""Eenmalig broadcast-script: meldt alle gebruikers met een gekoppelde
Telegram over de nieuwe autonome marktscan. Draai dit één keer handmatig op
de VPS, niet vanuit main.py."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot

from app import config, repo

TEXT = (
    "🔎 Nieuw: HesPulse zoekt nu ook zelf naar kansen\n"
    f"{'━' * 14}\n\n"
    "Tot nu toe keek HesPulse alleen naar een bericht dat jij zelf "
    "doorstuurde. Vanaf nu scant hij daarnaast elk uur zelf elke coin uit "
    "je coinlijst, zonder dat er eerst een bericht nodig is.\n\n"
    "Richting komt uit de trend (EMA9 tegenover EMA21). Daarna doorloopt "
    "een kans precies dezelfde toets als een gedeeld signaal: dezelfde "
    "technische factoren, dezelfde stop loss en take profit, jouw eigen "
    "positiegrootte. Bevestigt een coin, dan krijg je een gewone melding "
    "met erboven het label 'Zelf gedetecteerd door HesPulse', zodat je "
    "altijd ziet waar een kans vandaan komt.\n\n"
    "Een paar ingebouwde remmen: geen kans binnen 12 uur na een eigen "
    "verlies op diezelfde coin en richting, geen altcoin-kansen zolang "
    "BTC zelf zijwaarts beweegt, en op het dashboard staat een noodrem "
    "die de hele scan in één klik uitzet.\n\n"
    "Geen actie nodig. Dit draait automatisch mee naast je bestaande "
    "signalen."
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
