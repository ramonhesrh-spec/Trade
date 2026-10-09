"""Wanneer een kans als push bij een gebruiker aankomt. Pure beslisfunctie, geen database.
Twee regels, beide per gebruiker:
  1. Geen tegenstrijdige richting: ging er in de afgelopen CONFLICT_HOURS een push over dezelfde coin de andere kant op, dan komt de nieuwe niet als push.
     Long en short door elkaar op één coin is ruis die niemand kan opvolgen.
  2. Dagbudget: na `budget` pushes in 24 uur komt de rest niet als push.
Wat geen push wordt, blijft op de meldingenpagina staan: niets verdwijnt, alleen het scherm blijft rustig.
Alleen kansen met een coin en richting vallen hieronder. Updates van een lopende trade, stop- en doelmeldingen en de agenda blijven altijd komen."""
from datetime import datetime, timedelta
from typing import Optional

DEFAULT_BUDGET = 12
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
