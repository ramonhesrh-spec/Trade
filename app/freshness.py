"""Hoe oud een getoonde koers is. web/main.py houdt per coin bij wanneer een koers voor het laatst echt van de beurs kwam: een mislukte
ophaal laat de oude koers staan (_cached_prices), dus zonder deze aparte tijd zou een koers van een uur oud er vers uitzien."""
from typing import Iterable, Optional

STALE_AFTER_S = 120


def oldest_age(fetched_at: dict[str, float], coins: Iterable[str], now: float) -> Optional[int]:
    """Leeftijd in hele seconden van de oudste koers onder `coins`; None als geen van die coins ooit een koers had."""
    ages = [now - fetched_at[c] for c in set(coins) if c in fetched_at]
    return int(max(ages)) if ages else None
