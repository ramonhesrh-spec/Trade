"""Dagelijks levensteken: stuurt elke gebruiker een korte pushmelding dat
het systeem nog draait. Zonder dit merk je een crash pas op als er een
tijd lang geen meldingen meer binnenkomen. Wordt aangeroepen via een
systemd timer, zie deploy/crypto-heartbeat.service en .timer.
"""
import asyncio
import logging

from app import db, push_notify, repo

logger = logging.getLogger("heartbeat")


async def send_heartbeats() -> None:
    timestamp = db.now_iso()[:16].replace("T", " ")
    title = "HesPulse draait"
    body = f"Goedemorgen trader. Nieuwe dag, nieuwe kansen. Laatste controle: {timestamp}."

    # Geen telegram_chat_id-gate (Taak 11): push_notify.send_push slaat een
    # gebruiker zonder push-abonnement zelf al stilzwijgend over, en
    # telegram_chat_id wordt sinds de overstap naar push nooit meer
    # ingevuld voor nieuwe gebruikers.
    for user in repo.list_users():
        try:
            await push_notify.send_push(user["id"], title, body, "/", silent=True)
            logger.info("Levensteken verstuurd naar %s", user["username"])
        except Exception:
            logger.exception("Levensteken naar %s is mislukt", user["username"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(send_heartbeats())
