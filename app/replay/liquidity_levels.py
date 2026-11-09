"""Toets van sweeps op echte liquiditeitsniveaus: hoog en laag van gisteren (PDH, PDL), van vorige week (PWH, PWL) en de
range van de Azië-sessie (00:00 tot 07:00 UTC). Daar staan de stops van veel handelaren, anders dan bij de gewone
zwaaipunten van de SMC-regel. Een sweep telt als de koers een niveau doorsteekt en dezelfde 5m-candle terug sluit.

Instap op de slotkoers van die candle (marktorder, geen gunstiger limietprijs), stop achter de wick plus een marge, take als
veelvoud van de stop. Eerste sweep per niveau per dag. Alleen informatie van gesloten candles. Resultaten in R, kosten
eraf, train en test apart, met een controle op willekeurige momenten met dezelfde stopafstand."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay.lab import add_indicators, make_bars
from app.replay.outcome import resolve

RR_LIST = (1.0, 1.5, 2.0, 3.0)
STOP_ATR = 0.5            # marge achter de wick, in 5m-ATR
MIN_STOP_PCT = 0.2        # zelfde ondergrens als SMC_MIN_STOP_PCT: ruis binnen een candle is geen trade
MAX_AGE = pd.Timedelta(hours=24)
WINDOWS = {"PDH": (7, 21), "PDL": (7, 21), "PWH": (7, 21), "PWL": (7, 21), "ASIA_H": (7, 16), "ASIA_L": (7, 16)}
SWEEPS_UP = {"PDH", "PWH", "ASIA_H"}          # een niveau boven de prijs: sweep omhoog geeft een short


def day_levels(bars5: pd.DataFrame) -> pd.DataFrame:
    """Per UTC-dag de niveaus die op dat moment al vaststaan: gisteren, vorige week, en de Azië-range van die dag."""
    b = bars5.copy()
    b["day"] = b["timestamp"].dt.floor("D")
    daily = b.groupby("day").agg(high=("high", "max"), low=("low", "min"))
    b["week"] = b["day"] - pd.to_timedelta(b["day"].dt.weekday, unit="D")
    weekly = b.groupby("week").agg(high=("high", "max"), low=("low", "min"))
    asia = b[b["timestamp"].dt.hour < 7].groupby("day").agg(high=("high", "max"), low=("low", "min"))
    rows = []
    for day in daily.index:
        week = day - pd.Timedelta(days=day.weekday())
        prev_day = day - pd.Timedelta(days=1)
        prev_week = week - pd.Timedelta(days=7)
        row = {"day": day}
        if prev_day in daily.index:
            row["PDH"], row["PDL"] = daily.at[prev_day, "high"], daily.at[prev_day, "low"]
        if prev_week in weekly.index:
            row["PWH"], row["PWL"] = weekly.at[prev_week, "high"], weekly.at[prev_week, "low"]
        if day in asia.index:
            row["ASIA_H"], row["ASIA_L"] = asia.at[day, "high"], asia.at[day, "low"]
        rows.append(row)
    return pd.DataFrame(rows).set_index("day")


def find_sweeps(bars5: pd.DataFrame) -> pd.DataFrame:
    """Eerste sweep per niveau per dag binnen het tijdvenster. Kolommen: at (sluitmoment), kind, direction, level, extreme."""
    levels = day_levels(bars5)
    b = bars5.reset_index(drop=True)
    day = b["timestamp"].dt.floor("D")
    hour = b["timestamp"].dt.hour
    out = []
    for kind, (h0, h1) in WINDOWS.items():
        if kind not in levels.columns:
            continue
        level = day.map(levels[kind])
        in_window = (hour >= h0) & (hour < h1) & level.notna()
        if kind in SWEEPS_UP:
            hit = in_window & (b["high"] > level) & (b["close"] < level)
        else:
            hit = in_window & (b["low"] < level) & (b["close"] > level)
        first = hit[hit].groupby(day[hit]).head(1)
        for i in first.index:
            up = kind in SWEEPS_UP
            out.append({"at": b.at[i, "close_time"], "bar": i, "kind": kind, "direction": "short" if up else "long",
                        "level": float(level[i]), "extreme": float(b.at[i, "high"] if up else b.at[i, "low"]),
                        "close": float(b.at[i, "close"]), "atr": float(b.at[i, "atr"])})
    return pd.DataFrame(out, columns=["at", "bar", "kind", "direction", "level", "extreme", "close", "atr"])


def plan_trade(direction: str, close: float, extreme: float, atr: float) -> Optional[tuple[float, float]]:
    """(entry, stop) of None als de stop te dichtbij ligt. Stop achter de wick plus STOP_ATR keer de 5m-ATR."""
    stop = extreme - STOP_ATR * atr if direction == "long" else extreme + STOP_ATR * atr
    risk = close - stop if direction == "long" else stop - close
    if risk <= 0 or risk / close * 100 < MIN_STOP_PCT:
        return None
    return close, stop


@dataclass
class Row:
    kind: str
    rr: float
    n: int
    winrate: float
    gross: float
    net: float
    train_net: Optional[float]
    test_net: Optional[float]
    n_train: int
    n_test: int
    placebo_net: float


def _after(frame: pd.DataFrame, at: pd.Timestamp) -> pd.DataFrame:
    lo = frame["timestamp"].searchsorted(at, side="left")
    return frame.iloc[lo:lo + int(MAX_AGE / pd.Timedelta(minutes=1)) + 2]


def run(frame_1m: pd.DataFrame, fee_pct: float = 0.02, slippage_pct: float = 0.01) -> pd.DataFrame:
    """Alle trades van één coin: één rij per sweep en take-variant."""
    bars = add_indicators(make_bars(frame_1m, 5))
    sweeps = find_sweeps(bars)
    rows = []
    for s in sweeps.itertuples():
        plan = plan_trade(s.direction, s.close, s.extreme, s.atr)
        if plan is None:
            continue
        entry, stop = plan
        risk = abs(entry - stop)
        after = _after(frame_1m, s.at)
        sign = 1 if s.direction == "long" else -1
        for rr in RR_LIST:
            o = resolve(s.direction, entry, stop, entry + sign * risk * rr, after, s.at, MAX_AGE, fee_pct, slippage_pct)
            if o is not None:
                rows.append({"at": s.at, "kind": s.kind, "direction": s.direction, "rr": rr, "risk_pct": risk / entry * 100,
                             "win": o.result == "take_profit", "r_gross": o.r_gross, "r_net": o.r_net})
    return pd.DataFrame(rows)


def placebo(frame_1m: pd.DataFrame, trades: pd.DataFrame, fee_pct: float, slippage_pct: float, seed: int = 0) -> pd.DataFrame:
    """Zelfde aantal trades, zelfde stopafstand en take, maar op willekeurige 5m-momenten in dezelfde uren, met willekeurige kant."""
    if trades.empty:
        return trades
    rng = np.random.default_rng(seed)
    bars = make_bars(frame_1m, 5)
    rows = []
    for t in trades.itertuples():
        pool = bars[bars["timestamp"].dt.hour == t.at.hour]
        if pool.empty:
            continue
        b = pool.iloc[int(rng.integers(0, len(pool)))]
        direction = "long" if rng.random() < 0.5 else "short"
        entry = float(b["close"])
        risk = entry * t.risk_pct / 100
        sign = 1 if direction == "long" else -1
        o = resolve(direction, entry, entry - sign * risk, entry + sign * risk * t.rr, _after(frame_1m, b["close_time"]), b["close_time"],
                    MAX_AGE, fee_pct, slippage_pct)
        if o is not None:
            rows.append({"kind": t.kind, "rr": t.rr, "r_net": o.r_net})
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame, placebos: pd.DataFrame, cut: pd.Timestamp, min_n: int = 30) -> list[Row]:
    out = []
    for (kind, rr), g in list(trades.groupby(["kind", "rr"])) + [(("ALLES", rr), g) for rr, g in trades.groupby("rr")]:
        tr, te = g[g["at"] < cut], g[g["at"] >= cut]
        p = placebos[(placebos["rr"] == rr) & ((placebos["kind"] == kind) | (kind == "ALLES"))] if not placebos.empty else placebos
        out.append(Row(kind, rr, len(g), float(g["win"].mean()), float(g["r_gross"].mean()), float(g["r_net"].mean()),
                       float(tr["r_net"].mean()) if len(tr) else None, float(te["r_net"].mean()) if len(te) else None,
                       len(tr), len(te), float(p["r_net"].mean()) if len(p) else 0.0))
    return out


def passes(r: Row, min_n: int = 30) -> bool:
    return (r.n_train >= min_n and r.n_test >= min_n and r.train_net is not None and r.test_net is not None
            and r.train_net > 0 and r.test_net > 0)
