"""Marktfase uit een volumeprofiel (balans of onbalans, uit de veilingtheorie). Zuiver: geen netwerk, geen database.
De regels liggen vooraf vast en worden niet op data afgesteld; dit beschrijft alleen."""
from typing import Optional

import pandas as pd

BINS = 50
VALUE_PCT = 0.68
PROFILE_CANDLES = 72
STATE_CANDLES = 4
STATE_MIN_OUTSIDE = 3
MIN_CANDLES = 10
HOUR = pd.Timedelta(hours=1)


def parse_time(iso: str) -> pd.Timestamp:
    ts = pd.Timestamp(iso)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def closed_before(candles: pd.DataFrame, at: pd.Timestamp) -> pd.DataFrame:
    """Alleen 1u-candles die op `at` al gesloten waren; een candle die nog vormt telt nooit mee."""
    return candles[candles["timestamp"] + HOUR <= at]


def value_area(candles: pd.DataFrame, bins: int = BINS, pct: float = VALUE_PCT) -> Optional[dict]:
    if candles is None or len(candles) < MIN_CANDLES:
        return None
    lo, hi = float(candles["low"].min()), float(candles["high"].max())
    if hi <= lo:
        return None
    width = (hi - lo) / bins
    vols = [0.0] * bins
    for low, high, vol in zip(candles["low"], candles["high"], candles["volume"]):
        low, high, vol = float(low), float(high), float(vol)
        if vol <= 0:
            continue
        first = min(int((low - lo) / width), bins - 1)
        if high <= low:
            vols[first] += vol
            continue
        last = min(int((high - lo) / width), bins - 1)
        for i in range(first, last + 1):
            overlap = min(high, lo + (i + 1) * width) - max(low, lo + i * width)
            if overlap > 0:
                vols[i] += vol * overlap / (high - low)
    total = sum(vols)
    if total <= 0:
        return None
    poc = max(range(bins), key=lambda i: (vols[i], -i))
    a = b = poc
    included = vols[poc]
    while included < pct * total and (a > 0 or b < bins - 1):
        up = vols[b + 1] if b < bins - 1 else -1.0
        down = vols[a - 1] if a > 0 else -1.0
        if up >= down:
            b += 1
            included += vols[b]
        else:
            a -= 1
            included += vols[a]
    return {"val": lo + a * width, "poc": lo + (poc + 0.5) * width, "vah": lo + (b + 1) * width, "total_volume": total}


def classify(candles_1h_before: pd.DataFrame, direction: str) -> Optional[dict]:
    """Fase op het signaalmoment uit alleen eerder gesloten 1u-candles (nieuwste laatst)."""
    window = candles_1h_before.tail(PROFILE_CANDLES)
    va = value_area(window)
    if va is None:
        return None
    closes = [float(c) for c in window["close"].tail(STATE_CANDLES)]
    above = sum(c > va["vah"] for c in closes)
    below = sum(c < va["val"] for c in closes)
    if above >= STATE_MIN_OUTSIDE:
        state = "onbalans_op"
    elif below >= STATE_MIN_OUTSIDE:
        state = "onbalans_neer"
    else:
        state = "balans"
    last = closes[-1]
    if last < va["val"] or last > va["vah"]:
        positie = "buiten"
    else:
        f = (last - va["val"]) / (va["vah"] - va["val"])
        positie = "premium" if f >= 2 / 3 else "discount" if f <= 1 / 3 else "midden"
    if state == "balans":
        relatie = None
    else:
        met = (direction == "long" and state == "onbalans_op") or (direction == "short" and state == "onbalans_neer")
        relatie = "met" if met else "tegen"
    return {"state": state, "positie": positie, "relatie": relatie, "val": va["val"], "poc": va["poc"],
            "vah": va["vah"], "last_close": last}
