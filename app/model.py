"""HesPulse-model: het hoofdmodel uit hoofdstuk 25 van het boek, in vaste regels (docs/onderzoek/hespulse-model/preregistratie.md, bindend).

Context op 4u (bias uit de laatste breuk, dealing range met evenwicht), pools op 1u (onaangeraakte swing lows in discount), sweep, shift met
displacement en de fair value gap op 15m, limiet op de bovenkant van de zone (FVG, of de overlap met het order block), stop voorbij het uiterste
van de sweep, doel de dichtste van de rand van de range en een naakte dag- of week-POC. Geen R:R-eis en geen tijdfilter (besluiten CEO
2026-11-02). Short is long op gespiegelde candles (`_frame(mirror=True)`: hoog en laag wisselen van teken), zodat het spiegelbeeld per definitie
klopt en er maar één regelset is.

Zuiver: geen database of netwerk. Elk gegeven draagt het moment waarop het herkenbaar was (het sluiten van de laatste candle die het nodig had).
Een scenario hangt alleen af van candles vanaf zijn range; `scenarios()` op de candles tot `now` geeft daarom voor elk eerder moment dezelfde
stappen als op meer data (tests/hespulse_model/test_model.py, prefix-toets). De live motor (app/model_live.py) rekent zo elke 15 minuten opnieuw
en bewaart alleen wat nieuw is; scripts/model_kaarten.py gebruikt dezelfde code.

De oude bouwstenen blijven ongemoeid (golden tests): de pivotregel komt uit trendlab, de rest staat hier opnieuw met de aanpassingen uit de
inventaris (§7): pools met "onaangeraakt" en gelijke lows als één pool, een sweep op een poolniveau, een order block zonder overlapfilter, en FVG's
met index en "ongevuld"."""
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs
from app.replay.lab import add_indicators
from app.replay.trendlab import _pivot_flags

TRADE_TYPE = "hespulse_model"
LABEL = "HesPulse-model"
KEY_PREFIX = "model"

TF = {"1d": pd.Timedelta(days=1), "12h": pd.Timedelta(hours=12), "4h": pd.Timedelta(hours=4), "1h": pd.Timedelta(hours=1), "15m": pd.Timedelta(minutes=15), "5m": pd.Timedelta(minutes=5)}

# Alles vooraf vastgelegd in de preregistratie (§4); nooit afstellen. Een ander getal vraagt een gedateerd aanvullend besluit.
K_4H, K_1H, K_15M = 2, 3, 2                 # 4.1
BIAS_MAX_BARS = 60                          # 4.3: 60 candles van 4u (10 dagen)
POOL_LOOKBACK = 120                         # 4.6: 120 candles van 1u (5 dagen)
POOL_EQUAL_ATR = 0.1                        # 4.6: gelijke lows binnen 0,1 ATR(1u)
MAX_DISTANCE_PCT = 6.0                      # 4.13: een pool binnen 6% onder het slot
PRIK_MIN_ATR = 0.1                          # 4.8, gelijk aan zonesweep
PRIK_MAX_ATR = 2.5
HERSTEL_BARS = 6
SHIFT_BARS = 24                             # 4.9
DISP_BARS = rs.DISP_BARS                    # 4.10: 5 candles, 1,0 ATR (de regel van rangesweep.find_zones)
DISP_ATR = rs.DISP_ATR
STOP_ATR = 0.25                             # 4.12
MIN_STOP_PCT = rs.MIN_STOP_PCT              # 0,4%
ENTRY_BARS = 24                             # 4.13: een limiet is 24 candles van 15m geldig (6 uur)
V1_STOP_ATR = 1.0                           # §6
TIME_LIMIT = pd.Timedelta(days=7)           # 4.14
# Een scenario mag pas beginnen als de ATR van 15m warm is: anders hangt de sweep af van waar het venster begint.
WARMUP_15M = 30

# Toestanden (4.13) en eindstanden. Ze staan ook in app/end_reason.py (tests/test_basis_afsluiten.py eist een tekst).
WAIT_STATES = ("wacht_sweep", "prik", "wacht_shift", "wacht_fvg")
SCENARIO_ENDS = ("context_weg", "geen_pool", "afgerond")
ALT_CODES = ("B", "B0", "R", "K")                # aanvullende besluiten 2026-11-03; K: consolidatiebreuk (B-2026-11-03-10)
CONS_BARS = 8                               # K: de consolidatie bij de top is de 8 candles van 15m (2 uur) erna; vooraf vast, nooit afstellen
ENTRY_ENDS = ("vervallen", "weggelopen", "context_weg", "niet_vulbaar", "btc_tegen")
FAIL_REASONS = {
    "run": "De koers liep door de pool zonder terug te sluiten (een run, geen sweep).",
    "geen_herstel": f"Geen slot terug boven de pool binnen {HERSTEL_BARS} candles van 15m.",
    "geen_top": "Er was geen top op 15m vóór de sweep om te breken.",
    "geen_shift": f"Geen slot boven de top binnen {SHIFT_BARS} candles van 15m, of eerst een slot onder het uiterste.",
    "geen_displacement": "De breuk kwam zonder displacement en fair value gap.",
    "terugtest_al_geweest": "De koers was al terug in de gap voordat de entry bekend was.",
    "premium": "De limiet lag boven het evenwicht van de range (premium).",
    "geen_doel": "Er lag geen doel voorbij de limiet.",
}


# ---------------------------------------------------------------------------------------------------------------------------------------
# Candles


@dataclass
class Frame:
    """Eén timeframe als numpy-reeksen. Gespiegeld (short): high' = -low, low' = -high, open' = -open, close' = -close; de ATR is dezelfde."""
    ts: pd.DatetimeIndex
    ct: np.ndarray                  # sluitmoment in ns
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    atr: np.ndarray
    mirror: bool

    @property
    def n(self) -> int:
        return len(self.c)

    def last_closed(self, t_ns: int) -> int:
        """Index van de laatste candle die op t gesloten was, -1 als er geen is."""
        return int(np.searchsorted(self.ct, t_ns, side="right")) - 1


def closed(df: pd.DataFrame, now: pd.Timestamp, tf: str) -> pd.DataFrame:
    return df[df["timestamp"] + TF[tf] <= now].reset_index(drop=True)


def _frame(df: pd.DataFrame, tf: str, mirror: bool) -> Frame:
    df = df.reset_index(drop=True)
    if "volume" not in df:
        df = df.assign(volume=1.0)
    atr = add_indicators(df)["atr"].to_numpy(float) if len(df) else np.array([], float)
    ts = pd.DatetimeIndex(df["timestamp"]).as_unit("ns")
    ct = (ts + TF[tf]).asi8 if len(df) else np.array([], np.int64)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    if mirror:
        o, h, l, c = -o, -l, -h, -c
    return Frame(ts, np.asarray(ct, np.int64), o, h, l, c, atr, mirror)


def swing_lows(fr: Frame, k: int) -> np.ndarray:
    """4.1: strikt lager dan k links, lager of gelijk aan k rechts (trendlab._pivot_flags); bekend op het sluiten van p + k."""
    return _pivot_flags(fr.l, k)


def swing_highs(fr: Frame, k: int) -> np.ndarray:
    return _pivot_flags(-fr.h, k)


# ---------------------------------------------------------------------------------------------------------------------------------------
# 4.2 BOS en CHoCH


@dataclass
class Break:
    i: int                  # de breukcandle
    up: bool                # omhoog in dit frame
    level: float
    swing: int              # index van de gebroken swing
    known: int              # sluitmoment in ns
    label: Optional[str]    # 'BOS', 'CHOCH' of None (de eerste)


def breaks(fr: Frame, k: int) -> list[Break]:
    """Elke gesloten candle: slot boven de meest recente herkenbare, nog niet gebroken swing high is een breuk omhoog (omlaag gespiegeld). Een
    breuk verbruikt elke herkenbare swing die het slot passeerde, zodat een oudere lagere top later niet opnieuw als breuk telt. Een lont zonder
    slot is geen breuk."""
    hi_f, lo_f = swing_highs(fr, k), swing_lows(fr, k)
    highs: list[list] = []          # [p, niveau, gebroken]
    lows: list[list] = []
    out: list[Break] = []
    last_up: Optional[bool] = None
    for i in range(fr.n):
        p = i - k
        if p >= 0:
            if hi_f[p]:
                highs.append([p, fr.h[p], False])
            if lo_f[p]:
                lows.append([p, fr.l[p], False])
        for side, pool, up in ((1, highs, True), (-1, lows, False)):
            open_ = [s for s in pool if not s[2]]
            if not open_:
                continue
            s = open_[-1]
            if (fr.c[i] - s[1]) * side > 0:
                for x in open_:
                    if (fr.c[i] - x[1]) * side > 0:
                        x[2] = True
                label = None if last_up is None else ("BOS" if last_up == up else "CHOCH")
                out.append(Break(i, up, float(s[1]), int(s[0]), int(fr.ct[i]), label))
                last_up = up
    return out


def break_times(df4: pd.DataFrame, now: pd.Timestamp) -> list[pd.Timestamp]:
    """Wanneer een 4u-breuk (in welke richting ook) herkenbaar werd: een geplaatste entry vervalt dan ('context_weg', 4.13)."""
    fr = _frame(closed(df4, now, "4h"), "4h", False)
    return [pd.Timestamp(b.known, tz="UTC") for b in breaks(fr, K_4H)]


# ---------------------------------------------------------------------------------------------------------------------------------------
# 4.3 en 4.4: bias en dealing range


@dataclass
class Context:
    range_id: str
    b: int
    s: int
    L: float
    H: float
    known: int              # het sluiten van de breukcandle

    @property
    def eq(self) -> float:
        return (self.L + self.H) / 2


class Context4h:
    def __init__(self, fr: Frame, direction: str, topdown: bool = False, prefix: str = ""):
        """topdown (aanvullend besluit 2026-11-03): de richting komt van de dag (DailyBias); hier telt dan alleen de laatste 4u-breuk in die
        richting voor de range. Een tussenliggende tegenbreuk (een herstel binnen de daling) gooit de range niet weg."""
        self.fr, self.direction, self.topdown, self.prefix = fr, direction, topdown, prefix
        self.events = [e for e in breaks(fr, K_4H) if e.up] if topdown else breaks(fr, K_4H)
        self.known = np.array([e.known for e in self.events], np.int64)
        self._cache: dict[int, Optional[Context]] = {}

    def at(self, t_ns: int) -> Optional[Context]:
        """De range voor deze richting op moment t, of None (neutraal of de andere kant). Alleen breuken en candles die op t herkenbaar waren."""
        q = self.fr.last_closed(t_ns)
        if q in self._cache:
            return self._cache[q]
        n_ev = int(np.searchsorted(self.known, self.fr.ct[q] if q >= 0 else -1, side="right")) if q >= 0 else 0
        ctx = None
        if n_ev:
            ev = self.events[n_ev - 1]
            b, s = ev.i, ev.swing
            if ev.up and q - b <= BIAS_MAX_BARS:
                L = float(self.fr.l[s + 1:b + 1].min())
                through = np.flatnonzero(self.fr.c[b + 1:q + 1] < L)
                H = float(self.fr.h[s:q + 1].max())
                rid = f"{self.prefix}{self.direction}:{self.fr.ts[b].isoformat()}"
                if not len(through):
                    ctx = Context(rid, b, s, L, H, int(self.fr.ct[b]))
                elif self.topdown:
                    # Doorbraak tegen de dag in (aanvullend besluit 2026-11-03, ZEC 2 november): een 4u-slot voorbij de range-rand terwijl de
                    # dag de richting houdt. De range rekt op naar het nieuwe uiterste; een nieuw scenario mag erin beginnen. Bekend op het
                    # slot van die candle; het uiterste groeit alleen met gesloten candles.
                    x = b + 1 + int(through[0])
                    ctx = Context(f"{rid}:door:{self.fr.ts[x].isoformat()}", b, s, float(self.fr.l[x:q + 1].min()), H, int(self.fr.ct[x]))
        self._cache[q] = ctx
        return ctx


class DailyBias:
    """De richting van de dag (aanvullend besluit 2026-11-03): de laatste breuk op gesloten dagcandles, dezelfde breukregel als 4.2 met
    pivots van 2 candles. 'long', 'short' of None (nog geen breuk in de data), op elk moment alleen met wat toen gesloten was."""

    def __init__(self, df1d: pd.DataFrame, now: pd.Timestamp):
        fr = _frame(closed(df1d, now, "1d"), "1d", False)
        ev = breaks(fr, K_4H) if fr.n else []
        self.known = np.array([e.known for e in ev], np.int64)
        self.up = [e.up for e in ev]

    def at(self, t_ns: int) -> Optional[str]:
        n = int(np.searchsorted(self.known, t_ns, side="right"))
        return None if n == 0 else ("long" if self.up[n - 1] else "short")


# ---------------------------------------------------------------------------------------------------------------------------------------
# 4.6: liquiditeitspools


@dataclass
class Pool:
    level: float
    key: str                # tijd van het punt met de laagste low
    known: int              # sluiten van p + 3 (1u) van het laatste punt
    touched: int            # eerste moment (ns) waarop een aanraking bekend was; int64-max = nooit
    n: int = 1              # aantal swing lows in de pool: 2 of meer is gelijke lows (EQL op de kaartgrafiek)


NEVER = np.iinfo(np.int64).max


class Pools:
    def __init__(self, f1: Frame, f15: Frame):
        self.f1, self.f15 = f1, f15
        self.flags = swing_lows(f1, K_1H)
        self._cache: dict[int, list[Pool]] = {}

    def _touch(self, level: float, known_idx: int, known_ns: int) -> int:
        f1, f15 = self.f1, self.f15
        t1 = NEVER
        hit = np.flatnonzero(f1.l[known_idx + 1:] <= level)
        if len(hit):
            t1 = int(f1.ct[known_idx + 1 + hit[0]])
        # Ook 15m: een prik in een 1u-candle die nog vormt, maakt de pool al op voordat die candle sluit.
        start = int(np.searchsorted(f15.ts.asi8, known_ns, side="left"))
        hit15 = np.flatnonzero(f15.l[start:] <= level)
        t15 = int(f15.ct[start + hit15[0]]) if len(hit15) else NEVER
        return min(t1, t15)

    def groups(self, q1: int) -> list[Pool]:
        if q1 in self._cache:
            return self._cache[q1]
        out: list[Pool] = []
        atr = self.f1.atr[q1] if q1 >= 0 else np.nan
        if q1 >= 0 and np.isfinite(atr):
            lo = max(0, q1 - POOL_LOOKBACK + 1)
            pts = [p for p in range(lo, q1 - K_1H + 1) if self.flags[p]]
            pts.sort(key=lambda p: (self.f1.l[p], p))
            group: list[int] = []
            for p in pts + [None]:
                if p is not None and group and self.f1.l[p] - self.f1.l[group[-1]] <= POOL_EQUAL_ATR * atr:
                    group.append(p)
                    continue
                if group:
                    first = min(group, key=lambda x: (self.f1.l[x], x))
                    last = max(group)
                    level = float(self.f1.l[first])
                    known_idx = last + K_1H
                    known = int(self.f1.ct[known_idx])
                    out.append(Pool(level, self.f1.ts[first].isoformat(), known, self._touch(level, known_idx, known), len(group)))
                group = [p] if p is not None else []
        self._cache[q1] = out
        return out

    def valid(self, t_ns: int, ctx: Context, close: float) -> list[Pool]:
        """Onaangeraakt op t, tussen L en EQ van de range, en onder het laatste slot van 15m."""
        q1 = self.f1.last_closed(t_ns)
        return [p for p in self.groups(q1) if p.touched > t_ns and ctx.L <= p.level <= ctx.eq and p.level < close]


# ---------------------------------------------------------------------------------------------------------------------------------------
# 4.7: POC als kandidaat-doel


@dataclass
class Poc:
    price: float            # in de coördinaten van het frame
    label: str
    known: int              # einde van de periode
    touched: int            # het moment waarop de eerste aanraking bekend was (5m-candle gesloten), NEVER als naakt


def _pocs(levels: Optional[Iterable], mirror: bool) -> Optional[list[Poc]]:
    if levels is None:
        return None
    from app import poc as poc_mod
    out = []
    for lv in levels:
        touched = NEVER if lv.touched_at is None else int((pd.Timestamp(lv.touched_at) + TF["5m"]).value)
        text = poc_mod.period_text(lv.period, lv.start)
        out.append(Poc(-lv.price if mirror else lv.price, text[:1].upper() + text[1:], int(pd.Timestamp(lv.end).value), touched))
    return out


def _naked(pocs: Optional[list[Poc]], t_ns: int) -> list[Poc]:
    return [p for p in pocs or [] if p.known <= t_ns < p.touched]


def _floor(limit: float, raw: float) -> float:
    """smc_eval.floor_stop met MIN_STOP_PCT in het (mogelijk gespiegelde) frame: minstens 0,4% van de limiet. Een negatieve prijs (gespiegeld)
    vraagt de absolute waarde; dat het voor beide richtingen gelijk is aan smc_eval.floor_stop, toetst test_model."""
    return min(raw, limit - abs(limit) * MIN_STOP_PCT / 100)


def _target(cands: list[tuple[str, str, float]], above: float) -> Optional[tuple[str, str, float]]:
    """4.7: de kandidaat die het dichtst boven `above` ligt. Nooit een verdere om een mooiere R:R."""
    over = [c for c in cands if c[2] > above]
    return min(over, key=lambda c: (c[2], c[0] != "range")) if over else None


# ---------------------------------------------------------------------------------------------------------------------------------------
# 4.10 en 4.11: displacement, FVG en order block


def displacement(f: Frame, j: int, c: int, last: int):
    """('ok', m, k, fvgs) | ('wacht', None, None, []) | ('geen', None, None, []). Per sweep telt de eerste m (j <= m <= c) met een rode candle k
    in m-5..m-1 (de laatste), slot[m] - high[k] >= 1 ATR(m), én een FVG met de middelste candle in k+1..m. 'wacht': alleen m = c voldoet nog en
    zijn derde FVG-candle (c+1) is nog niet gesloten."""
    for m in range(j, c + 1):
        if not np.isfinite(f.atr[m]):
            continue
        reds = [k for k in range(max(0, m - DISP_BARS), m) if f.c[k] < f.o[k]]
        if not reds:
            continue
        k = reds[-1]
        if f.c[m] - f.h[k] < DISP_ATR * f.atr[m]:
            continue
        fvgs = [(i, float(f.h[i - 2]), float(f.l[i])) for i in range(max(k + 2, 2), m + 2) if i <= last and f.h[i - 2] < f.l[i]]
        if fvgs:
            return "ok", m, k, fvgs
        if m + 1 > last:
            return "wacht", None, None, []
    return "geen", None, None, []


# ---------------------------------------------------------------------------------------------------------------------------------------
# Het scenario (4.13)


@dataclass
class _Active:
    ctx: Context
    discovered: int
    pool0: Pool
    cands: list
    v1: dict
    phase: str = "wacht_sweep"
    steps: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    prik: Optional[dict] = None
    shift: Optional[dict] = None
    end: Optional[tuple[str, int]] = None
    entry: Optional[dict] = None
    p: Optional[dict] = None                                    # P: POC-limiet bij moment A (aanvullend besluit 2026-11-03)
    alts: dict = field(default_factory=dict)                    # B en B0: lagere top (hogere bodem in het long-frame), naast A


def _ts(ns: int) -> pd.Timestamp:
    return pd.Timestamp(int(ns), tz="UTC")


class _Run:
    """Het scenario per richting op één (mogelijk gespiegeld) stel frames."""

    def __init__(self, direction: str, f4: Frame, f1: Frame, f15: Frame, pocs: Optional[list[Poc]], daily: Optional[DailyBias] = None,
                 counter: bool = False):
        self.direction, self.f4, self.f1, self.f15, self.pocs, self.daily, self.counter = direction, f4, f1, f15, pocs, daily, counter
        # counter (B-2026-11-03-11): de 4u-range van de laatste breuk in welke richting ook, maar alleen als de dag de andere kant op wijst.
        self.ctx = Context4h(f4, direction, topdown=daily is not None and not counter, prefix=COUNTER_PREFIX if counter else "")
        self.pools = Pools(f1, f15)
        self.hi15 = swing_highs(f15, K_15M)
        self.b15 = {b.i: b.label for b in breaks(f15, K_15M) if b.up}

    def px(self, v: Optional[float]) -> Optional[float]:
        return None if v is None else float(-v if self.f15.mirror else v)

    def span(self, lo: float, hi: float) -> tuple[float, float]:
        return (float(-hi), float(-lo)) if self.f15.mirror else (float(lo), float(hi))

    def _cands(self, ctx: Context, t_ns: int, low: float, high: float) -> list[tuple[str, str, float]]:
        out = [("range", "rand van de range", ctx.H)]
        out += [("poc", p.label, p.price) for p in _naked(self.pocs, t_ns) if low < p.price < high]
        return out

    def run(self) -> list[dict]:
        f = self.f15
        start = WARMUP_15M
        if f.n <= start:
            return []
        first_ok = int(f.ct[start])
        seen: set[str] = set()
        done: list[_Active] = []
        act: Optional[_Active] = None
        for t in range(start, f.n):
            T = int(f.ct[t])
            ctx = self.ctx.at(T)
            if self.counter:
                if self.daily is None or self.daily.at(T) in (None, self.direction):
                    ctx = None                                  # tegen de dag: alleen als de dag echt de andere kant op wijst
            elif self.daily is not None and self.daily.at(T) != self.direction:
                ctx = None                                      # de dag wijst de andere kant op (of nog geen breuk): geen scenario
            if act is not None and (ctx is None or ctx.range_id != act.ctx.range_id):
                act.end = ("context_weg", T)
                done.append(act)
                act = None
            if act is None:
                # Een range van vóór het venster kan al een scenario gehad hebben dat we niet zien: daar begint nooit een nieuw.
                if ctx is None or ctx.range_id in seen or ctx.known < first_ok:
                    continue
                pools = self.pools.valid(T, ctx, f.c[t])
                near = [p for p in pools if (f.c[t] - p.level) / abs(f.c[t]) * 100 <= MAX_DISTANCE_PCT]
                if not near:
                    continue
                seen.add(ctx.range_id)
                p0 = max(near, key=lambda p: p.level)
                act = _Active(ctx, T, p0, self._cands(ctx, T, f.c[t], ctx.H),
                              self._v1(ctx, T, p0, self._cands(ctx, T, p0.level, float("inf"))))
                act.p = self._p(ctx, T, float(f.c[t]))
                act.steps.append({"stap": "ontdekt", "at": T})
                continue
            for code in ALT_CODES:
                self._alt(act, t, ctx, code)
            self._step(act, t, ctx)
            if act.entry is not None or act.end is not None:
                if act.end is None:
                    act.end = ("afgerond", act.entry["known"])
                done.append(act)
                act = None
        if act is not None:
            done.append(act)
        return [self._out(a) for a in done]

    def _v1(self, ctx: Context, T: int, p0: Pool, cands) -> dict:
        """§6 V1: limiet op P0 op moment A, stop 1,0 ATR(1u) eronder met de ondergrens, doel de dichtste kandidaat boven P0 (bevroren)."""
        q1 = self.f1.last_closed(T)
        atr1 = float(self.f1.atr[q1])
        stop = _floor(p0.level, p0.level - V1_STOP_ATR * atr1)
        tgt = _target(cands, p0.level)
        rr = (tgt[2] - p0.level) / (p0.level - stop) if tgt and p0.level > stop else None
        return {"limit": p0.level, "stop": stop, "take": tgt[2] if tgt else None, "target_kind": tgt[0] if tgt else None, "rr": rr}

    def _p(self, ctx: Context, T: int, close: float) -> Optional[dict]:
        """P (aanvullend besluit 2026-11-03): limiet op de dichtste naakte POC onder het slot (long-frame), tussen L en EQ en binnen 6%,
        stop 1,0 ATR(1u) eronder met de vloer, doel de dichtste kandidaat erboven. Zonder POC-data of zonder zo'n POC: None."""
        if self.pocs is None:
            return None
        near = [p for p in _naked(self.pocs, T) if ctx.L <= p.price <= ctx.eq and p.price < close
                and (close - p.price) / abs(close) * 100 <= MAX_DISTANCE_PCT]
        if not near:
            return None
        poc = max(near, key=lambda p: p.price)
        atr1 = float(self.f1.atr[self.f1.last_closed(T)])
        if not np.isfinite(atr1):
            return None
        stop = _floor(poc.price, poc.price - V1_STOP_ATR * atr1)
        tgt = _target(self._cands(ctx, T, poc.price, float("inf")), poc.price)
        rr = (tgt[2] - poc.price) / (poc.price - stop) if tgt else None
        return {"known": T, "limit": poc.price, "stop": stop, "take": tgt[2] if tgt else None, "target_kind": tgt[0] if tgt else None,
                "target_label": tgt[1] if tgt else None, "rr": rr, "label": poc.label}

    def _higher_low(self, t: int, ctx: Context, discount_only: bool, used: set, log: Optional[list] = None) -> Optional[tuple[int, float, int]]:
        """B: een 1u-swing low die op het sluiten van 15m-candle t bekend werd, hoger dan de vorige bekende swing low sinds de swing van de
        range, tussen L en EQ (B) of L en H (B0), binnen 6% van het slot en nog zonder slot eronder. (j15, X, p) of None."""
        f, f1 = self.f15, self.f1
        q, qp = f1.last_closed(int(f.ct[t])), f1.last_closed(int(f.ct[t - 1]))
        start_ns = int(self.f4.ts[ctx.s].value)
        for c1 in range(qp + 1, q + 1):
            p = c1 - K_1H
            if p < 0 or p in used or not self.pools.flags[p] or int(f1.ts[p].value) < start_ns:
                continue
            prev = [r for r in range(p - 1, -1, -1) if self.pools.flags[r] and int(f1.ts[r].value) >= start_ns][:1]
            low = float(f1.l[p])
            why = ("geen_vorige_swing" if not prev else "niet_lager_dan_vorige" if low <= f1.l[prev[0]] else "buiten_de_range" if low < ctx.L
                   else "niet_in_premium" if low > (ctx.eq if discount_only else ctx.H) else None)
            if why is None and (f.c[t] - low) / abs(f.c[t]) * 100 > MAX_DISTANCE_PCT:
                why = "te_ver_van_de_koers"
            if why:
                if log is not None:
                    log.append({"at": int(f.ct[t]), "wat": why, "niveau": low})
                continue
            lo = int(np.searchsorted(f.ts.asi8, f1.ts[p].value, side="left"))
            hi = int(np.searchsorted(f.ts.asi8, (f1.ts[p] + TF["1h"]).value, side="left"))
            if hi <= lo:
                continue
            j = lo + int(np.argmin(f.l[lo:hi]))
            if (f.c[j:t + 1] < low).any():
                continue
            return j, low, p
        return None

    def _alt(self, a: _Active, t: int, ctx: Context, code: str) -> None:
        """Eén B- of B0-entry per scenario, naast A; eindigt het scenario, dan stopt dit ook. Alleen candles tot en met t."""
        tr = a.alts.setdefault(code, {"phase": "zoek", "used": set(), "entry": None, "log": []})
        if tr["entry"] is not None:
            return
        f = self.f15
        T = int(f.ct[t])
        if tr["phase"] == "zoek":
            hit = self._higher_low(t, ctx, code in ("B", "R", "K"), tr["used"], tr["log"])
            if hit is None:
                return
            j, X, p = hit
            tr["used"].add(p)
            if code == "K":
                tr.update(phase="wacht_cons", j=j, X=X, low_at=int(f.ts[j].value), found=T)
            else:
                tops = [q for q in range(0, j - K_15M + 1) if self.hi15[q]]
                if not tops:
                    tr["log"].append({"at": T, "wat": "geen_top", "niveau": X})
                    return
                bp = tops[-1]
                tr.update(phase="wacht_shift", j=j, X=X, B=float(f.h[bp]), top_at=int(f.ts[bp].value), low_at=int(f.ts[j].value), found=T,
                          checked=j)
            tr["log"].append({"at": T, "wat": "gevonden", "niveau": X})
        if tr["phase"] == "wacht_cons":
            # K (B-2026-11-03-10, SOL 30 oktober): na een rechte beweging ligt het laatste 15m-dal vóór de top (B en R) ver weg. K breekt
            # in plaats daarvan de consolidatie bij de top: het uiterste van de CONS_BARS candles van 15m na de top. Sluit er in die candles
            # een voorbij de top zelf, dan vervalt de poging.
            j = tr["j"]
            if t < j + CONS_BARS:
                return
            win = slice(j + 1, j + CONS_BARS + 1)
            if (f.c[win] < tr["X"]).any():
                tr["phase"] = "zoek"
                tr["log"].append({"at": T, "wat": "geen_shift", "niveau": tr["X"]})
                return
            k = j + 1 + int(np.argmax(f.h[win]))
            tr.update(phase="wacht_shift", B=float(f.h[k]), top_at=int(f.ts[k].value), checked=j + CONS_BARS)
        if tr["phase"] == "wacht_shift":
            for u in range(tr["checked"] + 1, t + 1):
                tr["checked"] = u
                if f.c[u] < tr["X"] or u >= tr["j"] + SHIFT_BARS:
                    tr["phase"] = "zoek"
                    tr["log"].append({"at": int(f.ct[u]), "wat": "geen_shift", "niveau": tr["X"]})
                    return
                if f.c[u] > tr["B"]:
                    tr["c"], tr["phase"] = u, "wacht_fvg"
                    break
            else:
                return
        if code in ("R", "K") and tr["phase"] == "wacht_fvg":
            return self._retest(tr, ctx, t)
        if tr["phase"] == "wacht_fvg":
            what, m, k, fvgs = displacement(f, tr["j"], tr["c"], t)
            if what == "wacht":
                return
            if what == "geen":
                tr["phase"] = "zoek"
                tr["log"].append({"at": T, "wat": "geen_displacement", "niveau": tr["X"]})
                return
            reason, e = self._plan(t, ctx, k, fvgs, tr["X"], tr["c"], premium_check=(code == "B"))
            if e is None:
                tr["phase"] = "zoek"
                tr["log"].append({"at": T, "wat": reason, "niveau": tr["X"]})
                return
            tr["entry"] = {**e, "extreme": tr["X"], "low_at": tr["low_at"], "top": tr["B"], "top_at": tr["top_at"],
                           "shift_at": int(f.ct[tr["c"]])}

    def _retest(self, tr: dict, ctx: Context, t: int) -> None:
        """R en K (aanvullende besluiten 2026-11-03): limiet op het gebroken niveau zelf, zonder displacement of gap; stop 0,25 ATR voorbij
        het uiterste met de vloer; doel zoals 4.7. Geen premium-eis op de limiet. Bekend op candle t, niet op de breukcandle: de breuk kan
        vallen vóór de 1u-top herkenbaar was, en dan was het punt pas bij t bekend (gevonden 2026-11-03: 7 van 26 punten te vroeg)."""
        f = self.f15
        c = tr["c"]
        T = int(f.ct[t])
        limit = tr["B"]
        stop = _floor(limit, tr["X"] - STOP_ATR * f.atr[c])
        tgt = _target(self._cands(ctx, T, limit, float("inf")), limit)
        if tgt is None or not np.isfinite(stop) or limit <= stop:
            tr["phase"] = "zoek"
            tr["log"].append({"at": T, "wat": "geen_doel", "niveau": tr["X"]})
            return
        tr["entry"] = {"known": T, "limit": limit, "stop": stop, "take": tgt[2], "target_kind": tgt[0], "target_label": tgt[1],
                       "rr": (tgt[2] - limit) / (limit - stop), "zone": (limit, limit), "ob_overlap": False, "eq": ctx.eq,
                       "range": (ctx.L, ctx.H), "extreme": tr["X"], "low_at": tr["low_at"], "top": tr["B"], "top_at": tr["top_at"],
                       "shift_at": int(f.ct[c])}

    def _plan(self, t: int, ctx: Context, k: int, fvgs: list, X: float, c: int, premium_check: bool = True) -> tuple[Optional[str], Optional[dict]]:
        """De limiet, stop en doel van 4.11 en 4.12 voor elke entry met een gap (A, B, B0). (reden, None) als er geen entry komt."""
        f = self.f15
        T = int(f.ct[t])
        unfilled = [g for g in fvgs if not (f.l[g[0] + 1:t + 1] <= g[2]).any()]
        if not unfilled:
            return "terugtest_al_geweest", None
        i, g_lo, g_hi = min(unfilled, key=lambda g: (g[1], g[0]))
        ob_lo, ob_hi = float(f.l[k]), float(f.h[k])
        lo, hi = max(g_lo, ob_lo), min(g_hi, ob_hi)
        overlap = hi > lo
        z_lo, z_hi = (lo, hi) if overlap else (g_lo, g_hi)
        limit = z_hi
        if premium_check and limit > ctx.eq:
            return "premium", None
        stop = _floor(limit, X - STOP_ATR * f.atr[c])
        tgt = _target(self._cands(ctx, T, limit, float("inf")), limit)
        if tgt is None or limit <= stop:
            return "geen_doel", None
        naked = _naked(self.pocs, T)
        samenval = None if self.pocs is None else any(z_lo <= p.price <= z_hi or ob_lo <= p.price <= ob_hi for p in naked)
        return None, {"known": T, "limit": limit, "stop": stop, "take": tgt[2], "target_kind": tgt[0], "target_label": tgt[1],
                      "rr": (tgt[2] - limit) / (limit - stop), "zone": (z_lo, z_hi), "fvg": (g_lo, g_hi), "fvg_at": int(f.ts[i - 1].value),
                      "ob": (ob_lo, ob_hi), "ob_at": int(f.ts[k].value), "ob_overlap": overlap, "poc_samenval": samenval,
                      "shift_label": self.b15.get(c), "eq": ctx.eq, "range": (ctx.L, ctx.H)}

    def _fail(self, a: _Active, reason: str, T: int, ctx: Context) -> None:
        a.attempts.append({"reden": reason, "at": T, "pool": a.prik["pool"].level if a.prik else None,
                           "steps": [s for s in a.steps if s["stap"] != "ontdekt"]})
        a.steps = [s for s in a.steps if s["stap"] == "ontdekt"]
        a.prik, a.shift, a.phase = None, None, "wacht_sweep"
        if not self.pools.valid(T, ctx, self.f15.c[self.f15.last_closed(T)]):
            a.end = ("geen_pool", T)

    def _step(self, a: _Active, t: int, ctx: Context) -> None:
        f = self.f15
        T = int(f.ct[t])
        if a.phase == "wacht_sweep":
            prev = int(f.ct[t - 1])
            pools = self.pools.valid(prev, ctx, f.c[t - 1])
            touched = [p for p in pools if f.l[t] <= p.level]
            if touched:
                P = min(touched, key=lambda p: p.level)            # prikt één candle door meer pools, dan telt de laagste
                if np.isfinite(f.atr[t]) and f.l[t] <= P.level - PRIK_MIN_ATR * f.atr[t]:
                    a.prik = {"j": t, "pool": P, "X": float(f.l[t]), "atr": float(f.atr[t])}
                    a.phase = "prik"
            if a.phase == "wacht_sweep":
                if not self.pools.valid(T, ctx, f.c[t]):
                    a.end = ("geen_pool", T)
                return
        if a.phase == "prik":
            pk = a.prik
            pk["X"] = min(pk["X"], float(f.l[t]))
            if pk["pool"].level - pk["X"] > PRIK_MAX_ATR * pk["atr"]:
                return self._fail(a, "run", T, ctx)
            if f.c[t] > pk["pool"].level:
                j = pk["j"]
                a.steps.append({"stap": "sweep", "at": T, "pool": pk["pool"].level, "extreme": pk["X"], "prik_at": int(f.ts[j].value),
                                "terug_at": int(f.ts[t].value), "pool_at": int(pd.Timestamp(pk["pool"].key).value), "pool_n": pk["pool"].n})
                tops = [p for p in range(0, j - K_15M + 1) if self.hi15[p]]
                if not tops:
                    return self._fail(a, "geen_top", T, ctx)
                bp = tops[-1]
                a.shift = {"r": t, "B": float(f.h[bp]), "top_at": int(f.ts[bp].value)}
                a.phase = "wacht_shift"
            elif t >= pk["j"] + HERSTEL_BARS - 1:
                return self._fail(a, "geen_herstel", T, ctx)
            else:
                return
        if a.phase == "wacht_shift":
            sh, pk = a.shift, a.prik
            if t > sh["r"] and f.c[t] < pk["X"]:
                return self._fail(a, "geen_shift", T, ctx)
            if f.c[t] > sh["B"]:
                sh["c"] = t
                a.steps.append({"stap": "shift", "at": T, "top": sh["B"], "top_at": sh["top_at"], "label": self.b15.get(t)})
                return self._displaced(a, t, ctx)
            if t >= pk["j"] + SHIFT_BARS:
                return self._fail(a, "geen_shift", T, ctx)
            return
        if a.phase == "wacht_fvg":
            return self._displaced(a, t, ctx)

    def _displaced(self, a: _Active, t: int, ctx: Context) -> None:
        f = self.f15
        T = int(f.ct[t])
        what, m, k, fvgs = displacement(f, a.prik["j"], a.shift["c"], t)
        if what == "wacht":
            a.phase = "wacht_fvg"
            return
        if what == "geen":
            return self._fail(a, "geen_displacement", T, ctx)
        # 'at' is wanneer het model hem vaststelt (bij de shift of de derde FVG-candle daarna); 'gesloten_at' wanneer displacement en FVG
        # zelf al gesloten waren (4.10). Zo verandert een eerdere stap nooit met meer data.
        closed_at = max(int(f.ct[m]), max(int(f.ct[g[0]]) for g in fvgs))
        a.steps.append({"stap": "displacement", "at": T, "gesloten_at": closed_at, "ob_at": int(f.ts[k].value), "disp_at": int(f.ts[m].value)})
        self._entry(a, t, ctx, m, k, fvgs)

    def _entry(self, a: _Active, t: int, ctx: Context, m: int, k: int, fvgs: list) -> None:
        T = int(self.f15.ct[t])
        reason, e = self._plan(t, ctx, k, fvgs, a.prik["X"], a.shift["c"])
        if e is None:
            return self._fail(a, reason, T, ctx)
        a.entry = {**e, "extreme": a.prik["X"], "pool": a.prik["pool"].level}
        a.phase = "entry"
        a.steps.append({"stap": "entry", "at": T})

    def _out(self, a: _Active) -> dict:
        ctx = a.ctx
        lo, hi = self.span(ctx.L, ctx.H)
        steps = [self._step_out(s) for s in a.steps]
        out = {
            "direction": self.direction, "range_id": ctx.range_id, "range_at": _ts(self.f4.ts[ctx.b].value),
            "range_known_at": _ts(ctx.known), "swing_at": _ts(self.f4.ts[ctx.s].value),
            "range_low": lo, "range_high": hi, "eq": self.px(ctx.eq), "target_edge": self.px(ctx.H),
            "discovered_at": _ts(a.discovered),
            "pool0": {"level": self.px(a.pool0.level), "key": a.pool0.key, "known_at": _ts(a.pool0.known), "n": a.pool0.n},
            "candidates": [{"kind": k, "label": lbl, "price": self.px(p)} for k, lbl, p in a.cands],
            "status": a.end[0] if a.end else a.phase, "ended_at": _ts(a.end[1]) if a.end else None,
            "steps": steps, "attempts": [{"reden": x["reden"], "at": _ts(x["at"]), "pool": self.px(x["pool"]),
                                          "steps": [self._step_out(s) for s in x["steps"]]} for x in a.attempts],
            "v1": {k: (self.px(v) if k in ("limit", "stop", "take") else v) for k, v in a.v1.items()},
            "entry": None,
            "p": None if a.p is None else {"known_at": _ts(a.p["known"]), "limit": self.px(a.p["limit"]), "stop": self.px(a.p["stop"]),
                                           "take": self.px(a.p["take"]), "rr": a.p["rr"], "target_kind": a.p["target_kind"],
                                           "target_label": a.p["target_label"], "label": a.p["label"]},
        }
        for code in ALT_CODES:
            # Alleen voor de controle achteraf (scripts/model_kaarten.py --tekst): waar een lagere top afviel. Geen stap, geen kaart.
            out[code.lower() + "_log"] = [{"at": _ts(x["at"]), "wat": x["wat"], "niveau": self.px(x["niveau"])}
                                          for x in (a.alts.get(code) or {}).get("log", [])]
            e = (a.alts.get(code) or {}).get("entry")
            out[code.lower()] = None if e is None else {
                "known_at": _ts(e["known"]), "limit": self.px(e["limit"]), "stop": self.px(e["stop"]), "take": self.px(e["take"]),
                "rr": float(e["rr"]), "target_kind": e["target_kind"], "target_label": e["target_label"],
                "zone_low": self.span(*e["zone"])[0], "zone_high": self.span(*e["zone"])[1], "ob_overlap": bool(e["ob_overlap"]),
                "extreme": self.px(e["extreme"]), "low_at": _ts(e["low_at"]), "top": self.px(e["top"]), "top_at": _ts(e["top_at"]),
                "shift_at": _ts(e["shift_at"]), "expires_at": _ts(e["known"]) + ENTRY_BARS * TF["15m"],
                "range_low": self.span(*e["range"])[0], "range_high": self.span(*e["range"])[1], "eq": self.px(e["eq"])}
        if a.entry:
            e = a.entry
            out["entry"] = {
                "known_at": _ts(e["known"]), "limit": self.px(e["limit"]), "stop": self.px(e["stop"]), "take": self.px(e["take"]),
                "rr": float(e["rr"]), "target_kind": e["target_kind"], "target_label": e["target_label"],
                "zone_low": self.span(*e["zone"])[0], "zone_high": self.span(*e["zone"])[1],
                "fvg_low": self.span(*e["fvg"])[0], "fvg_high": self.span(*e["fvg"])[1], "fvg_at": _ts(e["fvg_at"]),
                "ob_low": self.span(*e["ob"])[0], "ob_high": self.span(*e["ob"])[1], "ob_at": _ts(e["ob_at"]),
                "ob_overlap": bool(e["ob_overlap"]), "poc_samenval": e["poc_samenval"], "shift_label": e["shift_label"],
                "extreme": self.px(e["extreme"]), "pool": self.px(e["pool"]), "eq": self.px(e["eq"]),
                "range_low": self.span(*e["range"])[0], "range_high": self.span(*e["range"])[1],
                "expires_at": _ts(e["known"]) + ENTRY_BARS * TF["15m"],
            }
        return out

    def _step_out(self, s: dict) -> dict:
        out = {}
        for k, v in s.items():
            if k in ("stap", "label", "pool_n"):
                out[k] = v
            elif k.endswith("at"):
                out[k] = _ts(v)
            else:
                out[k] = self.px(v)
        return out


COUNTER_PREFIX = "tegen:"


def scenarios(frames: dict, now: pd.Timestamp, pocs: Optional[Iterable] = None, counter: bool = False) -> list[dict]:
    """Alle scenario's in deze candles, oudste eerst, voor beide richtingen. frames: {'4h', '1h', '15m'} met kolommen timestamp (open, UTC),
    open, high, low, close; alleen candles die op `now` gesloten zijn tellen. pocs: poc.PocLevel's (met touched_at), of None als er voor de
    coin geen POC-data is (dan is POC-samenval 'niet gemeten').

    counter (B-2026-11-03-11, de stille arm "tegen de dagtrend"): dezelfde regels, maar op de 4u-range van de laatste 4u-breuk tegen de
    dag in (een herstel of omkeer), alleen met dagcandles. range_id begint dan met COUNTER_PREFIX. Zonder dagcandles: geen scenario's."""
    now = pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    dfs = {tf: closed(frames[tf], now, tf) for tf in ("4h", "1h", "15m")}
    pocs = list(pocs) if pocs is not None else None
    # Aanvullend besluit 2026-11-03: met dagcandles bepaalt de dag de richting (top-down). Zonder (tests, oude scripts) de oude 4u-regel.
    daily = DailyBias(frames["1d"], now) if frames.get("1d") is not None and len(frames["1d"]) else None
    if counter and daily is None:
        return []
    found = []
    for direction, mirror in (("long", False), ("short", True)):
        fr = {tf: _frame(df, tf, mirror) for tf, df in dfs.items()}
        if not all(f.n for f in fr.values()):
            continue
        found += _Run(direction, fr["4h"], fr["1h"], fr["15m"], _pocs(pocs, mirror), daily, counter).run()
    return sorted(found, key=lambda s: (s["discovered_at"], s["direction"]))


STEP_ORDER = ("ontdekt", "sweep", "shift", "displacement", "entry")


def known_until(sc: dict, cut: pd.Timestamp) -> list[tuple[str, pd.Timestamp]]:
    """De stappen van een scenario die op `cut` herkenbaar waren: voor de prefix-toets en de tekening."""
    return [(s["stap"], s["at"]) for s in sc["steps"] if s["at"] <= cut]


# ---------------------------------------------------------------------------------------------------------------------------------------
# 4.14: vulling en uitkomst op 5m (live motor en script; V1 dezelfde code)


def walk_fill(direction: str, limit: float, take: Optional[float], published_at: pd.Timestamp, expires_at: Optional[pd.Timestamp],
              b5: pd.DataFrame, price_at_publish: Optional[float] = None, breaks_at: Iterable[pd.Timestamp] = ()) -> dict:
    """Wat er na publicatie met een limiet gebeurde, op 5m-candles die ná de publicatie openden. Eindstanden: 'gevuld', 'vervallen' (na
    expires_at), 'weggelopen' (het doel kwam eerst), 'context_weg' (een nieuwe 4u-breuk), 'niet_vulbaar' (de koers stond bij publicatie al door
    de limiet; geen marktorder). Raakt één candle limiet en doel, dan telt de vulling. `door_limiet`: de koers kwam strikt door de limiet.
    `vulbaar`: de limiet lag bij publicatie aan de goede kant van de koers (None zonder koers)."""
    sign = 1 if direction == "long" else -1
    vulbaar = None if price_at_publish is None else bool((price_at_publish - limit) * sign > 0)
    base = {"state": None, "at": None, "door_limiet": None, "vulbaar": vulbaar}
    if vulbaar is False:
        return {**base, "state": "niet_vulbaar", "at": published_at}
    brk = sorted(b for b in breaks_at if b > published_at)
    for row in b5[b5["timestamp"] >= published_at].itertuples():
        ts = row.timestamp
        if expires_at is not None and ts >= expires_at:
            return {**base, "state": "vervallen", "at": expires_at}
        if brk and ts >= brk[0]:
            return {**base, "state": "context_weg", "at": brk[0]}
        low, high = (row.low, row.high) if sign > 0 else (-row.high, -row.low)
        lim = limit * sign
        if low <= lim:
            return {**base, "state": "gevuld", "at": ts, "door_limiet": bool(low < lim)}
        if take is not None and high >= take * sign:
            return {**base, "state": "weggelopen", "at": ts}
    return base


def outcome(direction: str, entry: float, stop: float, take: Optional[float], filled_at: pd.Timestamp, b5: pd.DataFrame,
            now: Optional[pd.Timestamp] = None) -> dict:
    """Stop of doel op 5m-candles die na de vulcandle openden, zoals level_check; beide in één candle telt als stop (ambigu). Na TIME_LIMIT
    sluit de meting op het slot ('tijd'). Zonder uitkomst: state None. R bruto, zonder kosten."""
    sign = 1 if direction == "long" else -1
    risk = (entry - stop) * sign
    after = b5[b5["timestamp"] > filled_at]
    for row in after.itertuples():
        if row.timestamp >= filled_at + TIME_LIMIT:
            return {"state": "tijd", "at": row.timestamp, "r": (row.open - entry) * sign / risk, "ambiguous": False}
        hit_stop = (row.low <= stop) if sign > 0 else (row.high >= stop)
        hit_take = take is not None and ((row.high >= take) if sign > 0 else (row.low <= take))
        if hit_stop:
            return {"state": "stop_loss", "at": row.timestamp, "r": -1.0, "ambiguous": bool(hit_take)}
        if hit_take:
            return {"state": "take_profit", "at": row.timestamp, "r": (take - entry) * sign / risk, "ambiguous": False}
    return {"state": None, "at": None, "r": None, "ambiguous": False}
