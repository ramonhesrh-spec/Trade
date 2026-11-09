"""Hoe oud een getoonde koers is. web/main.py houdt per coin bij wanneer een koers voor het laatst echt van de beurs kwam: een mislukte
ophaal laat de oude koers staan (_cached_prices), dus zonder deze aparte tijd zou een koers van een uur oud er vers uitzien."""
from datetime import datetime, timezone
from typing import Iterable, Optional

STALE_AFTER_S = 120


def oldest_age(fetched_at: dict[str, float], coins: Iterable[str], now: float) -> Optional[int]:
    """Leeftijd in hele seconden van de oudste koers onder `coins`; None als geen van die coins ooit een koers had."""
    ages = [now - fetched_at[c] for c in set(coins) if c in fetched_at]
    return int(max(ages)) if ages else None


def age_seconds(iso: Optional[str], now: datetime) -> Optional[int]:
    """Leeftijd van een opgeslagen meting in hele seconden; None zonder (leesbaar) tijdstip, zodat er nooit een verzonnen leeftijd staat."""
    if not iso:
        return None
    try:
        at = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0, int((now - (at if at.tzinfo else at.replace(tzinfo=timezone.utc))).total_seconds()))


def age_text(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return "net"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} u"
    return f"{seconds // 86400} d"
