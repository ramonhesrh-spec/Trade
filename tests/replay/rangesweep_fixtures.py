"""Een kunstmatige markt met één schone range, aanbod- en vraagzones op de randen en één sweep, opgebouwd uit 15m-candles zodat 30m, 1u, 2u
en 4u er exact uit volgen. Uren: 40 vlak op 103, in 5 uur naar 100, zes keer 10 uur op naar 106 en 10 uur af naar 100, 9 uur op naar 105,4,
dan het sweep-uur (prik naar 106,5, slot 105,6), 10 uur af naar 100 en 20 uur vlak. Pieken op uur 54, 74, ..., 154; dalen op 44, 64, ..., 164.
Elke piek is een groene candle met daarna een daling van meer dan 1 ATR: een aanbodzone 105,375 tot 106,025. Elke dal gespiegeld: een
vraagzone 99,975 tot 100,625. De range is pas bekend als er drie toppen en drie dalen bevestigd zijn: de eerste long-setup komt bij de
nadering op uur 102, de eerste short-setup op uur 112."""
import pandas as pd

START = pd.Timestamp("2025-03-03 00:00", tz="UTC")
SWEEP_HOUR = 174
FIRST_PEAK_HOUR = 54
FIRST_SHORT_ZONE_SETUP_HOUR = 112
FIRST_LONG_ZONE_SETUP_HOUR = 102
WICK = 0.025
SWEEP_15M = [(105.4, 105.925, 105.375, 105.9), (105.9, 106.5, 105.875, 106.2), (106.2, 106.225, 105.775, 105.8), (105.8, 105.825, 105.575, 105.6)]


def hourly_closes_before_sweep() -> list[float]:
    p = [103.0] * 40
    p += [103.0 - 0.6 * k for k in range(1, 6)]
    for _ in range(6):
        p += [100.0 + 0.6 * k for k in range(1, 11)]
        p += [106.0 - 0.6 * k for k in range(1, 11)]
    p += [100.0 + 0.6 * k for k in range(1, 10)]
    return p


def _linear_15m(prev: float, close: float) -> list[tuple]:
    out, o = [], prev
    for q in range(1, 5):
        c = prev + (close - prev) * q / 4
        out.append((o, max(o, c) + WICK, min(o, c) - WICK, c))
        o = c
    return out


def frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes = hourly_closes_before_sweep()
    rows, prev = [], closes[0]
    for c in closes:
        rows += _linear_15m(prev, c)
        prev = c
    rows += SWEEP_15M
    prev = 105.6
    for k in range(1, 11):
        c = 105.6 - 0.56 * k
        rows += _linear_15m(prev, c)
        prev = c
    for _ in range(20):
        rows += _linear_15m(prev, 100.0)
        prev = 100.0
    b15 = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    b15.insert(0, "timestamp", pd.date_range(START, periods=len(b15), freq="15min"))
    b15["volume"] = 1.0
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    b1h = b15.set_index("timestamp").resample("1h", origin="epoch").agg(agg).dropna().reset_index()
    b4h = b15.set_index("timestamp").resample("4h", origin="epoch").agg(agg).dropna().reset_index()
    return b15, b1h, b4h
