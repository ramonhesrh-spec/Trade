"""Eenmalig broadcast-script: meldt alle gebruikers met een gekoppelde
Telegram dat het systeem is bijgewerkt met automatische steun/weerstand-
zone-detectie. Draai dit één keer handmatig op de VPS, niet vanuit main.py."""
import asyncio

from telegram import Bot

from app import config, repo

TEXT = (
    "🆕 HesPulse is bijgewerkt\n"
    f"{'━' * 14}\n\n"
    "HesPulse herkent nu zelf uit de prijsgeschiedenis waar de markt eerder "
    "al gekeerd is (steun/weerstand-zones). Dat gebeurt bovenop de bestaande "
    "technische toetsing:\n\n"
    "• Nieuwe factor \"Steun/weerstand\" in elke melding (11 van de 15 "
    "geavanceerde factoren)\n"
    "• Stop loss en take profit worden verscherpt als er een zone dichtbij "
    "ligt\n"
    "• De zones zijn zichtbaar op de coin-grafiek als paarse blokken\n\n"
    "Verder niets veranderd aan hoe je meldingen krijgt of hoe je handelt."
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
