"""A+ onderzoek: bestaat er een stel kenmerken waarmee sweeps beter dan willekeurig worden, en houdt dat stand op data die
bij het kiezen niet is gebruikt? Zonder dat doen we de kenmerken alleen na op een testhelft die we al kenden.

Opzet, vastgelegd voor de uitkomst bekend was:
1. Gebeurtenissen: sweeps van echte niveaus (gisteren, vorige week, Azië, zie liquidity_levels) en van het 4-uurs zwaaipunt.
   Instap met een marktorder op de slotkoers van de sweepcandle, stop achter de wick, kosten eraf, maximaal 3 uur vasthouden.
2. Tien kenmerken met een vooraf vastgelegde richting ('meer is beter', zie HYPOTHESES). Geen enkele richting wordt achteraf omgedraaid.
3. De drempel is de mediaan van de trainhelft. Een kenmerk doet mee als de goede kant in de trainhelft minstens MIN_GAIN R beter is.
4. Score = aantal meedoende kenmerken waar een gebeurtenis aan voldoet. De score-grens kiest de trainhelft. Pas daarna kijkt de testhelft.
5. Permutatietoets: dezelfde procedure op husselde uitkomsten. De p-waarde zegt hoe vaak puur toeval even goed scoort."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import liquidity_levels as ll
from app.replay.lab import add_indicators, make_bars, trend_on
from app.replay.outcome import resolve

RR_LIST = (1.5, 2.0, 3.0)
MAX_AGE = pd.Timedelta(hours=3)
SWING_LOOKBACK = 48           # 4 uur aan 5m-candles
SWING_COOLDOWN = 24
CONFIRM_BARS = 3
TOUCH_WINDOW = 1440           # 5 dagen
TOUCH_TOL = 0.001
MIN_GAIN = 0.03
MIN_TRAIN_N = 150
KILLZONE_HOURS = (7, 8, 9, 13, 14, 15)

# (naam, wat 'goed' is). Alle richtingen zijn 'hoog is goed' behalve killzone en trend, die waar/onwaar zijn.
HYPOTHESES = ["depth_atr", "rejection", "vol_ratio", "killzone", "trend_aligned", "vol_regime", "prior_run_atr", "touches",
              "discount", "target_r"]


def swing_sweeps(bars5: pd.DataFrame) -> pd.DataFrame:
    """Sweep van het hoog of laag van de laatste 4 uur met een slotkoers terug erbinnen, met een afkoelperiode per kant."""
    hh = bars5["high"].shift(1).rolling(SWING_LOOKBACK).max()
    lo = bars5["low"].shift(1).rolling(SWING_LOOKBACK).min()
    long_hit = ((bars5["low"] < lo) & (bars5["close"] > lo)).to_numpy()
    short_hit = ((bars5["high"] > hh) & (bars5["close"] < hh)).to_numpy()
    rows, last = [], {"long": -10**9, "short": -10**9}
    for i in range(len(bars5)):
        for direction, hit, level in (("long", long_hit, lo), ("short", short_hit, hh)):
            if hit[i] and i - last[direction] >= SWING_COOLDOWN:
                last[direction] = i
                up = direction == "short"
                rows.append({"at": bars5.at[i, "close_time"], "bar": i, "kind": "SWING_H" if up else "SWING_L", "direction": direction,
                             "level": float(level.iloc[i]), "extreme": float(bars5.at[i, "high" if up else "low"]),
                             "close": float(bars5.at[i, "close"]), "atr": float(bars5.at[i, "atr"])})
    return pd.DataFrame(rows, columns=["at", "bar", "kind", "direction", "level", "extreme", "close", "atr"])


def _features(events: pd.DataFrame, bars5: pd.DataFrame, trend: np.ndarray, levels: pd.DataFrame) -> pd.DataFrame:
    close, high, low = bars5["close"].to_numpy(), bars5["high"].to_numpy(), bars5["low"].to_numpy()
    logret = np.log(bars5["close"]).diff()
    rv = logret.rolling(288).std()
    base = rv.rolling(8640, min_periods=2000).median()
    vol_regime = (rv / base).to_numpy()
    day = bars5["timestamp"].dt.floor("D")
    rows = []
    for e in events.itertuples():
        i, long = int(e.bar), e.direction == "long"
        b_high, b_low, b_close = high[i], low[i], close[i]
        span = b_high - b_low
        run = (close[max(i - 24, 0)] - close[i - 1]) if long else (close[i - 1] - close[max(i - 24, 0)])
        window = slice(max(i - TOUCH_WINDOW, 0), i)
        ref = low[window] if long else high[window]
        touches = int((np.abs(ref - e.level) <= e.level * TOUCH_TOL).sum())
        lv = levels.loc[day.iloc[i]] if day.iloc[i] in levels.index else None
        discount = np.nan
        target_r = np.nan
        if lv is not None and "PDH" in lv and pd.notna(lv.get("PDH")) and pd.notna(lv.get("PDL")) and lv["PDH"] > lv["PDL"]:
            pos = (b_close - lv["PDL"]) / (lv["PDH"] - lv["PDL"])
            discount = 1 - pos if long else pos
        plan = ll.plan_trade(e.direction, e.close, e.extreme, e.atr)
        if plan is not None and lv is not None:
            risk = abs(plan[0] - plan[1])
            names = ["PDH", "PWH", "ASIA_H"] if long else ["PDL", "PWL", "ASIA_L"]
            targets = [lv[n] for n in names if n in lv and pd.notna(lv[n]) and ((lv[n] > plan[0]) if long else (lv[n] < plan[0]))]
            if targets:
                target_r = abs((min(targets) if long else max(targets)) - plan[0]) / risk
        rows.append({
            "depth_atr": abs(e.level - e.extreme) / e.atr if e.atr else np.nan,
            "rejection": ((b_close - b_low) if long else (b_high - b_close)) / span if span > 0 else np.nan,
            "vol_ratio": bars5.at[i, "volume"] / bars5.at[i, "vol_avg"] if bars5.at[i, "vol_avg"] else np.nan,
            "killzone": bars5.at[i, "timestamp"].hour in KILLZONE_HOURS,
            "trend_aligned": bool(trend[i] == (1 if long else -1)),
            "vol_regime": vol_regime[i], "prior_run_atr": run / e.atr if e.atr else np.nan, "touches": touches,
            "discount": discount, "target_r": target_r,
        })
    return pd.concat([events.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def _after(frame: pd.DataFrame, at: pd.Timestamp) -> pd.DataFrame:
    lo = frame["timestamp"].searchsorted(at, side="left")
    return frame.iloc[lo:lo + int(MAX_AGE / pd.Timedelta(minutes=1)) + 2]


def _confirm(bars5: pd.DataFrame, e) -> Optional[tuple[float, pd.Timestamp]]:
    """Instap pas na een 5m-slotkoers voorbij de sweepcandle, binnen CONFIRM_BARS candles. (slotkoers, tijdstip) of None."""
    i, long = int(e.bar), e.direction == "long"
    ref = bars5.at[i, "high"] if long else bars5.at[i, "low"]
    for j in range(i + 1, min(i + 1 + CONFIRM_BARS, len(bars5))):
        c = bars5.at[j, "close"]
        if (c > ref) if long else (c < ref):
            return float(c), bars5.at[j, "close_time"]
    return None


def build_dataset(frame_1m: pd.DataFrame, fee_pct: float = 0.02, slippage_pct: float = 0.01) -> pd.DataFrame:
    bars5 = add_indicators(make_bars(frame_1m, 5))
    bars4h = make_bars(frame_1m, 240)
    trend = trend_on(bars5, bars4h)
    levels = ll.day_levels(bars5)
    events = pd.concat([ll.find_sweeps(bars5), swing_sweeps(bars5)], ignore_index=True)
    events = events[events["at"].notna()].sort_values("at").reset_index(drop=True)
    data = _features(events, bars5, trend, levels)
    out = {f"r{rr}": [] for rr in RR_LIST}
    out["conf_r2.0"] = []
    out["risk_pct"] = []
    for e in data.itertuples():
        plan = ll.plan_trade(e.direction, e.close, e.extreme, e.atr)
        sign = 1 if e.direction == "long" else -1
        if plan is None:
            for k in out:
                out[k].append(np.nan)
            continue
        entry, stop = plan
        risk = abs(entry - stop)
        out["risk_pct"].append(risk / entry * 100)
        after = _after(frame_1m, e.at)
        for rr in RR_LIST:
            o = resolve(e.direction, entry, stop, entry + sign * risk * rr, after, e.at, MAX_AGE, fee_pct, slippage_pct)
            out[f"r{rr}"].append(o.r_net if o else np.nan)
        conf = _confirm(bars5, e)
        value = np.nan
        if conf is not None:
            c_entry, c_at = conf
            c_plan = ll.plan_trade(e.direction, c_entry, e.extreme, e.atr)
            if c_plan is not None:
                c_risk = abs(c_plan[0] - c_plan[1])
                o = resolve(e.direction, c_plan[0], c_plan[1], c_plan[0] + sign * c_risk * 2.0, _after(frame_1m, c_at), c_at, MAX_AGE, fee_pct, slippage_pct)
                value = o.r_net if o else np.nan
        out["conf_r2.0"].append(value)
    for k, v in out.items():
        data[k] = v if len(v) == len(data) else v + [np.nan] * (len(data) - len(v))
    return data.dropna(subset=["r2.0"]).reset_index(drop=True)


def good_flags(df: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    flags = pd.DataFrame(index=df.index)
    for name in HYPOTHESES:
        if name in ("killzone", "trend_aligned"):
            flags[name] = df[name].astype(bool)
        else:
            flags[name] = df[name] > thresholds[name]
    return flags


def train_thresholds(train: pd.DataFrame) -> dict:
    return {n: float(train[n].median()) for n in HYPOTHESES if n not in ("killzone", "trend_aligned")}


@dataclass
class Result:
    chosen: list
    min_score: int
    n_train: int
    train_r: float
    n_test: int
    test_r: float


def run_pipeline(df: pd.DataFrame, rr_col: str, cut: pd.Timestamp, outcome: Optional[pd.Series] = None) -> Result:
    y = df[rr_col] if outcome is None else outcome
    train_mask = (df["at"] < cut).to_numpy()
    train, test = df[train_mask], df[~train_mask]
    thr = train_thresholds(train)
    flags = good_flags(df, thr)
    chosen = []
    for n in HYPOTHESES:
        good, bad = y[train_mask & flags[n].to_numpy()], y[train_mask & ~flags[n].to_numpy()]
        if len(good) >= 30 and len(bad) >= 30 and good.mean() - bad.mean() >= MIN_GAIN:
            chosen.append(n)
    if not chosen:
        return Result([], 0, 0, 0.0, 0, 0.0)
    score = flags[chosen].sum(axis=1).to_numpy()
    best_s, best_r = 0, -np.inf
    for s in range(1, len(chosen) + 1):
        sel = train_mask & (score >= s)
        if sel.sum() >= MIN_TRAIN_N and y[sel].mean() > best_r:
            best_s, best_r = s, float(y[sel].mean())
    if best_s == 0:
        return Result(chosen, 0, 0, 0.0, 0, 0.0)
    sel_tr, sel_te = train_mask & (score >= best_s), ~train_mask & (score >= best_s)
    return Result(chosen, best_s, int(sel_tr.sum()), float(y[sel_tr].mean()), int(sel_te.sum()),
                  float(y[sel_te].mean()) if sel_te.any() else 0.0)


def permutation_p(df: pd.DataFrame, rr_col: str, cut: pd.Timestamp, real: Result, n: int = 200, seed: int = 0) -> float:
    """Aandeel husselruns waarvan het testresultaat minstens zo goed is als het echte."""
    rng = np.random.default_rng(seed)
    values = df[rr_col].to_numpy()
    better = 0
    for _ in range(n):
        shuffled = pd.Series(rng.permutation(values), index=df.index)
        r = run_pipeline(df, rr_col, cut, shuffled)
        if r.n_test >= max(30, real.n_test // 2) and r.test_r >= real.test_r:
            better += 1
    return better / n


def feature_table(df: pd.DataFrame, rr_col: str, cut: pd.Timestamp) -> list[dict]:
    train_mask = (df["at"] < cut).to_numpy()
    thr = train_thresholds(df[train_mask])
    flags = good_flags(df, thr)
    y = df[rr_col]
    rows = []
    for n in HYPOTHESES:
        row = {"feature": n, "threshold": thr.get(n)}
        for label, mask in (("train", train_mask), ("test", ~train_mask)):
            g, b = y[mask & flags[n].to_numpy()], y[mask & ~flags[n].to_numpy()]
            row[f"{label}_good"], row[f"{label}_bad"] = (float(g.mean()) if len(g) else np.nan, float(b.mean()) if len(b) else np.nan)
            row[f"{label}_n"] = (len(g), len(b))
        rows.append(row)
    return rows
