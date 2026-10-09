"""Dagelijks levensteken: stuurt elke gebruiker een korte pushmelding dat
het systeem nog draait. Zonder dit merk je een crash pas op als er een
tijd lang geen meldingen meer binnenkomen. Wordt aangeroepen via een
systemd timer, zie deploy/crypto-heartbeat.service en .timer.
"""
import asyncio
import logging

from datetime import datetime, timedelta, timezone

from app import config, db, market_calendar, push_notify, repo, rule_live, today, track_record

logger = logging.getLogger("heartbeat")


def heartbeat_body(rows: list[dict], plans: int, next_moment: list[dict], timestamp: str) -> str:
    day = track_record.day_summary(rows, config.TRACK_RECORD_COST_PCT, datetime.now(timezone.utc) - timedelta(hours=24))
    lines = [f"Laatste 24 uur: {day['signals']} {'kans' if day['signals'] == 1 else 'kansen'} gemeld, {day['resolved']} afgerond"
             + (f", {day['net_r']:+.1f}R na kosten." if day["resolved"] else ".")]
    lines.append(f"{plans} {'plan' if plans == 1 else 'plannen'} klaar.")
    if next_moment:
        m = next_moment[0]
        lines.append(f"Straks: {m['label']} om {today.local(m['at']).strftime('%H:%M')}.")
    lines.append(f"Laatste controle: {timestamp}.")
    return "\n".join(lines)


async def send_heartbeats() -> None:
    timestamp = db.now_iso()[:16].replace("T", " ")
    plans = len(repo.list_structure_setups(("waiting",)))
    next_moment = today.agenda(market_calendar.upcoming(datetime.now(timezone.utc), 24))
    rows = repo.list_signals_for_quality_report(None)
    ceo = repo.get_ceo_user()

    # Geen telegram_chat_id-gate (Taak 11): push_notify.send_push slaat een
    # gebruiker zonder push-abonnement zelf al stilzwijgend over, en
    # telegram_chat_id wordt sinds de overstap naar push nooit meer
    # ingevuld voor nieuwe gebruikers.
    sunday = datetime.now(timezone.utc).weekday() == 6
    for user in repo.list_users():
        # Per gebruiker: de proef (rule_live) telt alleen in de cijfers van de CEO.
        body = heartbeat_body(rule_live.for_viewer(rows, bool(ceo) and user["id"] == ceo["id"]), plans, next_moment, timestamp)
        title = "Kwartaalcijfers van de CEO"
        if sunday:
            title, body = "Jouw week staat klaar", body + "\nTik voor je week als plaatje."
        try:
            await push_notify.send_push(user["id"], title, body, "/week" if sunday else "/", silent=True)
            logger.info("Levensteken verstuurd naar %s", user["username"])
        except Exception:
            logger.exception("Levensteken naar %s is mislukt", user["username"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    asyncio.run(send_heartbeats())
