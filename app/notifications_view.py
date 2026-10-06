"""Weergave van de pagina Meldingen: per dag gegroepeerd, met een label per soort en een tijd die leest als een mens
praat ("3 uur geleden"). Pure functies, geen database."""
from datetime import datetime, timezone
from typing import Optional

from app import today

TYPE_CHIPS = {
    "update": ("Nieuw", "chip-new"),
    "quality_report": ("Rapport", "chip-report"),
    "expired_signal": ("Vervallen", "chip-muted"),
    "new_coin": ("Coin", "chip-muted"),
}
DEFAULT_CHIP = ("Melding", "chip-muted")


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def relative_time(at: datetime, now: datetime) -> str:
    seconds = max(0, (now - at).total_seconds())
    if seconds < 90:
        return "zojuist"
    if seconds < 3600:
        return f"{int(seconds // 60)} min geleden"
    if seconds < 86400:
        return f"{int(seconds // 3600)} uur geleden"
    return today.local(at).strftime("%d-%m, %H:%M")


def day_label(at: datetime, now: datetime) -> str:
    days = (today.local(now).date() - today.local(at).date()).days
    if days <= 0:
        return "Vandaag"
    if days == 1:
        return "Gisteren"
    return f"{today.DAYS[today.local(at).weekday()].capitalize()} {today.local(at):%d-%m}"


def group_notifications(rows: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """Nieuwste eerst. Elke groep heeft een dagnaam en items met label, relatieve tijd en gelezen-status."""
    now = now or datetime.now(timezone.utc)
    groups: list[dict] = []
    for r in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        at = _parse(r["created_at"])
        label, css = TYPE_CHIPS.get(r.get("type"), DEFAULT_CHIP)
        item = {**r, "chip": label, "chip_class": css, "when": relative_time(at, now), "unread": not r.get("is_read")}
        day = day_label(at, now)
        if not groups or groups[-1]["label"] != day:
            groups.append({"label": day, "items": []})
        groups[-1]["items"].append(item)
    return groups
