"""Dagbrief: twee keer per dag één melding met wat er wacht, in plaats van een melding per kans. Draait mee in de
snelcyclus van de motoren en meldt per dagdeel hooguit één keer (repo.alert_once)."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app import repo, today

logger = logging.getLogger(__name__)
SLOTS = (8, 20)          # lokale uren; de cyclus draait elke 5 minuten, dus de brief komt binnen een paar minuten na dit uur


def slot_key(now: datetime) -> Optional[str]:
    """Sleutel van het dagdeel waarin we nu zitten (08:00-11:59 of 20:00-23:59 lokaal), anders None."""
    local = today.local(now)
    for start in reversed(SLOTS):
        if local.hour >= start and (start == SLOTS[-1] or local.hour < SLOTS[-1]):
            return f"digest:{local.date().isoformat()}:{start}"
    return None


def build(waiting: list[dict]) -> Optional[tuple[str, str]]:
    """waiting: [{coin, direction, grade, dist_pct}], dist_pct = hoever de koers nog van het niveau is (positief = nog te gaan).
    Geeft (titel, tekst) of None als er niets wacht."""
    if not waiting:
        return None
    ordered = sorted(waiting, key=lambda w: abs(w["dist_pct"]))
    nearest = ordered[0]
    n = len(ordered)
    title = f"{n} {'kans wacht' if n == 1 else 'kansen wachten'}"
    lines = [f"{w['coin']} {w['direction']}{' ' + w['grade'] if w.get('grade') in ('A', 'B') else ''}: nog {abs(w['dist_pct']):.1f}%" for w in ordered[:3]]
    body = f"Het dichtst bij: {nearest['coin']} {nearest['direction']}, nog {abs(nearest['dist_pct']):.1f}%.\n" + "\n".join(lines[1:] if n > 1 else [])
    return title, body.strip()


async def run(now: Optional[datetime] = None) -> None:
    import asyncio
    from app import exchange, push_notify
    now = now or datetime.now(timezone.utc)
    key = slot_key(now)
    if not key:
        return
    waiting = []
    for s in repo.list_structure_setups(("waiting",), 30):
        try:
            price = await asyncio.to_thread(exchange.fetch_last_price, s["coin"])
        except Exception:
            continue
        level = json.loads(s["plan"])["level"]
        dist = (level - price) / price * 100 if s["direction"] == "short" else (price - level) / price * 100
        waiting.append({"coin": s["coin"], "direction": s["direction"], "grade": s["grade"], "dist_pct": dist})
    message = build(waiting)
    if not message or not repo.alert_once(key):
        return
    for user in repo.list_users():
        try:
            await push_notify.send_push(user["id"], message[0], message[1], "/structuur", silent=push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"]), tag="dagbrief")
        except Exception:
            logger.exception("Dagbrief naar %s is mislukt", user["username"])
