"""Range sweep: onze lezing van de strategie van Cos867 (docs/onderzoek/range-sweep/preregistratie.md). Een range met minstens drie aanrakingen
op beide randen, aanbod- en vraagzones (order blocks als vakken) op die randen, en twee manieren om terug door de range te handelen: de
zone-retest (de koers keert terug in de zone aan de rand) en de sweep (een prik voorbij de rand en een slot terug binnen). Altijd met een
limietorder en een stop voorbij de zone. Pure functies op candles: lab, misser-controle en live motor gebruiken dezelfde code.

Tijd: de timestamp van een candle is zijn openmoment; een candle is bekend op timestamp + timeframe. Een zwaaipunt op p is pas bekend op p + PIVOT_N."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import trendlab as tl
from app.replay.lab import add_indicators

TFS = ("30m", "1h", "2h", "4h")
TF_DELTA = {"15m": pd.Timedelta(minutes=15), "30m": pd.Timedelta(minutes=30), "1h": pd.Timedelta(hours=1),
            "2h": pd.Timedelta(hours=2), "4h": pd.Timedelta(hours=4)}
# "1h/15m confirmation": de sweep en het slot terug binnen op 1u, behalve op 30m, waar 1u grover is dan de range zelf.
TRIGGER_TF = {"30m": "30m", "1h": "1h", "2h": "1h", "4h": "1h"}
PIVOT_N = 3
TOUCHES = 3
CLUSTER_ATR = 0.5
RANGE_LOOKBACK = {"30m": 120, "1h": 120, "2h": 90, "4h": 90}
RANGE_MIN_ATR = 3.0
RANGE_MAX_ATR = 15.0
CONTAIN_ATR = 0.25
DISP_BARS = 5
DISP_ATR = 1.0
ZONE_MAX_AGE = 200
ZONE_OVERLAP = 0.5
SHORT, LONG = "short", "long"
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Candles van tf uit fijnere candles, alleen volle vakken op UTC-grenzen (zoals Binance 30m en 2u opent). Een half vak aan het eind valt weg,
    anders verschijnt live een candle die het lab nooit zag."""
    delta = TF_DELTA[tf]
    if len(bars) < 2:
        return bars.iloc[:0].reset_index(drop=True)
    step = bars["timestamp"].diff().dropna().min()
    g = bars.set_index("timestamp").resample(delta, origin="epoch", label="left", closed="left")
    out, count = g.agg(_AGG), g["close"].count()
    return out[count == int(delta / step)].dropna().reset_index()


def build_frames(b15: pd.DataFrame, b1h: pd.DataFrame, b4h: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"15m": b15.reset_index(drop=True), "30m": resample(b15, "30m"), "1h": b1h.reset_index(drop=True), "2h": resample(b1h, "2h"),
            "4h": b4h.reset_index(drop=True)}


@dataclass(frozen=True)
class Range:
    tf: str
    known_at: pd.Timestamp
    high: float
    low: float
    high_touches: int
    low_touches: int
    high_spread: float
    low_spread: float
    first_at: pd.Timestamp
    atr: float

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

    @property
    def width(self) -> float:
        return self.high - self.low


def _best_cluster(values: np.ndarray, tol: float) -> np.ndarray:
    """Posities van de grootste groep binnen tol van één anker; bij gelijkstand de groep met het laatste punt, zoals rejection.py."""
    best = np.array([], dtype=int)
    for a in range(len(values)):
        group = np.flatnonzero(np.abs(values - values[a]) <= tol)
        if len(group) > len(best) or (len(group) == len(best) and len(group) and group[-1] > best[-1]):
            best = group
    return best


def range_at(b: pd.DataFrame, i: int, tf: str, ph: np.ndarray, pl: np.ndarray) -> tuple[Optional[Range], str]:
    atr = float(b["atr"].iloc[i])
    if not np.isfinite(atr) or atr <= 0:
        return None, "te weinig candles voor de ATR"
    lo_idx, hi_idx = max(0, i - RANGE_LOOKBACK[tf]), i - PIVOT_N
    if hi_idx <= lo_idx:
        return None, "te weinig candles"
    high, low, close = b["high"].to_numpy(float), b["low"].to_numpy(float), b["close"].to_numpy(float)
    highs = np.flatnonzero(ph[lo_idx:hi_idx + 1]) + lo_idx
    lows = np.flatnonzero(pl[lo_idx:hi_idx + 1]) + lo_idx
    hc = highs[_best_cluster(high[highs], CLUSTER_ATR * atr)] if len(highs) else highs
    lc = lows[_best_cluster(low[lows], CLUSTER_ATR * atr)] if len(lows) else lows
    if len(hc) < TOUCHES or len(lc) < TOUCHES:
        return None, f"te weinig aanrakingen (boven {len(hc)}, onder {len(lc)}, nodig {TOUCHES})"
    top, bottom = float(high[hc].max()), float(low[lc].min())
    if top - bottom < RANGE_MIN_ATR * atr:
        return None, "range te smal"
    if top - bottom > RANGE_MAX_ATR * atr:
        return None, "range te breed"
    start = int(min(hc.min(), lc.min()))
    inside = close[start:i + 1]
    if (inside > top + CONTAIN_ATR * atr).any() or (inside < bottom - CONTAIN_ATR * atr).any():
        return None, "slot buiten de range sinds de eerste aanraking"
    ts = b["timestamp"]
    return Range(tf, ts.iloc[i] + TF_DELTA[tf], top, bottom, len(hc), len(lc), float(high[hc].max() - high[hc].min()),
                 float(low[lc].max() - low[lc].min()), ts.iloc[start], atr), ""


def range_series(bars: pd.DataFrame, tf: str) -> tuple[pd.DataFrame, list[Optional[Range]]]:
    b = add_indicators(bars).reset_index(drop=True)
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    ph, pl = tl._pivot_flags(-hi, PIVOT_N), tl._pivot_flags(lo, PIVOT_N)
    return b, [range_at(b, i, tf, ph, pl)[0] for i in range(len(b))]


def active_for(b_trig: pd.DataFrame, b_tf: pd.DataFrame, ranges: list[Optional[Range]], tf: str) -> list[Optional[Range]]:
    """Per candle van b_trig de range van de laatste candle van tf die gesloten was bij het openen van die candle."""
    known = (b_tf["timestamp"] + TF_DELTA[tf]).to_numpy()
    pos = np.searchsorted(known, b_trig["timestamp"].to_numpy(), side="right") - 1
    return [ranges[p] if p >= 0 else None for p in pos]


@dataclass(frozen=True)
class Zone:
    kind: str
    low: float
    high: float
    ob_idx: int
    known_idx: int
    broken_idx: Optional[int]
    disp_bars: int
    disp_atr: float

    @property
    def outer(self) -> float:
        return self.high if self.kind == "bear" else self.low

    def inner(self, direction: str) -> float:
        return self.low if self.kind == "bear" else self.high


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Deel van het kleinste vak dat in het andere ligt."""
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return max(0.0, inter) / max(1e-12, min(a[1] - a[0], b[1] - b[0]))


def zone_active(z: Zone, i: int) -> bool:
    return z.known_idx < i <= z.known_idx + ZONE_MAX_AGE and (z.broken_idx is None or i < z.broken_idx)


def find_zones(b: pd.DataFrame) -> list[Zone]:
    """Aanbodzone: de laatste groene candle k (hooguit DISP_BARS vóór m) waarna een slot op m minstens DISP_ATR ATR onder het laag van k komt.
    Zone = laag tot hoog van k, bekend op m. Vraagzone gespiegeld. broken_idx is de eerste candle na m die voorbij de buitenkant sluit; consumenten
    vergelijken hem alleen met hun eigen index, zodat er niets uit de toekomst lekt. Een zone die voor meer dan ZONE_OVERLAP overlapt met een
    nog actieve zone van dezelfde soort telt niet: de oudere is dezelfde liquiditeit."""
    op, hi, lo, cl, atr = (b[c].to_numpy(float) for c in ("open", "high", "low", "close", "atr"))
    n, out, seen = len(b), [], set()
    for m in range(1, n):
        if not np.isfinite(atr[m]) or atr[m] <= 0:
            continue
        for kind in ("bear", "bull"):
            k = next((k for k in range(m - 1, max(-1, m - DISP_BARS - 1), -1) if ((cl[k] > op[k]) if kind == "bear" else (cl[k] < op[k]))), None)
            if k is None or (kind, k) in seen:
                continue
            moved = (lo[k] - cl[m]) if kind == "bear" else (cl[m] - hi[k])
            if moved < DISP_ATR * atr[m]:
                continue
            seen.add((kind, k))
            if any(z.kind == kind and zone_active(z, m) and _overlap((z.low, z.high), (lo[k], hi[k])) > ZONE_OVERLAP for z in out):
                continue
            after = cl[m + 1:min(n, m + 1 + ZONE_MAX_AGE)]
            beyond = np.flatnonzero(after > hi[k]) if kind == "bear" else np.flatnonzero(after < lo[k])
            window = cl[k + 1:m + 1]
            disp = ((lo[k] - window.min()) if kind == "bear" else (window.max() - hi[k])) / atr[m]
            out.append(Zone(kind, float(lo[k]), float(hi[k]), k, m, int(m + 1 + beyond[0]) if len(beyond) else None, m - k, float(disp)))
    return out


def retests_before(z: Zone, b: pd.DataFrame, i: int) -> int:
    """Hoe vaak de koers tussen het ontstaan en candle i (exclusief) de zone binnenkwam: elke overgang van erbuiten naar erin telt één keer."""
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    count, inside = 0, False
    for m in range(z.known_idx + 1, i):
        now = (hi[m] >= z.low) if z.kind == "bear" else (lo[m] <= z.high)
        count += now and not inside
        inside = now
    return count
