"""Range sweep: onze lezing van de strategie van Cos867 (docs/onderzoek/range-sweep/preregistratie.md). Een range met minstens drie aanrakingen
op beide randen, aanbod- en vraagzones (order blocks als vakken) op die randen, en twee manieren om terug door de range te handelen: de
zone-retest (de koers keert terug in de zone aan de rand) en de sweep (een prik voorbij de rand en een slot terug binnen). Altijd met een
limietorder en een stop voorbij de zone. Pure functies op candles: lab, misser-controle en live motor gebruiken dezelfde code.

Tijd: de timestamp van een candle is zijn openmoment; een candle is bekend op timestamp + timeframe. Een zwaaipunt op p is pas bekend op p + PIVOT_N."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app import smc_eval
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
# False (de pre-registratie): geen slot buiten de range tot nu. True: alleen tot de laatste aanraking van een rand; de uitstap daarna naar de zone is de setup, geen range-fout.
CONTAIN_UNTIL_LAST_TOUCH = False
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


def closed_only(df: pd.DataFrame, now: pd.Timestamp, tf: str) -> pd.DataFrame:
    """Alleen candles die op `now` gesloten zijn. De live motor moet elk frame hiermee voeden: range-, zone- en setupdetectie gaan uit van
    gesloten candles en zouden op een candle die nog vormt een range of CHoCH zien die bij het sluiten verdwijnt. Het lab heeft alleen gesloten candles."""
    return df[df["timestamp"] + TF_DELTA[tf] <= now].reset_index(drop=True)


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
    """Posities van de grootste groep binnen tol van één anker; bij gelijkstand de groep met het laatste punt, zoals rejection.py. Bij nog
    steeds gelijk wint het eerste anker. Eén matrix in plaats van een Python-lus per anker: range_series roept dit per candle aan."""
    n = len(values)
    if not n:
        return np.array([], dtype=int)
    member = np.abs(values[:, None] - values[None, :]) <= tol
    last = (member * np.arange(n)).max(axis=1)
    best = int(np.argmax(member.sum(axis=1) * (n + 1) + last))
    return np.flatnonzero(member[best])


def range_at(b: pd.DataFrame, i: int, tf: str, ph: np.ndarray, pl: np.ndarray, cols: Optional[tuple] = None) -> tuple[Optional[Range], str]:
    """cols: (high, low, close, atr, timestamp) als arrays, voor aanroepers die per candle lopen; zonder worden ze uit b gehaald."""
    high, low, close, atr_all, ts = cols if cols is not None else tuple(b[c].to_numpy() for c in ("high", "low", "close", "atr", "timestamp"))
    atr = float(atr_all[i])
    if not np.isfinite(atr) or atr <= 0:
        return None, "te weinig candles voor de ATR"
    lo_idx, hi_idx = max(0, i - RANGE_LOOKBACK[tf]), i - PIVOT_N
    if hi_idx <= lo_idx:
        return None, "te weinig candles"
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
    end = int(max(hc.max(), lc.max())) if CONTAIN_UNTIL_LAST_TOUCH else i
    inside = close[start:end + 1]
    if (inside > top + CONTAIN_ATR * atr).any() or (inside < bottom - CONTAIN_ATR * atr).any():
        return None, "slot buiten de range sinds de eerste aanraking"
    return Range(tf, pd.Timestamp(ts[i]) + TF_DELTA[tf], top, bottom, len(hc), len(lc), float(high[hc].max() - high[hc].min()),
                 float(low[lc].max() - low[lc].min()), pd.Timestamp(ts[start]), atr), ""


def range_series(bars: pd.DataFrame, tf: str) -> tuple[pd.DataFrame, list[Optional[Range]]]:
    b = add_indicators(bars).reset_index(drop=True)
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    ph, pl = tl._pivot_flags(-hi, PIVOT_N), tl._pivot_flags(lo, PIVOT_N)
    cols = (hi, lo, b["close"].to_numpy(float), b["atr"].to_numpy(float), b["timestamp"].to_numpy())
    return b, [range_at(b, i, tf, ph, pl, cols)[0] for i in range(len(b))]


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


def zone_displacement(z: Zone, closes: np.ndarray, closes15: Optional[np.ndarray] = None) -> float:
    """Grootste slot weg van de zone (in prijs) tot de bevestiging: de kaart van de nadering, bij choch15 ook de 15m-candles tot en met de CHoCH.
    Preregistratie: 'tot de bevestiging', niet tot het ontstaan van de zone. Gedeeld door lab en live."""
    c = closes if closes15 is None else np.r_[closes, closes15]
    return float((z.low - c.min()) if z.kind == "bear" else (c.max() - z.high))


def retests_before(z: Zone, b: pd.DataFrame, i: int) -> int:
    """Hoe vaak de koers tussen het ontstaan en candle i (exclusief) de zone binnenkwam: elke overgang van erbuiten naar erin telt één keer."""
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    count, inside = 0, False
    for m in range(z.known_idx + 1, i):
        now = (hi[m] >= z.low) if z.kind == "bear" else (lo[m] <= z.high)
        count += now and not inside
        inside = now
    return count


APPROACH_ATR = 1.0
EDGE_BAND = 0.25
SWEEP_MIN_ATR = 0.1
SWEEP_MAX_ATR = 1.5
RETURN_MAX_BARS = 6
SWEEP_COOLDOWN = 24
OB_SEARCH_15M = 8
CHOCH_PIVOT_N = 2
CHOCH_MAX_BARS = 24
HTF_LOOKBACK_4H = 180
EDGE_WEIGHT, OB_WEIGHT = 0.4, 0.6
AGE_MIN = {"30m": 48, "1h": 48, "2h": 36, "4h": 36}
# Vast, niet uit config: lab en live moeten met dezelfde ondergrens rekenen, ook als SMC_MIN_STOP_PCT op de VPS anders staat.
MIN_STOP_PCT = 0.4
STOP_BUFFER = {"zone_0": ("zone", 0.0), "zone_025": ("zone", 0.25), "zone_05": ("zone", 0.5), "wick_025": ("wick", 0.25)}
TESTED_STOPS = {"zone": ("zone_025", "zone_05"), "sweep": ("zone_025", "wick_025")}
DESCRIPTIVE_STOP = "zone_0"


@dataclass(frozen=True)
class Sweep:
    direction: str
    rng: Range
    start: int
    ret: int
    extreme: float
    atr: float


def _refusal(at, direction: str, reason: str, lo: float, hi: float, atr: float) -> dict:
    """lo en hi: het prijsgebied waar de weigering over ging (zone of rand), atr: de maat voor 'dichtbij' in diagnose."""
    return {"at": at, "direction": direction, "reason": reason, "span": (float(lo), float(hi)), "atr": float(atr)}


def _near(price: float, lo: float, hi: float, atr: float) -> bool:
    return lo - atr <= price <= hi + atr


def find_sweeps(b: pd.DataFrame, active: list[Optional[Range]]) -> tuple[list[Sweep], list[dict]]:
    """b: triggercandles met atr. Een prik voorbij een rand met een slot terug binnen in RETURN_MAX_BARS candles; dieper dan SWEEP_MAX_ATR is een uitbraak."""
    hi, lo, cl, atr = (b[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    ts = b["timestamp"]
    out, refused, used, last_start = [], [], set(), {}
    for j in range(len(b)):
        r = active[j]
        if r is None or not np.isfinite(atr[j]):
            continue
        for direction in (SHORT, LONG):
            beyond = hi[j] - r.high if direction == SHORT else r.low - lo[j]
            if beyond < SWEEP_MIN_ATR * atr[j]:
                continue
            key = (direction, r.first_at, r.high, r.low)
            # Na een sweep vormt de prik vaak een nieuwe range met bijna dezelfde randen: binnen SWEEP_COOLDOWN telt dezelfde kant één keer.
            edge = r.high if direction == SHORT else r.low
            skip = "al een sweep op deze rand" if key in used else ("cooldown na eerdere prik" if j - last_start.get(direction, -10**9) < SWEEP_COOLDOWN else "")
            if skip:
                refused.append(_refusal(ts.iloc[j], direction, skip, edge, edge, r.atr))
                continue
            used.add(key)
            last_start[direction] = j
            extreme, ret, reason = (hi[j] if direction == SHORT else lo[j]), None, "geen terugkeer binnen 6 candles"
            for k in range(j, min(len(b), j + RETURN_MAX_BARS)):
                extreme = max(extreme, hi[k]) if direction == SHORT else min(extreme, lo[k])
                if (extreme - r.high if direction == SHORT else r.low - extreme) > SWEEP_MAX_ATR * r.atr:
                    reason = "prik te diep, dit is een uitbraak"
                    break
                if (cl[k] < r.high) if direction == SHORT else (cl[k] > r.low):
                    ret = k
                    break
            if ret is None:
                refused.append(_refusal(ts.iloc[j], direction, reason, edge, edge, r.atr))
                continue
            out.append(Sweep(direction, r, j, ret, float(extreme), float(atr[ret])))
    return out, refused


def htf_context(b: pd.DataFrame, b4h: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(trend, hh, ll) per candle van b, alleen uit gesloten 4u-candles (beschikbaar op timestamp + 4u)."""
    trend = tl.htf_trend(b, b4h)
    b4 = b4h.reset_index(drop=True)
    frame = pd.DataFrame({"timestamp": b4["timestamp"] + pd.Timedelta(hours=4), "hh": b4["high"].rolling(HTF_LOOKBACK_4H).max(),
                          "ll": b4["low"].rolling(HTF_LOOKBACK_4H).min()})
    merged = pd.merge_asof(b[["timestamp"]].reset_index(drop=True), frame, on="timestamp")
    return trend, merged["hh"].to_numpy(float), merged["ll"].to_numpy(float)


def htf_ok(direction: str, trend: int, hh: float, ll: float, rng: Range) -> bool:
    """Short mag met de 4u-trend omlaag of met de range in de bovenste helft van de laatste 30 dagen; long gespiegeld."""
    want = -1 if direction == SHORT else 1
    if not (np.isfinite(hh) and np.isfinite(ll)) or hh <= ll:
        return trend == want
    pos = (rng.mid - ll) / (hh - ll)
    return trend == want or (pos >= 0.5 if direction == SHORT else pos <= 0.5)


def _htf_pos(rng: Range, hh: float, ll: float) -> Optional[float]:
    return float((rng.mid - ll) / (hh - ll)) if np.isfinite(hh) and np.isfinite(ll) and hh > ll else None


def _extreme_15m(b15: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp, direction: str) -> Optional[int]:
    pos = np.flatnonzero(((b15["timestamp"] >= t0) & (b15["timestamp"] < t1)).to_numpy())
    if not len(pos):
        return None
    col = b15["high" if direction == SHORT else "low"].to_numpy(float)[pos]
    return int(pos[np.argmax(col)] if direction == SHORT else pos[np.argmin(col)])


def order_block(b15: pd.DataFrame, k: int, direction: str) -> tuple[float, float, int, bool]:
    """(laag, hoog, index, echte_tegenkaars). Vanaf de uiterste 15m-candle k terug: de eerste groene (short) of rode (long) candle."""
    op, cl = b15["open"].to_numpy(float), b15["close"].to_numpy(float)
    for m in range(k, max(-1, k - OB_SEARCH_15M - 1), -1):
        if (cl[m] > op[m]) if direction == SHORT else (cl[m] < op[m]):
            return float(b15["low"].iloc[m]), float(b15["high"].iloc[m]), m, True
    return float(b15["low"].iloc[k]), float(b15["high"].iloc[k]), k, False


def choch_index(b15: pd.DataFrame, k: int, start: int, direction: str, extreme: float) -> Optional[int]:
    """Eerste 15m-candle vanaf start die sluit voorbij het laatste zwaaipunt (CHOCH_PIVOT_N) vóór k; een nieuw uiterste eerst maakt het ongeldig."""
    hi, lo, cl = (b15[c].to_numpy(float) for c in ("high", "low", "close"))
    flags = tl._pivot_flags(lo, CHOCH_PIVOT_N) if direction == SHORT else tl._pivot_flags(-hi, CHOCH_PIVOT_N)
    known = [p for p in np.flatnonzero(flags[:k]) if p + CHOCH_PIVOT_N < start]
    if not known:
        return None
    level = lo[known[-1]] if direction == SHORT else hi[known[-1]]
    for m in range(start, min(len(cl), start + CHOCH_MAX_BARS)):
        if (hi[m] > extreme) if direction == SHORT else (lo[m] < extreme):
            return None
        if (cl[m] < level) if direction == SHORT else (cl[m] > level):
            return m
    return None


def _ob_unmitigated(b15: pd.DataFrame, ob_idx: int, end: int, direction: str, ob_low: float, ob_high: float) -> bool:
    """Na het eerste slot voorbij het order block (short: onder het laag) raakte geen candle tot end (exclusief) het weer."""
    hi, lo, cl = (b15[c].to_numpy(float) for c in ("high", "low", "close"))
    left = False
    for m in range(ob_idx + 1, end):
        if not left:
            left = bool((cl[m] < ob_low) if direction == SHORT else (cl[m] > ob_high))
            continue
        if (hi[m] >= ob_low) if direction == SHORT else (lo[m] <= ob_high):
            return False
    return True


def legs_for(entry: str, direction: str, rng: Range, zone_price: float, ref_price: float) -> list[tuple[float, float]]:
    """[(gewicht, prijs)]. Een limiet aan de verkeerde kant van de koers is een marktorder: die vervalt, dit is een limietrecept."""
    edge = rng.high if direction == SHORT else rng.low
    raw = [(EDGE_WEIGHT, edge), (OB_WEIGHT, zone_price)] if entry == "split" else [(1.0, zone_price)]
    return [(w, p) for w, p in raw if (p > ref_price if direction == SHORT else p < ref_price)]


def _range_features(r: Range, start_at: pd.Timestamp, tf: str) -> dict:
    return {"touches_high": r.high_touches, "touches_low": r.low_touches, "width_atr": r.width / r.atr,
            "age_bars": int(round((start_at - r.first_at) / TF_DELTA[tf])), "edge_spread_atr": max(r.high_spread, r.low_spread) / r.atr}


def _setup(direction, family, tf, r, zone_low, zone_high, zone_at, sweep_at, extreme, return_at, placed_at, place_idx, ref_price, legs, atr_t,
           trend, hh, ll, ok, features) -> dict:
    return {"direction": direction, "family": family, "tf": tf, "range_high": r.high, "range_low": r.low, "range_first_at": r.first_at,
            "zone_low": zone_low, "zone_high": zone_high, "zone_at": zone_at, "sweep_at": sweep_at, "extreme": extreme, "return_at": return_at,
            "placed_at": placed_at, "place_idx15": place_idx, "ref_price": ref_price, "legs": legs, "atr_t": atr_t, "htf_trend": int(trend),
            "htf_pos": _htf_pos(r, hh, ll), "htf_ok": bool(ok), "features": features}


def _sweep_setups(frames, tf, entry, confirm, use_htf, ranges) -> tuple[list[dict], list[dict]]:
    b15 = frames["15m"]
    bt = add_indicators(frames[TRIGGER_TF[tf]]).reset_index(drop=True)
    b_tf, rlist = ranges
    sweeps, refused = find_sweeps(bt, active_for(bt, b_tf, rlist, tf))
    trend, hh, ll = htf_context(bt, frames["4h"])
    ts, ts15, clt, cl15 = bt["timestamp"], b15["timestamp"], bt["close"].to_numpy(float), b15["close"].to_numpy(float)
    dt = TF_DELTA[TRIGGER_TF[tf]]
    setups = []
    for sw in sweeps:
        r, d, at = sw.rng, sw.direction, ts.iloc[sw.ret] + dt
        ok = htf_ok(d, int(trend[sw.ret]), float(hh[sw.ret]), float(ll[sw.ret]), r)
        edge = r.high if d == SHORT else r.low
        if use_htf and not ok:
            refused.append(_refusal(at, d, "HTF-filter: tegen de 4u-trend en aan de verkeerde kant van de grotere range", edge, edge, sw.atr))
            continue
        k = _extreme_15m(b15, ts.iloc[sw.start], at, d)
        if k is None:
            refused.append(_refusal(at, d, "geen 15m-candles bij de prik", edge, edge, sw.atr))
            continue
        ob_low, ob_high, ob_idx, ob_real = order_block(b15, k, d)
        start15 = int(ts15.searchsorted(at))
        span = (min(edge, ob_low), max(edge, ob_high))
        if confirm == "choch15":
            m = choch_index(b15, k, start15, d, sw.extreme)
            if m is None:
                refused.append(_refusal(at, d, "geen CHoCH op 15m binnen 6 uur", *span, sw.atr))
                continue
            placed_at, place_idx, ref_price = ts15.iloc[m] + TF_DELTA["15m"], m + 1, float(cl15[m])
        else:
            placed_at, place_idx, ref_price = at, start15, float(clt[sw.ret])
        legs = legs_for(entry, d, r, (ob_low + ob_high) / 2, ref_price)
        if not legs:
            refused.append(_refusal(placed_at, d, "geen geldige limiet: het order block ligt aan de verkeerde kant van de koers", *span, sw.atr))
            continue
        features = {**_range_features(r, ts.iloc[sw.start], tf), "ob_opposite": ob_real, "displacement_atr": abs(sw.extreme - ref_price) / sw.atr,
                    "zone_fresh": _ob_unmitigated(b15, ob_idx, place_idx, d, ob_low, ob_high), "zone_atr": (ob_high - ob_low) / sw.atr}
        setups.append(_setup(d, "sweep", tf, r, ob_low, ob_high, ts15.iloc[ob_idx], ts.iloc[sw.start], sw.extreme, at, placed_at, place_idx,
                             ref_price, legs, sw.atr, trend[sw.ret], hh[sw.ret], ll[sw.ret], ok, features))
    return setups, refused


def _zone_setups(frames, tf, entry, confirm, use_htf, ranges) -> tuple[list[dict], list[dict]]:
    """Per zone de eerste nadering waarop alle voorwaarden kloppen. Een nadering zonder CHoCH of zonder geldige limiet is geen setup maar sluit de
    zone niet af: pas als de koers de zone weer verlaten heeft telt de volgende aanraking als een nieuwe nadering (in_visit)."""
    b15 = frames["15m"]
    b, rlist = ranges
    hi, lo, cl, atr = (b[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    ts, ts15, cl15 = b["timestamp"], b15["timestamp"], b15["close"].to_numpy(float)
    trend, hh, ll = htf_context(b, frames["4h"])
    setups, refused = [], []
    for z in find_zones(b):
        d = SHORT if z.kind == "bear" else LONG
        inner = z.inner(d)
        in_visit, done_at = False, None
        for i in range(z.known_idx + 1, min(len(b), z.known_idx + 1 + ZONE_MAX_AGE)):
            if not zone_active(z, i):
                break
            near = (inner - APPROACH_ATR * atr[i] <= cl[i] < inner and hi[i] < inner) if d == SHORT else (inner < cl[i] <= inner + APPROACH_ATR * atr[i] and lo[i] > inner)
            touched = (hi[i] >= inner) if d == SHORT else (lo[i] <= inner)
            if not (near if confirm == "slot" else touched):
                in_visit = False
                continue
            if in_visit:
                continue
            at, r = ts.iloc[i] + TF_DELTA[tf], rlist[i]
            if done_at is not None:
                refused.append(_refusal(at, d, f"zone had al een setup op {done_at:%Y-%m-%d %H:%M}", z.low, z.high, atr[i]))
                in_visit = True
                continue
            if r is None:
                refused.append(_refusal(at, d, f"geen range op {tf} bij de nadering van de zone", z.low, z.high, atr[i]))
                continue
            in_band = (inner >= r.high - EDGE_BAND * r.width) if d == SHORT else (inner <= r.low + EDGE_BAND * r.width)
            if not in_band:
                refused.append(_refusal(at, d, "zone ligt niet aan de rand van de range", z.low, z.high, atr[i]))
                continue
            ok = htf_ok(d, int(trend[i]), float(hh[i]), float(ll[i]), r)
            if use_htf and not ok:
                refused.append(_refusal(at, d, "HTF-filter: tegen de 4u-trend en aan de verkeerde kant van de grotere range", z.low, z.high, atr[i]))
                continue
            start15 = int(ts15.searchsorted(at))
            if confirm == "choch15":
                k = _extreme_15m(b15, ts.iloc[i], at, d)
                extreme = float(hi[i] if d == SHORT else lo[i])
                m = None if k is None else choch_index(b15, k, start15, d, extreme)
                if m is None:
                    refused.append(_refusal(at, d, "geen CHoCH op 15m binnen 6 uur", z.low, z.high, atr[i]))
                    in_visit = True
                    continue
                placed_at, place_idx, ref_price = ts15.iloc[m] + TF_DELTA["15m"], m + 1, float(cl15[m])
            else:
                placed_at, place_idx, ref_price = at, start15, float(cl[i])
            legs = legs_for(entry, d, r, inner, ref_price)
            if not legs:
                refused.append(_refusal(placed_at, d, "geen geldige limiet: de zone ligt aan de verkeerde kant van de koers", z.low, z.high, atr[i]))
                in_visit = True
                continue
            away = zone_displacement(z, cl[z.ob_idx + 1:i + 1], cl15[start15:m + 1] if confirm == "choch15" else None)
            features = {**_range_features(r, ts.iloc[i], tf), "ob_opposite": z.disp_bars <= 2, "displacement_atr": float(away / atr[z.known_idx]),
                        "zone_fresh": retests_before(z, b, i) <= 1, "zone_atr": (z.high - z.low) / atr[i]}
            setups.append(_setup(d, "zone", tf, r, z.low, z.high, ts.iloc[z.ob_idx], None, None, None, placed_at, place_idx, ref_price, legs,
                                 float(atr[i]), trend[i], hh[i], ll[i], ok, features))
            done_at, in_visit = placed_at, True
    return setups, refused


def find_setups(frames: dict, tf: str, family: str, entry: str, confirm: str, use_htf: bool,
                ranges: Optional[tuple[pd.DataFrame, list]] = None) -> tuple[list[dict], list[dict]]:
    """frames: uitvoer van build_frames, met uitsluitend gesloten candles (live: elk frame door closed_only). ranges: uitvoer van range_series voor tf
    (het lab rekent die één keer per coin)."""
    ranges = ranges if ranges is not None else range_series(frames[tf], tf)
    if family == "zone":
        return _zone_setups(frames, tf, entry, confirm, use_htf, ranges)
    return _sweep_setups(frames, tf, entry, confirm, use_htf, ranges)


def raw_stops(setup: dict) -> dict[str, float]:
    """Ruwe stops: buitenkant van de zone (of het uiterste van de sweep) plus een buffer in ATR. Bij de zone-retest is er geen wick."""
    short = setup["direction"] == SHORT
    side, far = (1, max) if short else (-1, min)
    # Bij split ligt het randbeen op de rand van de range, en die kan voorbij de zone liggen: dan zou het been nooit vullen vóór de stop.
    legs = [p for _, p in setup["legs"]]
    outer = far([setup["zone_high"] if short else setup["zone_low"], *legs])
    out = {}
    for name, (base, buf) in STOP_BUFFER.items():
        ref = outer if base == "zone" else setup.get("extreme")
        if ref is not None:
            out[name] = far(ref, *legs) + side * buf * setup["atr_t"]
    return out


def final_stop(setup: dict, name: str) -> float:
    legs = setup["legs"]
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    return smc_eval.floor_stop(setup["direction"], planned, raw_stops(setup)[name], min_pct=MIN_STOP_PCT)


def diagnose(frames: dict, at: pd.Timestamp, direction: str, tf: str, family: str, entry: str, confirm: str, use_htf: bool,
             window: pd.Timedelta = pd.Timedelta(hours=12), ranges: Optional[tuple[pd.DataFrame, list]] = None, price: Optional[float] = None) -> dict:
    """Voor de misser-controle: zag deze variant een setup rond `at`, en zo niet, welke regel weigerde. Volgorde: setup, weigering, en anders
    waarom er geen range of geen zone was op het laatste slot vóór `at`. price: de instapprijs van de trader; met price telt alleen een setup of
    weigering waarvan zone, rand of been binnen 1 ATR van die prijs ligt."""
    setups, refused = find_setups(frames, tf, family, entry, confirm, use_htf, ranges)
    def setup_near(s):
        prices = [p for _, p in s["legs"]] + [s["zone_low"], s["zone_high"]]
        return price is None or _near(price, min(prices), max(prices), s["atr_t"])

    near = [s for s in setups if s["direction"] == direction and abs(s["placed_at"] - at) <= window and setup_near(s)]
    if near:
        return {"seen": True, "reason": "", "setup": min(near, key=lambda s: abs(s["placed_at"] - at))}
    ref = [r for r in refused if r["direction"] == direction and abs(r["at"] - at) <= window and (price is None or _near(price, *r["span"], r["atr"]))]
    if ref:
        return {"seen": False, "reason": min(ref, key=lambda r: abs(r["at"] - at))["reason"], "setup": None}
    b = add_indicators(frames[tf]).reset_index(drop=True)
    idx = int(((b["timestamp"] + TF_DELTA[tf]) <= at).sum()) - 1
    if idx < 0:
        return {"seen": False, "reason": f"geen range op {tf}: te weinig candles", "setup": None}
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    rng, why = range_at(b, idx, tf, tl._pivot_flags(-hi, PIVOT_N), tl._pivot_flags(lo, PIVOT_N))
    if rng is None:
        return {"seen": False, "reason": f"geen range op {tf}: {why}", "setup": None}
    if family == "zone":
        kind = "bear" if direction == SHORT else "bull"
        if not any(z.kind == kind and zone_active(z, idx) for z in find_zones(b)):
            return {"seen": False, "reason": f"range op {tf}, maar geen actieve {'aanbod' if kind == 'bear' else 'vraag'}zone", "setup": None}
        return {"seen": False, "reason": f"range en zone op {tf}, maar de koers kwam niet binnen {APPROACH_ATR} ATR van de zone", "setup": None}
    return {"seen": False, "reason": f"range op {tf} gevonden, maar geen prik voorbij de rand van minstens {SWEEP_MIN_ATR} ATR", "setup": None}
