"""Telling voor scripts/structuur_check.py: komen er minder of andere Structuur-kansen? Pure functies over de rijen van
repo.list_structure_report_rows en de hartslag 'structuur'; geen database, geen netwerk.

Begrippen, gelijk aan de motor (app/structure_live.py) en repo.count_structure_alerts_since:
  breuken   elke rij (ook zonder plan)
  plannen   een breuk met plan (stand niet 'geen_plan')
  gemeld    stand niet in NOT_ANNOUNCED: kreeg de luide melding (en telt mee voor de dagcap)
  gevuld    met signal_id: de limiet raakte en het werd een signaal
  niet_gemeld  door een volle dagcap gehouden (STRUCTURE_MAX_ALERTS_PER_DAY): dan is de cap geraakt
  vast      stand 'oordeel': ontdekt maar nooit gemeld of gehouden, de run brak tussen ontdekken en melden af"""
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from app import focus, today
from app.structure_live import parse_beat

NOT_ANNOUNCED = ("geen_plan", "niet_gemeld", "geen_oordeel", "schaduw", "oordeel")


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def daily(rows: list[dict], now: datetime, days: int = 10) -> list[dict]:
    """Per kalenderdag in Nederlandse tijd, nieuwste eerst."""
    first = today.local(now).date()
    out = []
    for k in range(days):
        day = first - timedelta(days=k)
        mine = [r for r in rows if today.local(_at(r["created_at"])).date() == day]
        plans = [r for r in mine if r["state"] != "geen_plan"]
        filled = [r for r in mine if r.get("signal_id")]
        held = sum(1 for r in mine if r["state"] == "niet_gemeld")
        out.append({"date": day.isoformat(), "breuken": len(mine), "plannen": len(plans),
                    "gemeld": sum(1 for r in mine if r["state"] not in NOT_ANNOUNCED), "gevuld": len(filled),
                    "doel": sum(1 for r in filled if r.get("auto_outcome") == "take_profit"),
                    "stop": sum(1 for r in filled if r.get("auto_outcome") == "stop_loss"),
                    "open": sum(1 for r in filled if not r.get("auto_outcome")),
                    "niet_gemeld": held, "vast": sum(1 for r in mine if r["state"] == "oordeel"), "cap_hit": held > 0})
    return out


def coin_counts(rows: list[dict], coins: list[str], now: datetime, days: int = 7) -> tuple[list[tuple[str, int]], list[str]]:
    """(coins met plannen, meeste eerst en bij gelijk op naam; gevolgde coins zonder enig plan) over de laatste `days` dagen."""
    since = now - timedelta(days=days)
    n = Counter(r["coin"] for r in rows if r["state"] != "geen_plan" and _at(r["created_at"]) >= since)
    return sorted(n.items(), key=lambda kv: (-kv[1], kv[0])), [c for c in coins if not n[c]]


def beat_view(beat: Optional[dict], total: int, now: datetime) -> dict:
    """Leeftijd en dekking van de laatste run. `all` is False als niet alle FIXED_COINS bekeken zijn (of de tekst geen telling is)."""
    if not beat:
        return {"minutes": None, "detail": "", "checked": None, "total": total, "all": False, "off": False}
    minutes = int((now - _at(beat["at"])).total_seconds() // 60)
    count = parse_beat(beat.get("detail") or "")
    return {"minutes": minutes, "detail": beat.get("detail") or "", "checked": count["checked"] if count else None, "total": total,
            "all": bool(count) and count["checked"] >= total, "off": (beat.get("detail") or "") == focus.OFF_DETAIL}
