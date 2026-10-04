"""Deterministische nepdata voor de meetraam-tests."""
import numpy as np
import pandas as pd


def make_base(days: int = 40, start: str = "2026-01-01", seed: int = 7, start_price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = days * 96
    ts = pd.date_range(start, periods=n, freq="15min", tz="UTC")
    closes = start_price * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    opens = np.concatenate([[start_price], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.0007, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.0007, n)))
    volume = rng.lognormal(5, 0.3, n)
    return pd.DataFrame({"timestamp": ts, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volume})
