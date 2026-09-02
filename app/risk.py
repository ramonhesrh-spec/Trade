"""Risicomanagement: stop loss, take profit op basis van ATR, en risicobedrag
in euro's op basis van handmatig ingevuld portfoliobedrag."""
from dataclasses import dataclass

ATR_STOP_MULTIPLIER = 1.5
ATR_TARGET_MULTIPLIER = 3.0  # risk:reward van 1:2


@dataclass
class RiskLevels:
    stop_loss: float
    take_profit: float
    risk_eur: float


def compute_levels(
    direction: str,
    entry_price: float,
    atr: float,
    portfolio_eur: float,
    risk_percent: float,
) -> RiskLevels:
    direction = direction.lower()
    if direction == "long":
        stop_loss = entry_price - ATR_STOP_MULTIPLIER * atr
        take_profit = entry_price + ATR_TARGET_MULTIPLIER * atr
    elif direction == "short":
        stop_loss = entry_price + ATR_STOP_MULTIPLIER * atr
        take_profit = entry_price - ATR_TARGET_MULTIPLIER * atr
    else:
        raise ValueError(f"onbekende richting: {direction}")

    risk_eur = portfolio_eur * (risk_percent / 100.0)

    return RiskLevels(stop_loss=stop_loss, take_profit=take_profit, risk_eur=risk_eur)
