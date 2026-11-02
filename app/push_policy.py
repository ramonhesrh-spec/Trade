"""Wanneer een kans als luide push bij een gebruiker aankomt. Pure beslisfunctie, geen database.
Sinds 2026-11-02 (CEO: veel te veel meldingen, ~560 nieuwe kaarten en ~255 vullingen in een week) is alleen een vulling luid. Een nieuwe kaart
is een stille melding buiten het budget (push_notify.send_new_card). Voor de luide push gelden twee regels, beide per gebruiker:
  1. Geen tegenstrijdige richting: ging er in de afgelopen CONFLICT_HOURS een push over dezelfde coin de andere kant op, dan komt de nieuwe niet als push.
     Long en short door elkaar op één coin is ruis die niemand kan opvolgen.
  2. Dagbudget: na `budget` luide pushes in 24 uur wordt de rest een stille melding. Elke luide push telt, ook een herhaling op dezelfde coin
     en richting (de oude uitzondering daarvoor is op verzoek van de CEO teruggedraaid). Een bundel (meer vullingen in één scancyclus, één push)
     telt één keer: push_log heeft dan een rij per coin voor de conflictregel, maar alleen de eerste heeft counts = 1.
Wat geen luide push wordt, blijft op de meldingenpagina staan: niets verdwijnt, alleen het scherm blijft rustig.
Updates van een lopende trade, stop- en doelmeldingen en de agenda blijven altijd komen en tellen niet mee."""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

DEFAULT_BUDGET = 8
CONFLICT_HOURS = 6


def used(recent: list[dict]) -> int:
    """Plekken van het dagbudget die in `recent` gebruikt zijn: elke luide push één, een bundel één (counts)."""
    return sum(1 if r.get("counts") is None else int(r["counts"]) for r in recent)


def conflict(recent: list[dict], coin: str, direction: str, now: datetime) -> Optional[str]:
    cut = now - timedelta(hours=CONFLICT_HOURS)
    for r in recent:
        if r["coin"] == coin and r["direction"] != direction and datetime.fromisoformat(r["at"]) >= cut:
            return f"Tegenstrijdig met een eerdere melding op {coin} ({r['direction']}), daarom geen push."
    return None


def over_budget(recent: list[dict], budget: Optional[int]) -> Optional[str]:
    limit = DEFAULT_BUDGET if budget is None else budget
    if limit and used(recent) >= limit:
        return f"Dagbudget van {limit} pushes bereikt, daarom een stille melding."
    return None


def decide(recent: list[dict], coin: str, direction: str, budget: Optional[int], now: datetime) -> tuple[bool, str]:
    """(mag als luide push, reden als niet). recent: pushes van de laatste 24 uur [{coin, direction, at, counts}]."""
    reason = conflict(recent, coin, direction, now) or over_budget(recent, budget)
    return (False, reason) if reason else (True, "")


def bundle_text(items: list[tuple[str, str]], kinds: Optional[list[str]] = None) -> tuple[str, str]:
    """Titel en tekst van één push voor meer luide kansen in dezelfde scancyclus, bijvoorbeeld '3 kansen gevuld' en 'SOL long, ETH short'.
    kinds: per item 'vulling' of 'entry' (HesPulse-model, entry beschikbaar); zijn het allemaal entries, dan '3 entries klaar'."""
    names = ", ".join(f"{coin} {direction}" for coin, direction in items)
    if kinds and all(k == "entry" for k in kinds):
        return f"{len(items)} entries klaar", names + "\nZet je limietorders. Tik voor Kansen."
    if kinds and any(k == "entry" for k in kinds):
        return f"{len(items)} kansen", names + "\nTik voor Kansen."
    return f"{len(items)} kansen gevuld", names + "\nTik voor Kansen."


def in_follow_set(coins: Optional[set], coin: str) -> bool:
    """Een volg-set (fase 2) laat alleen zijn eigen coins als push door; zonder set (None) komt alles. De kaarten en de data blijven gelijk."""
    return coins is None or coin in coins


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
