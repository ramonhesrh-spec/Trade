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


def make_smc_prone_1m(days: int = 12, start: str = "2026-01-01", seed: int = 5, start_price: float = 100.0,
                       spike_prob: float = 0.002, spike_scale: float = 0.006, wick_scale: float = 0.0006) -> pd.DataFrame:
    """1m-data met trend-segmenten en uitschietende wicks, zodat structuurbreuken,
    sweeps en fair-value-gaps op 30m/15m voorkomen. Deterministisch."""
    rng = np.random.default_rng(seed)
    n = days * 1440
    drift = np.zeros(n)
    i = 0
    while i < n:
        length = int(rng.integers(90, 420))
        drift[i:i + length] = rng.choice([-1, 1]) * rng.uniform(0.0002, 0.0007)
        i += length
    noise = rng.normal(0, 0.0009, n)
    spikes = (rng.random(n) < spike_prob) * rng.normal(0, spike_scale, n)
    closes = start_price * np.exp(np.cumsum(drift + noise + spikes))
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    opens = np.concatenate([[start_price], closes[:-1]])
    wick = np.abs(rng.normal(0, wick_scale, n)) + np.abs(spikes) * 0.5
    highs = np.maximum(opens, closes) * (1 + wick)
    lows = np.minimum(opens, closes) * (1 - wick)
    volume = rng.lognormal(4, 0.4, n)
    return pd.DataFrame({"timestamp": ts, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volume})
