"""Sessie-toets: de London- en New York-sessie als structuur, zoals een sessie-indicator ze tekent. Vier vooraf vastgelegde ideeën:

  ORB    Opening range van New York (eerste 30 minuten vanaf 9:30 Eastern). Slot van een 5m-candle erbuiten in de 2 uur erna: mee (follow),
         stop aan de andere kant van de range. De spiegel (zelfde instap, omgekeerde kant, even ver stop) is de controle.
  SWEEP  New York prikt door de London-hoog of -laag en sluit terug: tegen de prik in (fade), stop achter de wick. Spiegel als controle.
  LONDON De richting van London (slot min open) tegenover de richting van New York (open tot 60 of 120 minuten later): mee en tegen.
  UREN   Gemiddeld rendement per uur van de dag, per helft, om te zien welke uren stabiel dezelfde kant op wijzen.

Tijden volgen de zomer- en wintertijd van Londen en New York. Alleen werkdagen. Kosten 0,06% per rondreis, R na kosten, stop eerst bij gelijktijdig raken
(app/replay/outcome.py). Train en test op tijd, een t-waarde per dag over coins heen."""
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.replay.lab import add_indicators, make_bars
from app.replay.outcome import resolve

LONDON_TZ, NEW_YORK_TZ = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
RR_LIST = (1.0, 1.5, 2.0)
OR_MINUTES = 30
ENTRY_WINDOW_MIN = 120
MAX_AGE = pd.Timedelta(hours=3)
MIN_STOP_PCT, MAX_STOP_PCT = 0.2, 2.0
STOP_ATR = 0.25
FEE_PCT, SLIP_PCT = 0.02, 0.01


def _utc(day: date, t: time, tz: ZoneInfo) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day, t, tzinfo=tz).astimezone(ZoneInfo("UTC")))


def session_times(day: date) -> dict:
    return {"london": (_utc(day, time(8, 0), LONDON_TZ), _utc(day, time(16, 30), LONDON_TZ)),
            "ny": (_utc(day, time(9, 30), NEW_YORK_TZ), _utc(day, time(16, 0), NEW_YORK_TZ))}


def window(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    lo = frame["timestamp"].searchsorted(start, side="left")
    hi = frame["timestamp"].searchsorted(end, side="left")
    return frame.iloc[lo:hi]


def weekdays(frame: pd.DataFrame) -> list[date]:
    days = pd.date_range(frame["timestamp"].iloc[0].normalize() + pd.Timedelta(days=1), frame["timestamp"].iloc[-1].normalize() - pd.Timedelta(days=1), freq="D")
    return [d.date() for d in days if d.weekday() < 5]


def _row(coin: str, variant: str, direction: str, entry: float, stop: float, at: pd.Timestamp, frame: pd.DataFrame) -> list[dict]:
    risk_pct = abs(entry - stop) / entry * 100
    if not (MIN_STOP_PCT <= risk_pct <= MAX_STOP_PCT) or (direction == "long" and stop >= entry) or (direction == "short" and stop <= entry):
        return []
    sign = 1 if direction == "long" else -1
    after = window(frame, at, at + MAX_AGE + pd.Timedelta(minutes=1))
    out = []
    for rr in RR_LIST:
        o = resolve(direction, entry, stop, entry + sign * abs(entry - stop) * rr, after, at, MAX_AGE, FEE_PCT, SLIP_PCT)
        if o is not None:
            out.append({"at": at, "coin": coin, "variant": variant, "rr": rr, "win": o.result == "take_profit", "r_gross": o.r_gross, "r_net": o.r_net})
    return out


def _mirror(direction: str, entry: float, stop: float) -> tuple[str, float]:
    return ("short" if direction == "long" else "long"), entry + (entry - stop)


def orb_trades(coin: str, frame: pd.DataFrame) -> list[dict]:
    rows = []
    for day in weekdays(frame):
        t0 = session_times(day)["ny"][0]
        opening = window(frame, t0, t0 + pd.Timedelta(minutes=OR_MINUTES))
        if len(opening) < OR_MINUTES - 3:
            continue
        hi, lo = float(opening["high"].max()), float(opening["low"].min())
        bars = make_bars(window(frame, t0 + pd.Timedelta(minutes=OR_MINUTES), t0 + pd.Timedelta(minutes=OR_MINUTES + ENTRY_WINDOW_MIN)), 5)
        for b in bars.itertuples():
            if b.close > hi:
                direction, stop = "long", lo
            elif b.close < lo:
                direction, stop = "short", hi
            else:
                continue
            rows += _row(coin, "ORB mee", direction, b.close, stop, b.close_time, frame)
            m_dir, m_stop = _mirror(direction, b.close, stop)
            rows += _row(coin, "ORB spiegel", m_dir, b.close, m_stop, b.close_time, frame)
            break
    return rows


def sweep_trades(coin: str, frame: pd.DataFrame) -> list[dict]:
    rows = []
    for day in weekdays(frame):
        t = session_times(day)
        london = window(frame, *t["london"])
        if len(london) < 400:
            continue
        l_hi, l_lo = float(london["high"].max()), float(london["low"].min())
        start = max(t["london"][1], t["ny"][0])
        bars = add_indicators(make_bars(window(frame, t["london"][0], t["ny"][1]), 5))
        bars = bars[bars["timestamp"] >= start]
        seen = set()
        for b in bars.itertuples():
            if not np.isfinite(b.atr):
                continue
            for level, up in ((l_hi, True), (l_lo, False)):
                key = "hi" if up else "lo"
                swept = (b.high > level and b.close < level) if up else (b.low < level and b.close > level)
                if swept and key not in seen:
                    seen.add(key)
                    direction = "short" if up else "long"
                    stop = b.high + STOP_ATR * b.atr if up else b.low - STOP_ATR * b.atr
                    rows += _row(coin, "SWEEP fade", direction, b.close, stop, b.close_time, frame)
                    m_dir, m_stop = _mirror(direction, b.close, stop)
                    rows += _row(coin, "SWEEP spiegel", m_dir, b.close, m_stop, b.close_time, frame)
    return rows


def summarize(trades: pd.DataFrame, cut: pd.Timestamp) -> list[dict]:
    out = []
    for (variant, rr), g in trades.groupby(["variant", "rr"]):
        tr, te = g[g["at"] < cut], g[g["at"] >= cut]
        daily = g.groupby(g["at"].dt.floor("D"))["r_net"].mean()
        t = float(daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily)))) if len(daily) >= 5 and daily.std(ddof=1) > 0 else None
        out.append({"variant": variant, "rr": rr, "n": len(g), "winrate": float(g["win"].mean()), "gross": float(g["r_gross"].mean()), "net": float(g["r_net"].mean()),
                    "train": float(tr["r_net"].mean()) if len(tr) else None, "test": float(te["r_net"].mean()) if len(te) else None,
                    "n_train": len(tr), "n_test": len(te), "t_days": t})
    return out


def passes(r: dict, min_n: int = 30) -> bool:
    return (r["n_train"] >= min_n and r["n_test"] >= min_n and r["train"] is not None and r["test"] is not None
            and r["train"] > 0 and r["test"] > 0 and (r["t_days"] or 0) > 2)


def london_to_ny(coin: str, frame: pd.DataFrame, horizons=(60, 120), cost_bp: float = 6.0) -> pd.DataFrame:
    """Richting van London tegenover het rendement van New York na de opening. Eén rij per dag, horizon en kant (mee of tegen)."""
    rows = []
    for day in weekdays(frame):
        t = session_times(day)
        london = window(frame, *t["london"])
        if len(london) < 400:
            continue
        sign = np.sign(float(london["close"].iloc[-1]) - float(london["open"].iloc[0]))
        if sign == 0:
            continue
        for h in horizons:
            seg = window(frame, t["ny"][0], t["ny"][0] + pd.Timedelta(minutes=h + 1))
            if len(seg) < h:
                continue
            move = (float(seg["close"].iloc[h - 1]) / float(seg["open"].iloc[0]) - 1) * 1e4
            for side, mult in (("mee", 1.0), ("tegen", -1.0)):
                gross = sign * mult * move
                rows.append({"at": t["ny"][0], "coin": coin, "variant": f"LONDON {side} {h}m", "gross_bp": gross, "net_bp": gross - cost_bp})
    return pd.DataFrame(rows)


def hour_map(frames: dict[str, pd.DataFrame], cut: pd.Timestamp) -> pd.DataFrame:
    """Gemiddeld rendement per UTC-uur (bp), over coins gemiddeld per dag, met t-waarde per helft."""
    daily = {}
    for coin, f in frames.items():
        g = f.set_index("timestamp")[["open", "close"]].resample("1h").agg({"open": "first", "close": "last"}).dropna()
        daily[coin] = (g["close"] / g["open"] - 1) * 1e4
    panel = pd.DataFrame(daily).mean(axis=1)
    out = []
    for hour in range(24):
        s = panel[panel.index.hour == hour]
        row = {"uur": hour}
        for label, part in (("train", s[s.index < cut]), ("test", s[s.index >= cut])):
            row[f"{label}_bp"] = float(part.mean())
            row[f"{label}_t"] = float(part.mean() / (part.std(ddof=1) / np.sqrt(len(part)))) if len(part) > 5 and part.std(ddof=1) > 0 else None
        out.append(row)
    return pd.DataFrame(out)
