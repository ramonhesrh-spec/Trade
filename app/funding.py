"""Funding van een afgeronde trade, in R van de stopafstand. Zuiver; het ophalen doet app/outcome_measure.py. Alleen meting: Bewijs trekt het
af van de netto R, geen motor, filter of melding leest het.

De regel: elk funding-moment van het perpcontract strikt na de vulling en strikt vóór het einde van de uitgangscandle telt. Een long betaalt
de rate (positief kost geld, negatief levert op), een short krijgt hem. Binance rekent funding over de waarde van de positie op het moment
zelf; hier over de instapwaarde, want R rekent ook met de instap. Het interval verschilt per contract (8 uur, soms 4 of 1 uur): de momenten
komen uit de API zelf, dus het interval hoeft niet bekend te zijn."""
from typing import Iterable, Optional

import pandas as pd

from app import candle_source


def symbol(coin: str) -> str:
    """Het perpcontract zoals /fapi het kent; een 1000-contract heeft dezelfde rate per munt."""
    base = candle_source.base_of(coin)
    return f"{candle_source.PERP_ALIASES.get(base, base)}USDT"


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def rates_between(events: Iterable[tuple], start, end) -> list[float]:
    lo, hi = _ts(start), _ts(end)
    return [float(rate) for t, rate in events if lo < _ts(t) < hi]


def measure(direction: str, entry: float, stop: float, events: Iterable[tuple], start, end) -> Optional[dict]:
    """funding_pct is wat de trade betaalde in procenten van de instapwaarde (negatief: ontvangen), funding_r hetzelfde in R. Geen moment in
    het venster is een gemeten nul."""
    stop_pct = abs(entry - stop) / entry * 100 if entry else 0.0
    if not stop_pct:
        return None
    rates = rates_between(events, start, end)
    paid_pct = sum(rates) * 100 * (-1 if direction == "short" else 1)
    return {"funding_pct": paid_pct, "funding_r": paid_pct / stop_pct, "events": len(rates)}
