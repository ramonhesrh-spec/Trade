"""Toets van het recept achter de handgetekende trades (SUI en SOL): breuk van een structuur op 30m, daarna de terugkeer naar
het gebroken niveau, instap met een limietorder, stop net achter de terugkeer en een ladder van doelen met break-even na het
eerste doel.

Structuur is een van twee soorten, beide uit bevestigde zwaaipunten (3 candles links en rechts, dus pas bekend 3 candles na het punt):
  RANGE: de laatste twee zwaaipunten aan dezelfde kant liggen op bijna dezelfde prijs (horizontaal niveau)
  LINE:  de laatste twee zwaaipunten liggen op een schuine lijn (stijgende steun of dalende weerstand)
Breuk is een 30m-slot voorbij het niveau met een marge in ATR. Alles is vooraf vastgelegd, er is niets afgestemd op data.

Instapvormen: RETEST (limiet op het gebroken niveau, binnen RETEST_BARS candles) en MARKT (slot van de breukcandle, als
controle: voegt wachten op de terugkeer iets toe?). Uitgangen: een enkel doel op 2R, een ladder 1R/2R/3R, en een ladder op
de eerstvolgende zwaaipunten (liquiditeit) die minstens 1R verderop liggen. Bij een ladder gaat de stop naar de instap
zodra het eerste doel raakt. Stop eerst als een minuutcandle stop en doel tegelijk raakt."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay.lab import add_indicators, make_bars

BAR_MINUTES = 30
PIVOT_K = 3
LOOKBACK = 80             # candles waarbinnen de twee zwaaipunten moeten liggen
MIN_GAP = 6               # minimale afstand tussen die twee zwaaipunten
FLAT_ATR = 0.5            # RANGE: verschil tussen de twee niveaus, in ATR
SLOPE_ATR = 0.5           # LINE: minimale stijging of daling tussen de twee punten, in ATR
BREAK_ATR = 0.25          # een slot zo ver voorbij het niveau telt als breuk
RETEST_BARS = 8
STOP_ATR = 0.25
MIN_STOP_PCT = 0.2        # zelfde ondergrens als SMC_MIN_STOP_PCT
MAX_STOP_PCT = 2.0
MAX_HOLD_MIN = 12 * 60
LEVEL_LOOKBACK = 200      # zwaaipunten die als doel meetellen

LADDERS = {
    "enkel 2R": ((2.0,), (1.0,)),
    "ladder 1-2-3R": ((1.0, 2.0, 3.0), (1 / 3, 1 / 3, 1 / 3)),
    "niveaus": (None, None),
}
MODES = ("RETEST", "MARKT")
SHORT = "short"


def _pivots(bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(is_pivot_high, is_pivot_low). Het punt in candle i is pas bekend na candle i + PIVOT_K."""
    w = 2 * PIVOT_K + 1
    hi, lo = bars["high"], bars["low"]
    return ((hi.rolling(w, center=True).max() == hi).to_numpy(), (lo.rolling(w, center=True).min() == lo).to_numpy())


def find_breaks(bars: pd.DataFrame) -> pd.DataFrame:
    """Eerste breuk per paar zwaaipunten. Kolommen: bar (breukcandle), direction, kind, p1, p2, a (niveau op p1), slope
    (per candle, 0 bij RANGE), atr, vol_ratio, span, touches, with_trend."""
    b = add_indicators(bars).reset_index(drop=True)
    n = len(b)
    high, low, close = b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy()
    atr, vol = b["atr"].to_numpy(), b["volume"].to_numpy()
    ema_fast = b["close"].ewm(span=21, adjust=False).mean().to_numpy()
    ema_slow = b["close"].ewm(span=200, adjust=False).mean().to_numpy()
    p_high, p_low = _pivots(b)
    known_high: list[int] = []
    known_low: list[int] = []
    out = []
    for i in range(PIVOT_K, n):
        q = i - PIVOT_K
        if p_high[q]:
            known_high.append(q)
        if p_low[q]:
            known_low.append(q)
        if i < LOOKBACK or not np.isfinite(atr[i]):
            continue
        for direction, known, series in ((SHORT, known_low, low), ("long", known_high, high)):
            recent = [p for p in known if p >= i - LOOKBACK]
            if len(recent) < 2:
                continue
            p2 = recent[-1]
            earlier = [p for p in recent if p2 - p >= MIN_GAP]
            if not earlier:
                continue
            p1 = earlier[-1]
            diff = series[p2] - series[p1]
            sign = 1 if direction == SHORT else -1        # short breekt steun: lijn stijgt of ligt vlak
            if abs(diff) <= FLAT_ATR * atr[i]:
                kind, slope, a = "RANGE", 0.0, (series[p1] + series[p2]) / 2
            elif sign * diff >= SLOPE_ATR * atr[i]:
                kind, slope, a = "LINE", diff / (p2 - p1), series[p1]
            else:
                continue
            idx = np.arange(p2 + 1, i + 1)
            line = a + slope * (idx - p1)
            margin = BREAK_ATR * atr[idx]
            beyond = (sign * (line - close[idx]) > margin)       # short: slot onder de lijn
            if not (beyond[-1] and not beyond[:-1].any()):
                continue
            touch = sum(1 for p in recent if abs(series[p] - (a + slope * (p - p1))) <= FLAT_ATR * atr[i])
            ratio = vol[i] / np.mean(vol[i - 20:i]) if np.mean(vol[i - 20:i]) > 0 else np.nan
            out.append({"bar": i, "direction": direction, "kind": kind, "p1": p1, "p2": p2, "a": float(a), "slope": float(slope),
                        "atr": float(atr[i]), "vol_ratio": float(ratio), "span": p2 - p1, "touches": touch,
                        "with_trend": bool(ema_fast[i] < ema_slow[i]) if direction == SHORT else bool(ema_fast[i] > ema_slow[i])})
    return pd.DataFrame(out, columns=["bar", "direction", "kind", "p1", "p2", "a", "slope", "atr", "vol_ratio", "span", "touches", "with_trend"])


def level_at(ev, j: int) -> float:
    return ev.a + ev.slope * (j - ev.p1)


def ladder_targets(direction: str, entry: float, risk: float, name: str, pivot_levels: list[float]) -> Optional[tuple[tuple, tuple]]:
    """(doelen in R, fracties) of None als de variant hier niet kan (te weinig niveaus op minstens 1R)."""
    r_list, fractions = LADDERS[name]
    if r_list is not None:
        return r_list, fractions
    sign = 1 if direction == "long" else -1
    r = sorted({round(sign * (lv - entry) / risk, 3) for lv in pivot_levels if sign * (lv - entry) / risk >= 1.0})[:3]
    if len(r) < 2:
        return None
    return tuple(r), tuple(1 / len(r) for _ in r)


def simulate(direction: str, entry: float, stop: float, targets_r: tuple, fractions: tuple, be_after_first: bool,
             highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, cost_pct: float) -> tuple[float, float, str]:
    """Loopt de minuutcandles vanaf de instapminuut af. Geeft (bruto R, netto R, uitkomst). Stop eerst bij gelijktijdig raken.
    Uitkomst: 'stop', 'be', 'doel' (alles gepakt) of 'tijd' (rest tegen de slotkoers)."""
    risk = abs(entry - stop)
    sign = 1 if direction == "long" else -1
    cost_r = cost_pct / 100 * entry / risk
    targets = [entry + sign * risk * r for r in targets_r]
    live = float(stop)
    gross, taken, moved = 0.0, 0, False
    for k in range(len(highs)):
        stopped = lows[k] <= live if sign == 1 else highs[k] >= live
        if stopped:
            gross += (1 - sum(fractions[:taken])) * sign * (live - entry) / risk
            return gross, gross - cost_r, "be" if moved else "stop"
        while taken < len(targets) and (highs[k] >= targets[taken] if sign == 1 else lows[k] <= targets[taken]):
            gross += fractions[taken] * targets_r[taken]
            taken += 1
            if be_after_first and not moved:
                live, moved = entry, True
        if taken == len(targets):
            return gross, gross - cost_r, "doel"
    gross += (1 - sum(fractions[:taken])) * sign * (closes[-1] - entry) / risk
    return gross, gross - cost_r, "tijd"


class Minutes:
    """1m-candles als arrays voor snel zoeken op tijd."""

    def __init__(self, frame_1m: pd.DataFrame):
        self.ts = frame_1m["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
        self.high, self.low, self.close = (frame_1m[c].to_numpy(dtype=float) for c in ("high", "low", "close"))

    def index(self, ts: pd.Timestamp) -> int:
        return int(np.searchsorted(self.ts, np.datetime64(ts.tz_convert("UTC").tz_localize(None), "ns"), side="left"))

    def window(self, start: int) -> slice:
        return slice(start, start + MAX_HOLD_MIN)


def _plan_retest(ev, b: pd.DataFrame, m: Minutes) -> Optional[tuple[int, float, float, int]]:
    """(minuutindex van de instap, instap, stop, candle j) of None. Het limietniveau ligt vast als de candle begint, de stop
    gebruikt alleen candles vóór j: niets uit de candle waarin de order vult."""
    direction, i, n = ev.direction, ev.bar, len(b)
    sign = 1 if direction == "long" else -1
    for j in range(i + 1, min(i + 1 + RETEST_BARS, n)):
        prev_level = level_at(ev, j - 1)
        if -sign * (b.at[j - 1, "close"] - prev_level) > BREAK_ATR * ev.atr:        # terug voorbij het niveau: breuk mislukt
            return None
        level = level_at(ev, j)
        start = m.index(b.at[j, "timestamp"])
        end = m.index(b.at[j, "close_time"])
        seg_high, seg_low = m.high[start:end], m.low[start:end]
        reach = seg_high >= level if direction == SHORT else seg_low <= level
        if not reach.any():
            continue
        extreme = b["high"].iloc[i:j].max() if direction == SHORT else b["low"].iloc[i:j].min()
        stop = max(level, extreme) + STOP_ATR * ev.atr if direction == SHORT else min(level, extreme) - STOP_ATR * ev.atr
        return start + int(np.argmax(reach)), float(level), float(stop), j
    return None


def _plan_market(ev, b: pd.DataFrame, m: Minutes) -> Optional[tuple[int, float, float, int]]:
    i = ev.bar
    level = level_at(ev, i)
    close = float(b.at[i, "close"])
    if ev.direction == SHORT:
        stop = max(level, float(b.at[i, "high"])) + STOP_ATR * ev.atr
    else:
        stop = min(level, float(b.at[i, "low"])) - STOP_ATR * ev.atr
    return m.index(b.at[i, "close_time"]), close, float(stop), i


def run(frame_1m: pd.DataFrame, cost_pct: float = 0.06) -> pd.DataFrame:
    """Alle trades van één coin: één rij per breuk, instapvorm en uitgang."""
    bars = make_bars(frame_1m, BAR_MINUTES)
    events = find_breaks(bars)
    if events.empty:
        return pd.DataFrame()
    b = add_indicators(bars).reset_index(drop=True)
    m = Minutes(frame_1m)
    p_high, p_low = _pivots(b)
    rows = []
    for ev in events.itertuples():
        for mode in MODES:
            plan = (_plan_retest if mode == "RETEST" else _plan_market)(ev, b, m)
            if plan is None:
                continue
            k, entry, stop, j = plan
            risk = abs(entry - stop)
            risk_pct = risk / entry * 100
            if not (MIN_STOP_PCT <= risk_pct <= MAX_STOP_PCT) or k >= len(m.high):
                continue
            if (ev.direction == SHORT and entry >= stop) or (ev.direction == "long" and entry <= stop):
                continue
            known = (ev.bar - PIVOT_K)
            lo = max(0, known - LEVEL_LOOKBACK)
            mask = (p_low if ev.direction == SHORT else p_high)[lo:known + 1]
            series = b["low" if ev.direction == SHORT else "high"].to_numpy()[lo:known + 1]
            levels = [float(v) for v in series[mask]]
            w = m.window(k)
            for name in LADDERS:
                tg = ladder_targets(ev.direction, entry, risk, name, levels)
                if tg is None:
                    continue
                gross, net, outcome = simulate(ev.direction, entry, stop, tg[0], tg[1], name != "enkel 2R", m.high[w], m.low[w], m.close[w], cost_pct)
                rows.append({"at": pd.Timestamp(m.ts[k]).tz_localize("UTC"), "mode": mode, "ladder": name, "kind": ev.kind,
                             "direction": ev.direction, "risk_pct": risk_pct, "targets_r": tg[0], "r_gross": gross, "r_net": net,
                             "outcome": outcome, "vol_ratio": ev.vol_ratio, "span": ev.span, "touches": ev.touches,
                             "with_trend": ev.with_trend})
    return pd.DataFrame(rows)


def placebo(frame_1m: pd.DataFrame, trades: pd.DataFrame, cost_pct: float, seed: int = 0) -> pd.DataFrame:
    """Zelfde aantal trades, stopafstand, doelen en uitgang, maar op een willekeurig 30m-moment in hetzelfde uur, willekeurige kant."""
    if trades.empty:
        return trades
    rng = np.random.default_rng(seed)
    m = Minutes(frame_1m)
    stamps = pd.DatetimeIndex(m.ts[::BAR_MINUTES])
    by_hour = {h: np.flatnonzero(stamps.hour == h) * BAR_MINUTES for h in range(24)}
    rows = []
    for t in trades.itertuples():
        pool = by_hour[t.at.hour]
        if len(pool) == 0:
            continue
        k = int(pool[int(rng.integers(0, len(pool)))])
        if k + 1 >= len(m.close):
            continue
        direction = SHORT if rng.random() < 0.5 else "long"
        entry = float(m.close[k])
        risk = entry * t.risk_pct / 100
        stop = entry + risk if direction == SHORT else entry - risk
        r_list = t.targets_r
        fractions = tuple(1 / len(r_list) for _ in r_list)
        w = m.window(k + 1)
        _, net, _ = simulate(direction, entry, stop, r_list, fractions, t.ladder != "enkel 2R", m.high[w], m.low[w], m.close[w], cost_pct)
        rows.append({"mode": t.mode, "ladder": t.ladder, "kind": t.kind, "r_net": net})
    return pd.DataFrame(rows)


@dataclass
class Row:
    kind: str
    mode: str
    ladder: str
    n: int
    gross: float
    net: float
    train_net: Optional[float]
    test_net: Optional[float]
    n_train: int
    n_test: int
    t_days_test: Optional[float]
    placebo_net: float


def day_t(g: pd.DataFrame) -> Optional[float]:
    """t-waarde van het gemiddelde per dag: trades op dezelfde dag (en over coins heen) tellen zo niet als onafhankelijk."""
    daily = g.groupby(g["at"].dt.floor("D"))["r_net"].mean()
    if len(daily) < 5 or daily.std(ddof=1) == 0:
        return None
    return float(daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))))


def summarize(trades: pd.DataFrame, placebos: pd.DataFrame, cut: pd.Timestamp) -> list[Row]:
    out = []
    keys = [(k, mo, lad) for (k, mo, lad), _ in trades.groupby(["kind", "mode", "ladder"])]
    keys += [("ALLES", mo, lad) for (mo, lad), _ in trades.groupby(["mode", "ladder"])]
    for kind, mode, ladder in keys:
        g = trades[(trades["mode"] == mode) & (trades["ladder"] == ladder) & ((trades["kind"] == kind) | (kind == "ALLES"))]
        p = placebos[(placebos["mode"] == mode) & (placebos["ladder"] == ladder) & ((placebos["kind"] == kind) | (kind == "ALLES"))] if not placebos.empty else placebos
        tr, te = g[g["at"] < cut], g[g["at"] >= cut]
        out.append(Row(kind, mode, ladder, len(g), float(g["r_gross"].mean()), float(g["r_net"].mean()),
                       float(tr["r_net"].mean()) if len(tr) else None, float(te["r_net"].mean()) if len(te) else None,
                       len(tr), len(te), day_t(te), float(p["r_net"].mean()) if len(p) else 0.0))
    return out


def passes(r: Row, min_n: int = 30) -> bool:
    return (r.n_train >= min_n and r.n_test >= min_n and r.train_net is not None and r.test_net is not None
            and r.train_net > 0 and r.test_net > 0 and r.net > r.placebo_net)


FEATURES = {          # vooraf vastgelegde richting: True = hoger of 'ja' hoort beter te zijn
    "vol_ratio >= 1.5": lambda d: d["vol_ratio"] >= 1.5,
    "met trend (EMA21/200)": lambda d: d["with_trend"],
    "span >= 12 candles": lambda d: d["span"] >= 12,
    "touches >= 3": lambda d: d["touches"] >= 3,
}


def feature_table(trades: pd.DataFrame, cut: pd.Timestamp, mode: str = "RETEST", ladder: str = "ladder 1-2-3R") -> list[dict]:
    """Gemiddelde netto R met en zonder elk kenmerk, per helft. Een kenmerk telt alleen als het in beide helften dezelfde kant op wijst."""
    g = trades[(trades["mode"] == mode) & (trades["ladder"] == ladder)]
    rows = []
    for name, fn in FEATURES.items():
        flag = fn(g)
        row = {"kenmerk": name}
        for label, part in (("train", g["at"] < cut), ("test", g["at"] >= cut)):
            yes, no = g[part & flag], g[part & ~flag]
            row[label] = (len(yes), float(yes["r_net"].mean()) if len(yes) else None, len(no), float(no["r_net"].mean()) if len(no) else None)
        rows.append(row)
    return rows
