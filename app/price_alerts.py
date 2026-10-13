"""Prijsalarm vanaf een kaart: tik op een niveau, melding zodra de koers er is. Pure functies; repo bewaart, level_check toetst elke 15 minuten."""
from typing import Iterable, Optional

from app.chance_steps import fmt

MAX_OPEN_PER_USER = 20


def side_for(target: float, current: float) -> str:
    """De kant ligt vast bij het aanmaken. Zonder vaste kant zou een alarm onder de koers meteen afgaan op elke candle die erboven ligt."""
    return "above" if target >= current else "below"


def first_hit(side: str, target: float, bars: Iterable[tuple[float, float]]) -> Optional[float]:
    """bars: (hoog, laag) per candle, oudste eerst. De candle-hoog of -laag waarop het niveau geraakt werd, of None."""
    for high, low in bars:
        if side == "above" and high >= target:
            return float(high)
        if side == "below" and low <= target:
            return float(low)
    return None


def alert_text(coin: str, label: str, target: float, hit: float) -> tuple[str, str]:
    return f"Prijsalarm {coin}: {label.lower()} {fmt(target)} bereikt", f"Koers raakte {fmt(hit)}.\nTik voor de kaart."
