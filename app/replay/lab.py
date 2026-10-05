"""Testbank voor eenvoudige instap-regels op 15m en 30m. Doel: meten of een regel
een voorsprong heeft, los van de SMC- en day_trading-logica van het live systeem.

Elke regel geeft een lang- of kortsignaal op het moment dat een tf-candle sluit (alleen
informatie van gesloten candles, de 4u-trend alleen uit gesloten 4u-candles). De trade
start op de open van de eerstvolgende 1m-candle, met stop op STOP_ATR x ATR en take op
1R, 1,5R en 2R. Stop gaat voor als beide in dezelfde 1m-candle geraakt worden, zoals in
de rest van het meetraam. Na MAX_HOLD sluit de trade tegen de slotprijs."""
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

MAX_HOLD = pd.Timedelta(hours=24)
RR_LIST = (1.0, 1.5, 2.0)
STOP_ATR = 1.5
COOLDOWN_BARS = 8
BREAKOUT_LOOKBACK = 20
ENTRY_GAP = pd.Timedelta(minutes=5)
SESSION_STARTS_UTC = (8, 14)
SESSION_WINDOW = pd.Timedelta(hours=3)
SESSION_RANGE_MINUTES = 30

_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def _naive(ts: pd.Timestamp) -> np.datetime64:
    return ts.tz_convert("UTC").tz_localize(None).to_datetime64()


def make_bars(frame_1m: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Gesloten candles van `minutes` minuten uit 1m-data; de laatste, mogelijk onvolledige, valt weg."""
    bars = (frame_1m.set_index("timestamp").resample(f"{minutes}min", origin="epoch", label="left", closed="left")
            .agg(_AGG).dropna().reset_index())
    bars["close_time"] = bars["timestamp"] + pd.Timedelta(minutes=minutes)
    last_seen = frame_1m["timestamp"].iloc[-1] + pd.Timedelta(minutes=1)
    return bars[bars["close_time"] <= last_seen].reset_index(drop=True)


def _wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    b = bars.copy()
    prev_close = b["close"].shift(1)
    true_range = pd.concat([b["high"] - b["low"], (b["high"] - prev_close).abs(), (b["low"] - prev_close).abs()], axis=1).max(axis=1)
    b["atr"] = _wilder(true_range, 14)
    delta = b["close"].diff()
    b["rsi"] = 100 - 100 / (1 + _wilder(delta.clip(lower=0), 14) / _wilder((-delta).clip(lower=0), 14).replace(0, np.nan))
    b["ema21"] = b["close"].ewm(span=21, adjust=False).mean()
    b["hh"] = b["high"].shift(1).rolling(BREAKOUT_LOOKBACK).max()
    b["ll"] = b["low"].shift(1).rolling(BREAKOUT_LOOKBACK).min()
    b["vol_avg"] = b["volume"].shift(1).rolling(BREAKOUT_LOOKBACK).mean()
    return b


def trend_on(bars: pd.DataFrame, bars_4h: pd.DataFrame) -> np.ndarray:
    """+1 als op het sluitmoment van elke tf-candle de laatst gesloten 4u-candle een stijgende trend
    (EMA21 boven EMA50) had, -1 bij dalend, 0 als er nog geen 4u-trend is."""
    four = bars_4h[["close_time", "close"]].copy()
    four["trend"] = np.where(four["close"].ewm(span=21, adjust=False).mean() > four["close"].ewm(span=50, adjust=False).mean(), 1, -1)
    four.loc[:49, "trend"] = 0
    merged = pd.merge_asof(bars[["close_time"]], four[["close_time", "trend"]], on="close_time", direction="backward")
    return merged["trend"].fillna(0).to_numpy()


def _rule_pullback(b, trend):
    up = (trend == 1) & (b["low"] <= b["ema21"]) & (b["close"] > b["ema21"]) & (b["close"] > b["open"])
    down = (trend == -1) & (b["high"] >= b["ema21"]) & (b["close"] < b["ema21"]) & (b["close"] < b["open"])
    return up.to_numpy(), down.to_numpy()


def _rule_breakout(b, trend):
    vol = b["volume"] > 1.5 * b["vol_avg"]
    return ((b["close"] > b["hh"]) & vol).to_numpy(), ((b["close"] < b["ll"]) & vol).to_numpy()


def _rule_breakout_trend(b, trend):
    up, down = _rule_breakout(b, trend)
    return up & (trend == 1), down & (trend == -1)


def _rule_sweep(b, trend):
    span = (b["high"] - b["low"]).replace(0, np.nan)
    up = (b["low"] < b["ll"]) & (b["close"] > b["ll"]) & ((b["close"] - b["low"]) / span > 0.6)
    down = (b["high"] > b["hh"]) & (b["close"] < b["hh"]) & ((b["high"] - b["close"]) / span > 0.6)
    return up.to_numpy(), down.to_numpy()


def _rule_sweep_trend(b, trend):
    up, down = _rule_sweep(b, trend)
    return up & (trend == 1), down & (trend == -1)


def _rule_rsi(b, trend):
    return ((b["rsi"] < 25) & (b["close"] > b["open"])).to_numpy(), ((b["rsi"] > 75) & (b["close"] < b["open"])).to_numpy()


def _rule_session(b, trend):
    """Eerste sluiting buiten de range van de eerste 30 minuten van een sessie, binnen 3 uur."""
    ts = b["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    close, high, low = b["close"].to_numpy(), b["high"].to_numpy(), b["low"].to_numpy()
    minutes = int((b["close_time"].iloc[0] - b["timestamp"].iloc[0]).total_seconds() // 60)
    n_range = SESSION_RANGE_MINUTES // minutes
    long_mask = np.zeros(len(b), dtype=bool)
    short_mask = np.zeros(len(b), dtype=bool)
    if n_range < 1:
        return long_mask, short_mask
    days = pd.date_range(b["timestamp"].iloc[0].normalize(), b["timestamp"].iloc[-1].normalize(), freq="D", tz="UTC")
    for day in days:
        for hour in SESSION_STARTS_UTC:
            t0 = _naive(day + pd.Timedelta(hours=hour))
            first = int(np.searchsorted(ts, t0, side="left"))
            if first + n_range >= len(b) or ts[first] != t0:
                continue
            hi, lo = high[first:first + n_range].max(), low[first:first + n_range].min()
            end = int(np.searchsorted(ts, t0 + SESSION_WINDOW.to_timedelta64(), side="left"))
            for i in range(first + n_range, min(end, len(b))):
                if close[i] > hi:
                    long_mask[i] = True
                    break
                if close[i] < lo:
                    short_mask[i] = True
                    break
    return long_mask, short_mask


def _rule_random(b, trend):
    """Controle: willekeurige instap (2% van de candles), afgeleid van het tijdstip zodat het
    resultaat niet afhangt van hoeveel data er is. Hoort netto ongeveer minus de kosten te scoren."""
    minutes = (b["close_time"].dt.tz_convert("UTC").dt.tz_localize(None).astype("int64") // 60_000_000_000).to_numpy()
    pick = (minutes * 2654435761 % 1000) < 20
    direction = (minutes * 40503 // 7 % 2) == 0
    return pick & direction, pick & ~direction


RULES: dict[str, Callable] = {
    "pullback_trend": _rule_pullback,
    "uitbraak": _rule_breakout,
    "uitbraak_trend": _rule_breakout_trend,
    "sweep_terugkeer": _rule_sweep,
    "sweep_terugkeer_trend": _rule_sweep_trend,
    "rsi_uitersten": _rule_rsi,
    "sessie_opening": _rule_session,
    "controle_willekeurig": _rule_random,
}


def signal_bars(b: pd.DataFrame, trend: np.ndarray, rule: str) -> list[tuple[int, str]]:
    """(index van de tf-candle, richting), met een afkoelperiode per richting."""
    long_mask, short_mask = RULES[rule](b, trend)
    out, last = [], {"long": -10**9, "short": -10**9}
    for i in np.flatnonzero(long_mask | short_mask):
        for direction, mask in (("long", long_mask), ("short", short_mask)):
            if mask[i] and i - last[direction] >= COOLDOWN_BARS and not np.isnan(b["atr"].iloc[i]):
                last[direction] = i
                out.append((int(i), direction))
    return out


@dataclass
class Arrays:
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @classmethod
    def from_frame(cls, f: pd.DataFrame) -> "Arrays":
        return cls(f["timestamp"].to_numpy(), f["open"].to_numpy(), f["high"].to_numpy(), f["low"].to_numpy(), f["close"].to_numpy())


def resolve_many(direction: str, entry: float, stop: float, rr_list, a: Arrays, start: int, end: int,
                 fee_pct: float, slippage_pct: float) -> list[tuple[str, float, float]]:
    """Per rr (result, r_gross, r_net) over de 1m-candles [start, end). Zelfde regels als outcome.resolve."""
    risk = abs(entry - stop)
    sign = 1 if direction == "long" else -1
    h, l = a.high[start:end], a.low[start:end]
    n = len(h)
    stop_hits = (l <= stop) if sign == 1 else (h >= stop)
    first_stop = int(stop_hits.argmax()) if stop_hits.any() else n
    cost_r = 2 * (fee_pct + slippage_pct) / 100 * entry / risk
    out = []
    for rr in rr_list:
        take = entry + sign * risk * rr
        take_hits = (h >= take) if sign == 1 else (l <= take)
        first_take = int(take_hits.argmax()) if take_hits.any() else n
        if first_stop < n and first_stop <= first_take:
            out.append(("stop_loss", -1.0, -1.0 - cost_r))
        elif first_take < n:
            out.append(("take_profit", float(rr), float(rr) - cost_r))
        else:
            gross = sign * (a.close[end - 1] - entry) / risk
            out.append(("expired", float(gross), float(gross) - cost_r))
    return out


def run_rule(coin: str, rule: str, tf_minutes: int, bars: pd.DataFrame, trend: np.ndarray, a: Arrays,
             start: pd.Timestamp, end: pd.Timestamp, fee_pct: float, slippage_pct: float) -> list[dict]:
    rows = []
    ts_start, ts_end = _naive(start), _naive(end)
    for i, direction in signal_bars(bars, trend, rule):
        close_time = bars["close_time"].iloc[i]
        t64 = _naive(close_time)
        if t64 < ts_start or t64 >= ts_end:
            continue
        s = int(np.searchsorted(a.ts, t64, side="left"))
        e = int(np.searchsorted(a.ts, _naive(close_time + MAX_HOLD), side="left"))
        if s >= len(a.ts) or e - s < 2 or a.ts[s] - t64 > ENTRY_GAP.to_timedelta64():
            continue
        entry = float(a.open[s])
        risk = STOP_ATR * float(bars["atr"].iloc[i])
        if risk <= 0 or risk >= entry:
            continue
        stop = entry - risk if direction == "long" else entry + risk
        for rr, (result, gross, net) in zip(RR_LIST, resolve_many(direction, entry, stop, RR_LIST, a, s, e, fee_pct, slippage_pct)):
            rows.append({"coin": coin, "rule": rule, "tf": tf_minutes, "direction": direction, "at": close_time,
                         "risk_pct": risk / entry * 100, "rr": rr, "result": result, "r_gross": gross, "r_net": net})
    return rows


def evaluate_coin(coin: str, frame_1m: pd.DataFrame, tfs, rules, start, end, fee_pct, slippage_pct) -> list[dict]:
    a = Arrays.from_frame(frame_1m.assign(timestamp=frame_1m["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)))
    bars_4h = make_bars(frame_1m, 240)
    rows = []
    for tf in tfs:
        bars = add_indicators(make_bars(frame_1m, tf))
        trend = trend_on(bars, bars_4h)
        for rule in rules:
            rows += run_rule(coin, rule, tf, bars, trend, a, start, end, fee_pct, slippage_pct)
    return rows


def summarize(trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, train_fraction: float = 0.7,
              min_trades: int = 100, min_coin_trades: int = 10) -> pd.DataFrame:
    """Eén regel per (regel, tf, rr). `kandidaat` als netto in train en test positief is, er minstens
    min_trades trades zijn en minstens 70% van de coins met genoeg trades netto positief is."""
    cut = start + (end - start) * train_fraction
    years = (end - start).total_seconds() / (365 * 86400)
    out = []
    for (rule, tf, rr), g in trades.groupby(["rule", "tf", "rr"]):
        train, test = g[g["at"] < cut], g[g["at"] >= cut]
        done = g[g["result"] != "expired"]
        per_coin = g.groupby("coin")["r_net"].agg(["mean", "size"])
        per_coin = per_coin[per_coin["size"] >= min_coin_trades]
        coins_pos = int((per_coin["mean"] > 0).sum())
        coins_all = len(per_coin)
        ok = (len(g) >= min_trades and len(train) and len(test) and train["r_net"].mean() > 0 and test["r_net"].mean() > 0
              and coins_all > 0 and coins_pos >= 0.7 * coins_all)
        out.append({
            "regel": rule, "tf": tf, "take_R": rr, "trades": len(g), "per_jaar": len(g) / years,
            "winrate": float((done["result"] == "take_profit").mean()) if len(done) else np.nan,
            "bruto": g["r_gross"].mean(), "netto": g["r_net"].mean(),
            "netto_train": train["r_net"].mean() if len(train) else np.nan,
            "netto_test": test["r_net"].mean() if len(test) else np.nan,
            "coins_positief": f"{coins_pos}/{coins_all}", "kandidaat": bool(ok),
        })
    return pd.DataFrame(out)
