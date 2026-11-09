"""Weekterugblik (fase 2, ontwerp E): pure functies zonder database. Eén groot getal (de gemeten R van jouw trades deze week), acht weken
ernaast, de getallen eronder en hoogstens één observatie die alleen telt wat vaststaat.

Invoer komt uit app/logbook.py: `trades` zijn jouw afgeronde trades met hun R uit track_record.signal_r en het moment van de uitkomst,
`skips` jouw overgeslagen plannen met de uitkomst van het signaal waartoe ze later werden (of geen). Een week is een ISO-week in de
Nederlandse tijd. "Volgens plan" staat er niet: HesPulse weet niet of je stop en doel echt zo liet staan, dus dat getal bestaat niet."""
from datetime import date, datetime, timedelta
from typing import Optional

from app import logbook

WEEKS = 8
MONTHS = logbook.MONTHS


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _range_text(start: date) -> str:
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS[end.month - 1]}"
    return f"{start.day} {MONTHS[start.month - 1][:3]} – {end.day} {MONTHS[end.month - 1][:3]}"


def _short(value: float) -> str:
    text = logbook.r_text(value)[:-2]
    return "0" if round(value, 1) == 0 else text


def review(trades: list[dict], skips: list[dict], now: datetime, tz, weeks: int = WEEKS) -> dict:
    this_start = _week_start(now.astimezone(tz).date())
    starts = [this_start - timedelta(weeks=k) for k in range(weeks - 1, -1, -1)]

    def week_of(at: str) -> date:
        return _week_start(logbook._parse(at).astimezone(tz).date())

    per_week = {s: [] for s in starts}
    for tr in trades:
        w = week_of(tr["at"])
        if w in per_week:
            per_week[w].append(tr["r"])
    mine = per_week[this_start]
    total = sum(mine)
    wins = sum(1 for r in mine if r > 0)
    losses = sum(1 for r in mine if r < 0)
    week_skips = [s for s in skips if week_of(s["at"]) == this_start]

    if mine:
        parts = [f"{len(mine)} trade{'s' if len(mine) != 1 else ''}", f"{wins} gewonnen", f"{losses} verloren"]
        if week_skips:
            parts.append(f"{len(week_skips)} overgeslagen")
        counts = " · ".join(parts)
    else:
        counts = "Nog geen afgeronde trade deze week" + (f" · {len(week_skips)} overgeslagen" if week_skips else "")

    stats = []
    if mine:
        stats.append({"label": "Gem. per trade", "value": (f"{total / len(mine):+.2f}".replace(".", ",").replace("-", "−")) + " R"})
        if losses:
            stats.append({"label": "Grootste verlies", "value": logbook.r_text(min(mine))})

    sums = [sum(per_week[s]) for s in starts]
    peak = max((abs(v) for v in sums), default=0) or 1.0
    bars = [{"name": f"w{s.isocalendar()[1]}", "value": v, "value_text": _short(v), "negative": v < 0, "current": s == this_start,
             "height_pct": round(abs(v) / peak * 100, 1)} for s, v in zip(starts, sums)]

    return {"label": f"Week {this_start.isocalendar()[1]} · {_range_text(this_start)}", "total": total, "total_text": logbook.r_text(total),
            "counts_text": counts, "stats": stats, "weeks": bars, "eight_total_text": logbook.r_text(sum(sums)),
            "observation": _observation(week_skips)}


def _observation(skips: list[dict]) -> Optional[str]:
    """Alleen telbaar: van de overgeslagen plannen waarvan de uitkomst vaststaat (doel of stop), hoeveel hun doel haalden."""
    known = [s for s in skips if s.get("outcome") in ("take_profit", "stop_loss") and s.get("r") is not None]
    if not known:
        return None
    hits = [s for s in known if s["outcome"] == "take_profit"]
    if len(known) == 1:
        return "Je ene overgeslagen plan met een uitkomst " + ("haalde zijn doel." if hits else "raakte zijn stop.") + \
            (f" Samen {logbook.r_text(hits[0]['r'])} die je niet nam." if hits else "")
    text = f"{len(hits)} van je {len(known)} overgeslagen plannen met een uitkomst haalden hun doel."
    if hits:
        text += f" Samen {logbook.r_text(sum(s['r'] for s in hits))} die je niet nam."
    return text
