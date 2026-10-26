"""Het Logboek als dagtijdlijn (fase 2): pure functies zonder database of netwerk. De route geeft de rijen uit app/repo.py mee."""
from datetime import datetime, timezone
from typing import Optional


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def checklist_seconds(opened_at: Optional[str], done_at: Optional[str]) -> Optional[int]:
    """Hoe lang de checklist openstond tot alle stappen stonden; alleen als beide tijden bestaan, anders bestaat het getal niet."""
    if not opened_at or not done_at:
        return None
    seconds = int((_parse(done_at) - _parse(opened_at)).total_seconds())
    return seconds if seconds >= 0 else None


def duration_text(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} u {minutes} min" if minutes else f"{hours} u"
    if minutes:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    return f"{secs} s"
