"""M3 (aanvulling preregistratie 2026-11-03 avond, B-2026-11-03-12): willekeurig instappen als vergelijking. Per afgeronde modeltrade N
willekeurige 5m-candles tussen 7 dagen en 1 uur vóór de vulling, vast zaad uit soort en id; instap op de open, stop en doel op hetzelfde
percentage als het plan, dezelfde coin en richting, uitkomst met model.outcome. Zuiver; scripts/model_placebo.py haalt de candles en slaat op."""
import random
import zlib
from typing import Optional

import pandas as pd

from app import model

N = 10
WINDOW = pd.Timedelta(days=7)
GAP = pd.Timedelta(hours=1)
STEP = pd.Timedelta(minutes=5)


def sample_times(key: str, start: pd.Timestamp, n: int = N) -> list[pd.Timestamp]:
    """n verschillende 5m-slots in [start − WINDOW, start − GAP], altijd dezelfde voor dezelfde sleutel."""
    lo, hi = (start - WINDOW).ceil("5min"), (start - GAP).floor("5min")
    slots = int((hi - lo) / STEP) + 1
    if slots <= 0:
        return []
    rng = random.Random(zlib.crc32(key.encode()))
    return sorted(lo + i * STEP for i in rng.sample(range(slots), min(n, slots)))


def placebo_rs(key: str, direction: str, entry: float, stop: float, take: Optional[float], start: pd.Timestamp,
               candles: pd.DataFrame, n: int = N) -> list[float]:
    """Bruto R van de willekeurige instappen. Zonder doel, zonder candle op het slot, 'tijd' of zonder uitkomst: valt weg."""
    if take is None or entry == stop or not len(candles):
        return []
    stop_pct, take_pct = (stop - entry) / entry, (take - entry) / entry
    by_ts = candles.set_index("timestamp")
    out = []
    for t in sample_times(key, start, n):
        if t not in by_ts.index:
            continue
        e = float(by_ts.loc[t, "open"])
        # De instapcandle zelf telt mee voor stop en doel: model.outcome kijkt naar candles strikt na het vulmoment.
        res = model.outcome(direction, e, e * (1 + stop_pct), e * (1 + take_pct), t - pd.Timedelta(seconds=1), candles)
        if res["state"] in ("take_profit", "stop_loss"):
            out.append(float(res["r"]))
    return out
