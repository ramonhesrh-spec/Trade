"""Synthetische candles voor de modeltests: een 15m-pad uit rechte stukken, met losse candles die je kunt overschrijven (een lont, een
displacement), en daaruit 1u en 4u door samenvoegen. Zo horen de drie timeframes altijd bij elkaar. Deterministisch."""
from typing import Optional

import pandas as pd

START = pd.Timestamp("2026-10-01T00:00:00Z")
WICK = 0.05


def path(legs: list[tuple[int, float]], start_price: float = 100.0, wick: float = WICK) -> list[list[float]]:
    """legs: (aantal 15m-candles, eindkoers). Elke candle loopt rechtlijnig van de vorige slotkoers naar de volgende, met een lont van `wick`."""
    rows, price = [], start_price
    for n, target in legs:
        step = (target - price) / n
        for _ in range(n):
            o, c = price, price + step
            rows.append([o, max(o, c) + wick, min(o, c) - wick, c])
            price = c
    return rows


def frame(rows: list[list[float]], tf: str = "15min", start: pd.Timestamp = START) -> pd.DataFrame:
    ts = pd.date_range(start, periods=len(rows), freq=tf, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "timestamp", ts)
    df["volume"] = 1.0
    return df


def resample(b15: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Alleen volledige candles: een 1u-candle met minder dan vier 15m-candles valt weg (die is nog niet gesloten)."""
    per = {"1h": 4, "4h": 16}[rule]
    g = b15.set_index("timestamp").resample(rule.replace("h", "h"), origin="epoch")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    counts = g["open"].count()
    out = out[counts == per].reset_index()
    return out


def frames(rows: list[list[float]]) -> dict:
    b15 = frame(rows)
    return {"15m": b15, "1h": resample(b15, "1h"), "4h": resample(b15, "4h")}


def set_candle(rows: list[list[float]], i: int, o: float, h: float, l: float, c: float) -> None:
    rows[i] = [o, h, l, c]


def mirror_rows(rows: list[list[float]], around: float = 200.0) -> list[list[float]]:
    """Spiegelbeeld rond `around`: hoog en laag wisselen. Een long-scenario wordt zo een short-scenario."""
    return [[around - o, around - l, around - h, around - c] for o, h, l, c in rows]


def close_time(df: pd.DataFrame, i: int, tf: str) -> pd.Timestamp:
    return df["timestamp"].iloc[i] + pd.Timedelta(tf)


def cut_frames(fr: dict, now: pd.Timestamp) -> dict:
    """Alle timeframes zoals ze op `now` bekend waren: alleen candles die dan gesloten zijn."""
    delta = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "5m": pd.Timedelta(minutes=5)}
    return {k: v[v["timestamp"] + delta[k] <= now].reset_index(drop=True) for k, v in fr.items()}


def at(fr: dict, i15: int) -> pd.Timestamp:
    return close_time(fr["15m"], i15, "15min")


def find_index(df: pd.DataFrame, ts: Optional[pd.Timestamp]) -> Optional[int]:
    if ts is None:
        return None
    hit = df.index[df["timestamp"] == ts]
    return int(hit[0]) if len(hit) else None
