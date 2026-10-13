"""Wanneer een kans als push bij een gebruiker aankomt. Pure beslisfunctie, geen database.
Twee regels, beide per gebruiker:
  1. Geen tegenstrijdige richting: ging er in de afgelopen CONFLICT_HOURS een push over dezelfde coin de andere kant op, dan komt de nieuwe niet als push.
     Long en short door elkaar op één coin is ruis die niemand kan opvolgen.
  2. Dagbudget: na `budget` pushes in 24 uur komt de rest niet als push.
Wat geen push wordt, blijft op de meldingenpagina staan: niets verdwijnt, alleen het scherm blijft rustig.
Alleen kansen met een coin en richting vallen hieronder. Updates van een lopende trade, stop- en doelmeldingen en de agenda blijven altijd komen."""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

DEFAULT_BUDGET = 6
CONFLICT_HOURS = 6


def decide(recent: list[dict], coin: str, direction: str, budget: Optional[int], now: datetime) -> tuple[bool, str]:
    """(mag als push, reden als niet). recent: pushes van de laatste 24 uur [{coin, direction, at}]."""
    limit = DEFAULT_BUDGET if budget is None else budget
    cut = now - timedelta(hours=CONFLICT_HOURS)
    for r in recent:
        if r["coin"] == coin and r["direction"] != direction and datetime.fromisoformat(r["at"]) >= cut:
            return False, f"Tegenstrijdig met een eerdere melding op {coin} ({r['direction']}), daarom geen push."
    if limit and len(recent) >= limit:
        return False, f"Dagbudget van {limit} pushes bereikt, daarom geen push."
    return True, ""


PAUSE_HOURS = 2


def pause_until(now: datetime) -> datetime:
    return now + timedelta(hours=PAUSE_HOURS)


def pause_minutes_left(paused_until: Optional[str], now: datetime) -> int:
    """Hele minuten tot de pauze afloopt, naar boven afgerond, zodat de knop nooit "0" toont terwijl hij nog stil is."""
    if not paused_until:
        return 0
    try:
        until = datetime.fromisoformat(paused_until)
    except ValueError:
        return 0
    until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
    seconds = (until - now).total_seconds()
    return math.ceil(seconds / 60) if seconds > 0 else 0


def pause_text(minutes_left: int) -> str:
    if minutes_left <= 0:
        return "Pauze"
    return f"Stil {minutes_left // 60}:{minutes_left % 60:02d}"
