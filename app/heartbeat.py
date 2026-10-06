"""Dagelijks levensteken: stuurt elke gebruiker een korte pushmelding dat
het systeem nog draait. Zonder dit merk je een crash pas op als er een
tijd lang geen meldingen meer binnenkomen. Wordt aangeroepen via een
systemd timer, zie deploy/crypto-heartbeat.service en .timer.
"""
import asyncio
import logging

from datetime import datetime, timedelta, timezone

from app import config, db, market_calendar, push_notify, repo, today, track_record

logger = logging.getLogger("heartbeat")


async def send_heartbeats() -> None:
    timestamp = db.now_iso()[:16].replace("T", " ")
    title = "HesPulse draait"
    plans = len(repo.list_structure_setups(("waiting",)))
    next_moment = today.agenda(market_calendar.upcoming(datetime.now(timezone.utc), 24))
    day = track_record.day_summary(repo.list_signals_for_quality_report(None), config.TRACK_RECORD_COST_PCT, datetime.now(timezone.utc) - timedelta(hours=24))
    lines = [f"Laatste 24 uur: {day['signals']} {'kans' if day['signals'] == 1 else 'kansen'} gemeld, {day['resolved']} afgerond"
             + (f", {day['net_r']:+.1f}R na kosten." if day["resolved"] else ".")]
    lines.append(f"{plans} {'plan' if plans == 1 else 'plannen'} klaar.")
    if next_moment:
        m = next_moment[0]
        lines.append(f"Straks: {m['label']} om {today.local(m['at']).strftime('%H:%M')}.")
    lines.append(f"Laatste controle: {timestamp}.")
    body = "\n".join(lines)

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
