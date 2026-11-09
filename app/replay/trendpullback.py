"""Trend plus pullback, zoals beschreven: de trend op 4 uur en 1 uur wijst één kant op, de koers maakt een impuls, trekt terug naar een zone en toont op
5 minuten een bevestiging. Dan mee met de trend. Alles vooraf vastgelegd, niets afgestemd op data.

  Trend   4u en 1u allebei: EMA21 boven (onder) EMA50 en de slotkoers erboven (eronder). Anders geen handel.
  Impuls  op 15m, in de laatste 24 candles: een beweging van laag naar hoog (bij long) van minstens 2 keer de 15m-ATR.
  Zone    de terugtrekking van 38,2 tot 78,6 procent van die impuls.
  Bevestiging  de 5m-candle raakt de zone, sluit omhoog (bij long) boven de hoogte van de vorige candle en boven de onderkant van de zone.
  Instap  slot van die 5m-candle. Stop onder de laagste laag van de laatste 30 minuten (en de zone) min een kwart 5m-ATR.
  Uitgang  doel 1,5R of 2R, of de top van de impuls (alleen als die minstens 1,5R ver ligt). Eén instap per impuls.

De functie `entries` werkt op gesloten candles van vier tijdsniveaus en wordt ook live gebruikt (app/trend_live.py), dus de toets en de melding volgen dezelfde regels."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay.lab import add_indicators, make_bars
from app.replay.outcome import resolve

IMPULSE_BARS = 24
IMPULSE_ATR = 2.0
ZONE_NEAR, ZONE_FAR = 0.382, 0.786
STOP_ATR = 0.25
STOP_LOOKBACK_5M = 6
MIN_STOP_PCT, MAX_STOP_PCT = 0.2, 2.0
MIN_TARGET_R = 1.5
MAX_AGE = pd.Timedelta(hours=12)
RR_LIST = (1.5, 2.0)
FEE_PCT, SLIP_PCT = 0.02, 0.01


def bias(bars: pd.DataFrame) -> pd.Series:
    """+1 bullish, -1 bearish, 0 geen trend, per gesloten candle."""
    close = bars["close"]
    e21, e50 = close.ewm(span=21, adjust=False).mean(), close.ewm(span=50, adjust=False).mean()
    out = np.where((e21 > e50) & (close > e50), 1, np.where((e21 < e50) & (close < e50), -1, 0))
    out[:50] = 0
    return pd.Series(out, index=bars.index)


def impulse_legs(b15: pd.DataFrame) -> pd.DataFrame:
    """Per 15m-candle de laatste impuls omhoog (up_*) en omlaag (dn_*) in het venster. Kolommen: up_hi, up_lo, up_id, dn_lo, dn_hi, dn_id (NaN als er geen is)."""
    high, low, atr = b15["high"].to_numpy(), b15["low"].to_numpy(), b15["atr"].to_numpy()
    n = len(b15)
    cols = {k: np.full(n, np.nan) for k in ("up_hi", "up_lo", "up_id", "dn_lo", "dn_hi", "dn_id")}
    for i in range(IMPULSE_BARS, n):
        if not np.isfinite(atr[i]):
            continue
        lo_w = i - IMPULSE_BARS + 1
        h, l = high[lo_w:i + 1], low[lo_w:i + 1]
        hi_i = int(np.argmax(h))
        lo_before = float(l[:hi_i + 1].min())
        if hi_i > 0 and h[hi_i] - lo_before >= IMPULSE_ATR * atr[i] and int(np.argmin(l[:hi_i + 1])) < hi_i:
            cols["up_hi"][i], cols["up_lo"][i], cols["up_id"][i] = h[hi_i], lo_before, lo_w + hi_i
        lo_i = int(np.argmin(l))
        hi_before = float(h[:lo_i + 1].max())
        if lo_i > 0 and hi_before - l[lo_i] >= IMPULSE_ATR * atr[i] and int(np.argmax(h[:lo_i + 1])) < lo_i:
            cols["dn_lo"][i], cols["dn_hi"][i], cols["dn_id"][i] = l[lo_i], hi_before, lo_w + lo_i
    return pd.DataFrame(cols, index=b15.index)


def _asof(left: pd.DataFrame, right: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Waarden van de laatst gesloten hogere-tijdsniveau-candle op het sluitmoment van elke 5m-candle."""
    r = right[["close_time", *cols]].sort_values("close_time")
    return pd.merge_asof(left[["close_time"]].sort_values("close_time"), r, on="close_time", direction="backward")[cols].set_index(left.index)


def entries(b5: pd.DataFrame, b15: pd.DataFrame, b1h: pd.DataFrame, b4h: pd.DataFrame) -> pd.DataFrame:
    """Alle instappen in de gegeven gesloten candles. b5 en b15 moeten indicatoren hebben (add_indicators). Kolommen: bar (positie in b5), at (sluitmoment),
    direction, entry, stop, impulse_extreme, impulse_id."""
    b5 = b5.reset_index(drop=True)
    b15 = b15.reset_index(drop=True)
    b4 = b4h.reset_index(drop=True).assign(bias4=bias(b4h.reset_index(drop=True)))
    b1 = b1h.reset_index(drop=True).assign(bias1=bias(b1h.reset_index(drop=True)))
    legs = impulse_legs(b15)
    b15x = pd.concat([b15[["close_time"]], legs], axis=1)
    state = pd.concat([_asof(b5, b4, ["bias4"]), _asof(b5, b1, ["bias1"]), _asof(b5, b15x, list(legs.columns))], axis=1)
    high, low, close, opn, atr = (b5[c].to_numpy() for c in ("high", "low", "close", "open", "atr"))
    out = []
    used: set = set()
    cols = {c: state[c].to_numpy() for c in state.columns}
    for j in range(STOP_LOOKBACK_5M, len(b5)):
        if not np.isfinite(atr[j]):
            continue
        s = {c: cols[c][j] for c in cols}
        for direction, ok_bias, ext, base, leg_id in (("long", s["bias4"] == 1 and s["bias1"] == 1, "up_hi", "up_lo", "up_id"),
                                                     ("short", s["bias4"] == -1 and s["bias1"] == -1, "dn_lo", "dn_hi", "dn_id")):
            if not ok_bias or not np.isfinite(s[ext]) or (direction, s[leg_id]) in used:
                continue
            leg = abs(s[ext] - s[base])
            if direction == "long":
                near, far = s[ext] - ZONE_NEAR * leg, s[ext] - ZONE_FAR * leg
                touched = far <= low[j] <= near
                confirmed = close[j] > opn[j] and close[j] > high[j - 1] and close[j] > far
                stop = min(low[j - STOP_LOOKBACK_5M + 1:j + 1].min(), far) - STOP_ATR * atr[j]
                valid = stop < close[j]
            else:
                near, far = s[ext] + ZONE_NEAR * leg, s[ext] + ZONE_FAR * leg
                touched = near <= high[j] <= far
                confirmed = close[j] < opn[j] and close[j] < low[j - 1] and close[j] < far
                stop = max(high[j - STOP_LOOKBACK_5M + 1:j + 1].max(), far) + STOP_ATR * atr[j]
                valid = stop > close[j]
            if touched and confirmed and valid:
                used.add((direction, s[leg_id]))
                out.append({"bar": j, "at": b5.at[j, "close_time"], "direction": direction, "entry": float(close[j]), "stop": float(stop),
                            "impulse_extreme": float(s[ext]), "impulse_id": float(s[leg_id])})
    return pd.DataFrame(out, columns=["bar", "at", "direction", "entry", "stop", "impulse_extreme", "impulse_id"])


def prepare(frame_1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (add_indicators(make_bars(frame_1m, 5)), add_indicators(make_bars(frame_1m, 15)), make_bars(frame_1m, 60), make_bars(frame_1m, 240))


def targets(direction: str, entry: float, stop: float, extreme: float) -> dict[str, float]:
    """Doelen per uitgangsvariant. 'impuls' alleen als de top van de impuls minstens MIN_TARGET_R ver ligt."""
    risk = abs(entry - stop)
    sign = 1 if direction == "long" else -1
    out = {f"{rr:g}R": entry + sign * risk * rr for rr in RR_LIST}
    if sign * (extreme - entry) / risk >= MIN_TARGET_R:
        out["impuls"] = extreme
    return out


def run(coin: str, frame_1m: pd.DataFrame) -> pd.DataFrame:
    """Alle trades van één coin over de uitgangsvarianten. Spiegel: dezelfde instap, andere kant, even ver stop, als controle."""
    b5, b15, b1h, b4h = prepare(frame_1m)
    ent = entries(b5, b15, b1h, b4h)
    ts = frame_1m["timestamp"]
    rows = []
    for e in ent.itertuples():
        risk_pct = abs(e.entry - e.stop) / e.entry * 100
        if not (MIN_STOP_PCT <= risk_pct <= MAX_STOP_PCT):
            continue
        lo = ts.searchsorted(e.at, side="left")
        after = frame_1m.iloc[lo:lo + int(MAX_AGE / pd.Timedelta(minutes=1)) + 2]
        for kind, direction, stop in (("mee", e.direction, e.stop), ("spiegel", "short" if e.direction == "long" else "long", e.entry + (e.entry - e.stop))):
            for name, take in targets(direction, e.entry, stop, e.impulse_extreme if kind == "mee" else float("nan")).items():
                o = resolve(direction, e.entry, stop, take, after, e.at, MAX_AGE, FEE_PCT, SLIP_PCT)
                if o is not None:
                    rows.append({"at": e.at, "coin": coin, "kind": kind, "exit": name, "direction": direction, "risk_pct": risk_pct, "win": o.result == "take_profit",
                                 "r_gross": o.r_gross, "r_net": o.r_net})
    return pd.DataFrame(rows)


@dataclass
class Row:
    kind: str
    exit: str
    n: int
    winrate: float
    gross: float
    net: float
    train: Optional[float]
    test: Optional[float]
    n_train: int
    n_test: int
    t_days: Optional[float]


def summarize(trades: pd.DataFrame, cut: pd.Timestamp) -> list[Row]:
    out = []
    for (kind, ex), g in trades.groupby(["kind", "exit"]):
        tr, te = g[g["at"] < cut], g[g["at"] >= cut]
        daily = g.groupby(g["at"].dt.floor("D"))["r_net"].mean()
        t = float(daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))) if len(daily) >= 5 and daily.std(ddof=1) > 0 else None
        out.append(Row(kind, ex, len(g), float(g["win"].mean()), float(g["r_gross"].mean()), float(g["r_net"].mean()),
                       float(tr["r_net"].mean()) if len(tr) else None, float(te["r_net"].mean()) if len(te) else None, len(tr), len(te), t))
    return out


def passes(r: Row, min_n: int = 30) -> bool:
    return r.kind == "mee" and r.n_train >= min_n and r.n_test >= min_n and (r.train or 0) > 0 and (r.test or 0) > 0 and (r.t_days or 0) > 2
