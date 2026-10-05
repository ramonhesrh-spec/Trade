"""Na-analyse van alle SMC-setups uit het meetraam, ook die nooit een signaal werden.
Elke setup krijgt één vaste, eenvoudige trade (limietorder op de zonerand, stop achter
de sweep, take als veelvoud van de stop of het liquiditeitsdoel) zodat er ongeveer
zes keer meer trades zijn dan live signalen. Dat geeft genoeg aantal om te toetsen
welke kenmerken van een setup winnaars scheiden van verliezers.

Benadering: de zonegrenzen in een setup-rij zijn de laatste stand (ze schuiven mee
tot het signaal). In de fill-candle telt de stop volledig mee, maar kan de take niet
geraakt worden: wat die candle voor de fill deed, hoort niet bij de trade."""
from typing import Optional

import pandas as pd

from app import smc_eval
from app.replay.outcome import Outcome, resolve
from app.replay.view import ReplayData

ONE_MINUTE = pd.Timedelta(minutes=1)
STOP_ATR_MARGIN = smc_eval.STOP_MARGIN_ATR_MULTIPLE
DEFAULT_RR = (1.0, 1.5, 2.0)
TARGET = "doel"


def simulate_setup(
    setup: dict, frame: pd.DataFrame, rr_list=DEFAULT_RR, max_fill: pd.Timedelta = pd.Timedelta(hours=smc_eval.SMC_SETUP_MAX_AGE_HOURS),
    max_age: pd.Timedelta = pd.Timedelta(hours=48), fee_pct: float = 0.1, slippage_pct: float = 0.05,
    stop_margin_atr: float = STOP_ATR_MARGIN,
) -> Optional[dict]:
    """Geeft None als de setup onbruikbaar is (geen atr, stop aan de verkeerde kant). Anders
    een dict met `status` ('gevuld' of 'niet_gevuld') en bij 'gevuld' de entry, stop en per
    take-variant een Outcome in `outcomes` (sleutels: de rr-waarden en TARGET)."""
    atr = setup.get("atr")
    if atr is None or pd.isna(atr):
        return None
    direction = setup["direction"]
    long = direction == "long"
    entry = setup["zone_high"] if long else setup["zone_low"]
    stop = setup["sweep_price"] - stop_margin_atr * atr if long else setup["sweep_price"] + stop_margin_atr * atr
    risk = entry - stop if long else stop - entry
    if risk <= 0:
        return None
    created = pd.Timestamp(setup["created_at"])
    timestamps = frame["timestamp"]
    lo = timestamps.searchsorted(created, side="left")
    hi = timestamps.searchsorted(created + max_fill, side="left")
    window = frame.iloc[lo:hi]
    touch = window["low"].to_numpy() <= entry if long else window["high"].to_numpy() >= entry
    if not touch.any():
        return {"status": "niet_gevuld", "entry": entry, "stop": stop, "risk_pct": risk / entry * 100}
    fill_idx = lo + int(touch.argmax())
    fill_at = frame["timestamp"].iloc[fill_idx]
    after = frame.iloc[fill_idx:fill_idx + int(max_age / ONE_MINUTE) + 2].copy()
    # Eerste candle: na de fill kan de koers hooguit op de entry gestaan hebben.
    col = after.columns.get_loc("high" if long else "low")
    after.iloc[0, col] = min(after.iloc[0, col], entry) if long else max(after.iloc[0, col], entry)
    outcomes: dict = {}
    sign = 1 if long else -1
    for rr in rr_list:
        outcomes[rr] = resolve(direction, entry, stop, entry + sign * risk * rr, after, fill_at, max_age, fee_pct, slippage_pct)
    target = setup["liquidity_target"]
    if (target - entry) * sign >= risk:
        outcomes[TARGET] = resolve(direction, entry, stop, target, after, fill_at, max_age, fee_pct, slippage_pct)
    return {"status": "gevuld", "fill_at": fill_at, "entry": entry, "stop": stop, "risk_pct": risk / entry * 100,
            "minutes_to_fill": (fill_at - created).total_seconds() / 60, "outcomes": outcomes}


def _trend_aligned(df: pd.DataFrame, direction: str, fast: int, slow: int) -> Optional[bool]:
    closed = df.iloc[:-1]
    if len(closed) < slow + 5:
        return None
    close = closed["close"]
    up = close.ewm(span=fast, adjust=False).mean().iloc[-1] > close.ewm(span=slow, adjust=False).mean().iloc[-1]
    return bool(up == (direction == "long"))


def setup_features(setup: dict, base: dict) -> dict:
    """Kenmerken op het moment dat de setup gebouwd werd, alleen uit candles die toen gesloten waren."""
    coin, direction = setup["coin"], setup["direction"]
    at = pd.Timestamp(setup["created_at"])
    data = ReplayData(base, at, base_delta=ONE_MINUTE)
    mid = (setup["zone_low"] + setup["zone_high"]) / 2
    atr = setup["atr"]
    out = {
        "trend_4u": _trend_aligned(data.fetch_ohlcv(coin, "4h", limit=120), direction, 21, 50),
        "trend_dag": _trend_aligned(data.fetch_ohlcv(coin, "1d", limit=120), direction, 21, 50),
        "sweepdiepte_atr": abs(setup["structure_level"] - setup["sweep_price"]) / atr if atr else None,
        "zone_pct": (setup["zone_high"] - setup["zone_low"]) / mid * 100,
        "atr_pct": atr / mid * 100 if atr else None,
        "uur": at.hour,
        "weekend": at.dayofweek >= 5,
    }
    out["trend_btc_4u"] = out["trend_4u"] if coin == "BTC" or "BTC" not in base else \
        _trend_aligned(data.fetch_ohlcv("BTC", "4h", limit=120), direction, 21, 50)
    return out
