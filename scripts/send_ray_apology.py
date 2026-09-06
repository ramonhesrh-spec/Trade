"""Eenmalig bericht naar elke gebruiker met een gekoppelde Telegram chat:
uitleg en excuus over de gemiste RAY-kans (weekly double bottom, 05-09-2026,
bericht #47), en wat er gebouwd wordt om dit soort gemiste kansen te
voorkomen. Geen disable_notification: dit bericht mag gewoon geluid maken.

Draai met: python3 scripts/send_ray_apology.py
Vraagt eerst een bevestiging voor er echt iets verstuurd wordt.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot

from app import config, db, repo

MESSAGE = """Update HesPulse: gemiste kans op RAY

Gisteren kwam er een tip binnen over RAY: een weekly double bottom setup met een concrete weerstand. RAY steeg daarna meer dan 20%. HesPulse gaf geen instapmelding.

De reden: dit soort langere-termijn analyses worden nu alleen opgeslagen, niet technisch getoetst. Het systeem checkt op dit moment alleen tips met een concrete korte-termijn instap. Deze setup viel daarbuiten en werd daardoor nooit als kans herkend, ook al stond het niveau gewoon in het systeem.

Dat is een gat, geen correcte werking. Excuses dat dit een reële kans heeft gekost.

Wat we bouwen: elke tip met een concreet niveau, ook bij langere-termijn analyses, wordt voortaan bewaakt. Zodra de prijs weer in de buurt komt, draait HesPulse een volledige technische toets op daily en 4-uur candles, berekent een instap, stop loss en take profit op basis van dat niveau, en stuurt een directe melding. Geen stille logregel meer, een echte actiemelding zoals je kent van day trading signalen.

Tot dat live staat: blijf zelf alert op tips met een duidelijk niveau, het systeem pakt dat nog niet automatisch op."""


async def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN ontbreekt in .env, kan niets versturen.")
        return

    db.init_db()
    users = [u for u in repo.list_users() if u["telegram_chat_id"]]
    if not users:
        print("Geen gebruikers met een gekoppelde Telegram chat gevonden.")
        return

    print(f"Dit bericht gaat naar {len(users)} gebruiker(s):")
    for u in users:
        print(f"  - {u['username']} (chat {u['telegram_chat_id']})")
    print("\n--- bericht ---")
    print(MESSAGE)
    print("--- einde bericht ---\n")

    confirm = input("Versturen? Typ 'ja' om door te gaan: ").strip().lower()
    if confirm != "ja":
        print("Geannuleerd, niets verstuurd.")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    sent, failed = 0, 0
    for u in users:
        try:
            await bot.send_message(chat_id=u["telegram_chat_id"], text=MESSAGE)
            sent += 1
            print(f"OK: {u['username']}")
        except Exception as exc:
            failed += 1
            print(f"MISLUKT: {u['username']}: {exc}")

    print(f"\nKlaar: {sent} verstuurd, {failed} mislukt.")


if __name__ == "__main__":
    asyncio.run(main())
