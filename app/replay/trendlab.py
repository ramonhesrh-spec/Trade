"""Strategie-lab: kosten-robuuste regels op 1u en 4u, getoetst met kosten, twee helften, een marge en een controle op willekeurige instappen.

Waarom dit lab: op 30m met stops van 0,4% kost een rondreis ongeveer 0,15R en was het bruto voordeel van elke regel rond nul (zie breakretest_scan.py). Met
stops van 2 tot 4% zijn de kosten ongeveer 0,02R en blijft er ruimte voor een klein voordeel. Trendvolgen heeft bovendien de vorm die je zoekt: vaak een kleine
stop, soms een klapper van 5R of meer. Dat is een hypothese; dit lab toetst haar.

Regels staan vooraf vast (geen afstelling op de data). Alle instappen zijn de open van de candle NA het signaal, behalve de sweep die op het slot instapt.
Een candle die stop en doel raakt telt als stop. Pure functies; draai via scripts/strategy_lab.py."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app import smc_eval
from app.replay.lab import add_indicators

TRAIL_K_STOP = 2.0       # eerste stop op 2 ATR van de instap
TRAIL_K = 3.0            # chandelier-stop op 3 ATR van het uiterste sinds de instap
SWEEP_MAX_BARS = 48      # 1u-candles tot de sweep-trade op het slot sluit
SWEEP_COOLDOWN = 24      # hetzelfde niveau telt binnen zoveel candles één keer
WARMUP = 210             # candles voor de EMA van 200


@dataclass(frozen=True)
class Variant:
    name: str
    family: str          # donchian, pullback of sweep
    timeframe: str
    params: tuple


VARIANTS = (
    Variant("DON20", "donchian", "4h", (20, False)),
    Variant("DON20_TREND", "donchian", "4h", (20, True)),
    Variant("DON55", "donchian", "4h", (55, False)),
    Variant("DON55_TREND", "donchian", "4h", (55, True)),
    Variant("PULL21", "pullback", "4h", (21,)),
    Variant("PULL50", "pullback", "4h", (50,)),
    Variant("SWEEP_DAG_2R", "sweep", "1h", ("D", 2.0)),
    Variant("SWEEP_DAG_3R", "sweep", "1h", ("D", 3.0)),
    Variant("SWEEP_WEEK_2R", "sweep", "1h", ("W", 2.0)),
    Variant("SWEEP_WEEK_3R", "sweep", "1h", ("W", 3.0)),
)


def prepare(bars: pd.DataFrame) -> pd.DataFrame:
    b = add_indicators(bars).reset_index(drop=True)
    for n in (21, 50, 200):
        b[f"ema{n}"] = b["close"].ewm(span=n, adjust=False).mean()
    return b


def donchian_signals(b: pd.DataFrame, n: int, with_trend: bool) -> list[tuple[int, int]]:
    """[(signaal_candle, +1 of -1)]: slot voorbij het hoogste hoog of laagste laag van de vorige n candles, optioneel met de EMA van 200 als trendfilter."""
    hh, ll = b["high"].shift(1).rolling(n).max(), b["low"].shift(1).rolling(n).min()
    long_ok = (b["close"] > hh) & ((b["close"] > b["ema200"]) if with_trend else True)
    short_ok = (b["close"] < ll) & ((b["close"] < b["ema200"]) if with_trend else True)
    return sorted([(i, 1) for i in np.flatnonzero(long_ok.to_numpy()) if i >= WARMUP] + [(i, -1) for i in np.flatnonzero(short_ok.to_numpy()) if i >= WARMUP])


def pullback_signals(b: pd.DataFrame, x: int) -> list[tuple[int, int]]:
    """In een trend (EMA50 boven of onder EMA200) raakt de candle de EMA van x en sluit er weer aan de goede kant van."""
    ema = b[f"ema{x}"]
    up, down = b["ema50"] > b["ema200"], b["ema50"] < b["ema200"]
    long_ok = up & (b["low"] <= ema) & (b["close"] > ema)
    short_ok = down & (b["high"] >= ema) & (b["close"] < ema)
    return sorted([(i, 1) for i in np.flatnonzero(long_ok.to_numpy()) if i >= WARMUP] + [(i, -1) for i in np.flatnonzero(short_ok.to_numpy()) if i >= WARMUP])


def sweep_signals(b: pd.DataFrame, period: str) -> list[tuple[int, int]]:
    """Prik door het hoog of laag van de vorige dag (D) of week (W) en sluit er weer terug; hetzelfde niveau telt binnen SWEEP_COOLDOWN candles één keer."""
    ts = b["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    key = ts.dt.floor("D") if period == "D" else ts.dt.to_period("W").dt.start_time
    prev_high = b.groupby(key)["high"].max().shift(1).reindex(key).to_numpy()
    prev_low = b.groupby(key)["low"].min().shift(1).reindex(key).to_numpy()
    high, low, close = b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy()
    out, last = [], {}
    for i in range(WARMUP, len(b)):
        if not np.isnan(prev_high[i]) and high[i] > prev_high[i] and close[i] < prev_high[i]:
            if i - last.get((-1, prev_high[i]), -10**9) >= SWEEP_COOLDOWN:
                out.append((i, -1))
            last[(-1, prev_high[i])] = i
        if not np.isnan(prev_low[i]) and low[i] < prev_low[i] and close[i] > prev_low[i]:
            if i - last.get((1, prev_low[i]), -10**9) >= SWEEP_COOLDOWN:
                out.append((i, 1))
            last[(1, prev_low[i])] = i
    return out


def exit_trail(b: pd.DataFrame, j0: int, sign: int, entry: float, stop0: float, k_trail: float) -> tuple[float, int, str]:
    """(bruto R, uitgangscandle, uitkomst). Chandelier: de stop volgt het uiterste sinds de instap op k_trail ATR en gaat alleen de goede kant op.
    Een gat door de stop vult op de open. Stop eerst als open en stop samenvallen."""
    hi, lo, cl, op, atr = (b[c].to_numpy() for c in ("high", "low", "close", "open", "atr"))
    risk = abs(entry - stop0)
    stop, ext = stop0, entry
    for j in range(j0, len(cl)):
        if (lo[j] <= stop) if sign == 1 else (hi[j] >= stop):
            fill = min(op[j], stop) if sign == 1 else max(op[j], stop)
            return sign * (fill - entry) / risk, j, "stop"
        ext = max(ext, hi[j]) if sign == 1 else min(ext, lo[j])
        trail = ext - sign * k_trail * atr[j]
        stop = max(stop, trail) if sign == 1 else min(stop, trail)
    return sign * (cl[-1] - entry) / risk, len(cl) - 1, "tijd"


def exit_target(b: pd.DataFrame, j0: int, sign: int, entry: float, stop: float, target_r: float, max_bars: int) -> tuple[float, int, str]:
    hi, lo, cl = (b[c].to_numpy() for c in ("high", "low", "close"))
    risk = abs(entry - stop)
    target = entry + sign * risk * target_r
    last = min(len(cl), j0 + max_bars) - 1
    for j in range(j0, last + 1):
        if (lo[j] <= stop) if sign == 1 else (hi[j] >= stop):
            return -1.0, j, "stop"
        if (hi[j] >= target) if sign == 1 else (lo[j] <= target):
            return target_r, j, "doel"
    return sign * (cl[last] - entry) / risk, last, "tijd"


def _trade(v: Variant, b: pd.DataFrame, i: int, sign: int, cost_pct: float) -> Optional[dict]:
    """Eén trade voor een signaal op candle i, of None als er geen geldige instap of stop is."""
    atr = float(b["atr"].iloc[i])
    if not np.isfinite(atr) or atr <= 0:
        return None
    if v.family == "sweep":
        entry = float(b["close"].iloc[i])
        extreme = float(b["high"].iloc[i] if sign == -1 else b["low"].iloc[i])
        raw = extreme + 0.25 * atr if sign == -1 else extreme - 0.25 * atr
        stop = smc_eval.floor_stop("short" if sign == -1 else "long", entry, raw)
        risk = abs(entry - stop)
        if risk <= 0 or i + 1 >= len(b):
            return None
        gross, j, outcome = exit_target(b, i + 1, sign, entry, stop, v.params[1], SWEEP_MAX_BARS)
    else:
        if i + 1 >= len(b):
            return None
        entry = float(b["open"].iloc[i + 1])
        stop = entry - sign * TRAIL_K_STOP * atr
        risk = abs(entry - stop)
        gross, j, outcome = exit_trail(b, i + 1, sign, entry, stop, TRAIL_K)
    cost_r = cost_pct / 100 * entry / risk
    return {"at": b["timestamp"].iloc[i + 1 if v.family != "sweep" else i], "direction": "long" if sign == 1 else "short", "risk_pct": risk / entry * 100,
            "gross": gross, "net": gross - cost_r, "bars": j - i, "outcome": outcome, "i": i, "sign": sign}


def signals_for(v: Variant, b: pd.DataFrame) -> list[tuple[int, int]]:
    if v.family == "donchian":
        return donchian_signals(b, *v.params)
    if v.family == "pullback":
        return pullback_signals(b, *v.params)
    return sweep_signals(b, v.params[0])


def run_variant(v: Variant, bars: pd.DataFrame, cost_pct: float = 0.06) -> pd.DataFrame:
    """Alle trades van één variant op één coin; één positie tegelijk (bij een trailing-regel pas een nieuw signaal na de uitgang)."""
    b = prepare(bars)
    rows, busy_until = [], -1
    for i, sign in signals_for(v, b):
        if v.family != "sweep" and i <= busy_until:
            continue
        t = _trade(v, b, i, sign, cost_pct)
        if t is None:
            continue
        busy_until = i + t["bars"]
        rows.append(t)
    return pd.DataFrame(rows, columns=["at", "direction", "risk_pct", "gross", "net", "bars", "outcome", "i", "sign"])


def placebo_variant(v: Variant, bars: pd.DataFrame, real: pd.DataFrame, cost_pct: float = 0.06, seed: int = 0) -> pd.DataFrame:
    """Zelfde aantal trades en kantverdeling, zelfde uitgangsregel, maar op willekeurige candles. Vangt de drift van de markt: een long-regel in
    een stijgende markt hoort eerst beter te zijn dan willekeurig long gaan."""
    if real.empty:
        return real
    b = prepare(bars)
    rng = np.random.default_rng(seed)
    n = len(b)
    rows = []
    for sign in real["sign"].tolist():
        for _ in range(20):                                   # een paar pogingen voor een geldige instap
            i = int(rng.integers(WARMUP, n - 2))
            if v.family == "sweep":
                atr = float(b["atr"].iloc[i])
                entry = float(b["close"].iloc[i])
                raw = entry - sign * max(atr, entry * 0.004)
                stop = smc_eval.floor_stop("short" if sign == -1 else "long", entry, raw)
                risk = abs(entry - stop)
                if risk <= 0:
                    continue
                gross, j, outcome = exit_target(b, i + 1, sign, entry, stop, v.params[1], SWEEP_MAX_BARS)
            else:
                atr = float(b["atr"].iloc[i])
                if not np.isfinite(atr) or atr <= 0:
                    continue
                entry = float(b["open"].iloc[i + 1])
                stop = entry - sign * TRAIL_K_STOP * atr
                risk = abs(entry - stop)
                gross, j, outcome = exit_trail(b, i + 1, sign, entry, stop, TRAIL_K)
            rows.append({"net": gross - cost_pct / 100 * entry / risk, "gross": gross})
            break
    return pd.DataFrame(rows, columns=["net", "gross"])


MIN_TRADES = 500             # spec sectie 6: minder trades zeggen te weinig over een voordeel van 0,1R
MIN_PLACEBO_MARGIN = 0.03    # R per trade boven willekeurige instappen met dezelfde uitgang
MIN_HALF = MIN_TRADES // 4   # elke helft moet minstens een kwart van het minimum bevatten


def evaluate(trades: pd.DataFrame, placebo: pd.DataFrame) -> dict:
    """Oordeel over één variant over alle coins samen. 'slaagt' alleen als het gemiddelde netto resultaat in beide helften boven 0 ligt, de marge van het
    totaal boven 0 ligt en de variant beter is dan willekeurige instappen met dezelfde uitgang."""
    from app import structure_review as sr
    from app.replay import stats
    if trades.empty:
        return {"n": 0, "passes": False, "reason": "geen trades"}
    t = trades.sort_values("at")
    cut = t["at"].quantile(0.5)
    first, second = t[t["at"] < cut], t[t["at"] >= cut]
    lo, hi = sr.bootstrap_mean(t["net"].tolist())
    wlo, whi = stats.cluster_bootstrap_mean(t["net"].tolist(), [stats.week_key(x) for x in t["at"]])
    out = {"n": len(t), "avg": float(t["net"].mean()), "ci": (lo, hi), "week_ci": (wlo, whi), "gross": float(t["gross"].mean()), "total": float(t["net"].sum()),
           "winrate": float((t["net"] > 0).mean()), "median_risk_pct": float(t["risk_pct"].median()),
           "train": (len(first), float(first["net"].mean()) if len(first) else None), "test": (len(second), float(second["net"].mean()) if len(second) else None),
           "placebo": float(placebo["net"].mean()) if len(placebo) else None, "best": float(t["net"].max()), "avg_win": float(t.loc[t["net"] > 0, "net"].mean()) if (t["net"] > 0).any() else 0.0}
    checks = {"genoeg trades": len(t) >= MIN_TRADES,
              "eerste helft positief": out["train"][1] is not None and out["train"][1] > 0,
              "tweede helft positief": out["test"][1] is not None and out["test"][1] > 0,
              "marge boven 0": lo > 0,
              "marge per week boven 0": wlo > 0,
              "duidelijk beter dan willekeurig": out["placebo"] is not None and out["avg"] - out["placebo"] >= MIN_PLACEBO_MARGIN}
    out["checks"], out["passes"] = checks, all(checks.values())
    out["reason"] = "" if out["passes"] else "faalt: " + ", ".join(k for k, ok in checks.items() if not ok)
    return out
