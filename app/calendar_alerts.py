"""Herinnering vóór een moment uit de agenda: de opening van de VS-beurs (de enige regelmatige gebeurtenis die de toets als
duidelijk anders mat) en macro-uitslagen uit data/macro_events.csv. Draait in de SMC-snelcyclus; app/repo.alert_once zorgt dat
elk moment maar één keer gemeld wordt. De opening van de VS-beurs gaat stil (dat is elke werkdag), een macro-uitslag niet."""
import logging
from datetime import datetime, timezone
from typing import Optional

from app import market_calendar, push_notify, repo, today

logger = logging.getLogger("calendar_alerts")
LEAD_MINUTES = 30
ALERT_KINDS = ("vs_open", "macro")


def due(now: datetime) -> list[dict]:
    """Momenten die binnen LEAD_MINUTES beginnen en nog niet voorbij zijn."""
    return [m for m in today.agenda(market_calendar.upcoming(now, LEAD_MINUTES / 60)) if m["kind"] in ALERT_KINDS]


def message(m: dict, now: datetime) -> tuple[str, str]:
    minutes = max(1, round((m["at"] - now).total_seconds() / 60))
    clock = today.local(m["at"]).strftime("%H:%M")
    title = f"⏱ {m['label']} om {clock}"
    note = today.vol_note(m["kind"])
    if m["kind"] == "macro":
        body = f"Over {minutes} min. Een uitslag beweegt snel. Check je open limietorders en stops."
    else:
        body = f"Over {minutes} min." + (f" De markt {note}." if note else "")
    return title, body


async def run(now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    sent = 0
    for m in due(now):
        if not repo.alert_once(f"cal:{m['kind']}:{m['at'].isoformat()}"):
            continue
        title, body = message(m, now)
        for user in repo.list_users():
            quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
            try:
                await push_notify.send_push(user["id"], title, body, "/vandaag", silent=quiet or m["kind"] != "macro", tag=f"agenda-{m['kind']}")
            except Exception:
                logger.exception("Agenda-melding naar gebruiker %s is mislukt", user["username"])
        sent += 1
    return sent
