"""Risicomanagement: stop loss en take profit op basis van ATR (gedeeld,
hetzelfde voor iedereen), en risicobedrag in euro's op basis van een eigen
portfoliobedrag per gebruiker."""
from dataclasses import dataclass
from typing import Optional

ATR_STOP_MULTIPLIER = 1.5
ATR_TARGET_MULTIPLIER = 3.0  # risk:reward van 1:2


@dataclass
class StopTake:
    stop_loss: float
    take_profit: float


def compute_stop_take(direction: str, entry_price: float, atr: float) -> StopTake:
    direction = direction.lower()
    if direction == "long":
        stop_loss = entry_price - ATR_STOP_MULTIPLIER * atr
        take_profit = entry_price + ATR_TARGET_MULTIPLIER * atr
    elif direction == "short":
        stop_loss = entry_price + ATR_STOP_MULTIPLIER * atr
        take_profit = entry_price - ATR_TARGET_MULTIPLIER * atr
    else:
        raise ValueError(f"onbekende richting: {direction}")

    return StopTake(stop_loss=stop_loss, take_profit=take_profit)


def compute_risk_eur(portfolio_eur: float, risk_percent: float) -> float:
    return portfolio_eur * (risk_percent / 100.0)


def compute_position_size(risk_eur: float, entry_price: float, stop_loss: float) -> Optional[float]:
    """Hoeveel coin je koopt bij dit risicobedrag: risicobedrag gedeeld door
    de afstand tussen entry en stop loss. Geeft None als die afstand nul is,
    wat niet zou moeten voorkomen maar voorkomt een deling door nul."""
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    return risk_eur / distance
