"""Risicomanagement: stop loss op echte marktstructuur (recente 4h swing
low/high, gedeeld, hetzelfde voor iedereen), take profit op basis van de
zo ontstane risicoafstand, en risicobedrag in euro's op basis van een eigen
portfoliobedrag per gebruiker."""
from dataclasses import dataclass
from typing import Optional

ATR_BUFFER_MULTIPLIER = 0.25  # ruimte onder/boven de swing, tegen een korte wick-stop
ATR_STOP_MULTIPLIER_FALLBACK = 1.5  # als er geen swing-data is
RISK_REWARD_RATIO = 2.0  # take profit op 2x de werkelijke stop-afstand


@dataclass
class StopTake:
    stop_loss: float
    take_profit: float


def compute_stop_take(
    direction: str, entry_price: float, atr: float,
    swing_low: Optional[float] = None, swing_high: Optional[float] = None,
) -> StopTake:
    """Stop loss net onder de recente 4h swing low bij een long (of net
    boven de swing high bij een short), met een kleine ATR-buffer zodat een
    korte wick niet meteen uitstopt. Valt terug op een vaste ATR-afstand als
    er geen bruikbare swing-data is. Take profit volgt de risk:reward
    verhouding op de zo ontstane, echte stop-afstand, niet op een losse
    vaste ATR-afstand."""
    direction = direction.lower()
    buffer = ATR_BUFFER_MULTIPLIER * atr

    if direction == "long":
        if swing_low is not None and swing_low < entry_price:
            stop_loss = swing_low - buffer
        else:
            stop_loss = entry_price - ATR_STOP_MULTIPLIER_FALLBACK * atr
        risk_distance = entry_price - stop_loss
        take_profit = entry_price + RISK_REWARD_RATIO * risk_distance
    elif direction == "short":
        if swing_high is not None and swing_high > entry_price:
            stop_loss = swing_high + buffer
        else:
            stop_loss = entry_price + ATR_STOP_MULTIPLIER_FALLBACK * atr
        risk_distance = stop_loss - entry_price
        take_profit = entry_price - RISK_REWARD_RATIO * risk_distance
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
