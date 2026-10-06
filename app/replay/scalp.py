"""Scalp-toets op 1m: vier ideeën waarvan de informatie niet in een gewoon candle-patroon zit, elk als gebeurtenis met een
vaste uitgang na H minuten. Alles vooraf vastgelegd, drempels uit de trainhelft, kosten in basispunten.

  LEAD   BTC maakt een uitschieter in k minuten en de alt heeft nog niet meebewogen: de alt loopt achter. Instap in de richting van BTC.
  FADE   Uitputtingsminuut: een enorme range met enorm volume en een lange lont (een liquidatiegolf lijkt zo). Instap tegen de minuut in.
  FOLLOW Dezelfde minuut maar mee. Controle: als FADE werkt en FOLLOW niet, is het geen toeval van de uitgang.
  FLOW   Uitschieter in taker-delta (wie duwt) over k minuten: mee en tegen. Alleen als de flow-cache er is.

Instap op de open van de minuut ná de gebeurtenis, uitgang op de slotkoers H minuten later. Kosten 6 bp (taker) en 4 bp (met limietorders);
het slagen-criterium gebruikt de strenge 6 bp. Een controle op willekeurige minuten in hetzelfde uur van de dag staat ernaast."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

HORIZONS = (3, 5, 10)
LEAD_K = (1, 3, 5)
TOP_Q = 0.99
MIN_GAP = 10
BETA_WINDOW = 1440
WICK_MIN = 0.3
LAG_FRACTION = 0.5
COST_TAKER_BP = 6.0
COST_MAKER_BP = 4.0
SPIKE_WINDOW = 60


def align(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Alle coins op dezelfde minuut-index, ontbrekende minuten als NaN: schuiven en rollen blijven dan in minuten rekenen."""
    start = max(f["timestamp"].iloc[0] for f in frames.values())
    end = min(f["timestamp"].iloc[-1] for f in frames.values())
    index = pd.date_range(start, end, freq="1min", tz="UTC")
    return {c: f.set_index("timestamp")[["open", "high", "low", "close", "volume"]].reindex(index) for c, f in frames.items()}


def _trades(frame: pd.DataFrame, idx: np.ndarray, direction: np.ndarray, horizon: int) -> pd.DataFrame:
    """Brutorendement in bp van instap op de open van de volgende minuut tot de slotkoers `horizon` minuten later."""
    o, c = frame["open"].to_numpy(), frame["close"].to_numpy()
    entry_i, exit_i = idx + 1, idx + horizon
    ok = exit_i < len(c)
    idx, direction, entry_i, exit_i = idx[ok], direction[ok], entry_i[ok], exit_i[ok]
    gross = direction * (c[exit_i] / o[entry_i] - 1) * 1e4
    keep = np.isfinite(gross)
    return pd.DataFrame({"at": frame.index[idx[keep]], "hour": frame.index[idx[keep]].hour, "gross_bp": gross[keep],
                         "direction": direction[keep], "i": idx[keep]})


def _decluster(candidates: np.ndarray) -> np.ndarray:
    out, last = [], -10 ** 9
    for i in candidates:
        if i - last >= MIN_GAP:
            out.append(i)
            last = i
    return np.array(out, dtype=int)


def _train_mask(index: pd.DatetimeIndex, cut: pd.Timestamp) -> np.ndarray:
    return np.asarray(index < cut)


def lead_events(btc: pd.DataFrame, alt: pd.DataFrame, k: int, cut: pd.Timestamp, need_lag: bool) -> tuple[np.ndarray, np.ndarray]:
    """(indices, richting). De drempel is het TOP_Q-kwantiel van |BTC-rendement over k minuten| in de trainhelft."""
    lb = np.log(btc["close"]).diff(k)
    la = np.log(alt["close"]).diff(k)
    rb, ra = np.log(btc["close"]).diff(), np.log(alt["close"]).diff()
    beta = (ra.rolling(BETA_WINDOW, min_periods=BETA_WINDOW // 2).cov(rb) / rb.rolling(BETA_WINDOW, min_periods=BETA_WINDOW // 2).var()).shift(1)
    thr = lb.abs()[_train_mask(lb.index, cut)].quantile(TOP_Q)
    direction = np.sign(lb)
    hit = lb.abs() >= thr
    if need_lag:
        hit &= (la * direction) < LAG_FRACTION * beta.clip(lower=0) * lb.abs()
    idx = _decluster(np.flatnonzero(hit.fillna(False).to_numpy()))
    return idx, direction.to_numpy()[idx]


def spike_features(frame: pd.DataFrame) -> pd.DataFrame:
    tr = frame["high"] - frame["low"]
    atr = tr.rolling(SPIKE_WINDOW, min_periods=SPIKE_WINDOW // 2).mean().shift(1)
    vol_mean = frame["volume"].rolling(SPIKE_WINDOW, min_periods=SPIKE_WINDOW // 2).mean().shift(1)
    vol_std = frame["volume"].rolling(SPIKE_WINDOW, min_periods=SPIKE_WINDOW // 2).std().shift(1)
    body = np.sign(frame["close"] - frame["open"])
    wick = np.where(body > 0, (frame["high"] - frame["close"]) / tr.replace(0, np.nan), (frame["close"] - frame["low"]) / tr.replace(0, np.nan))
    return pd.DataFrame({"range_x": tr / atr, "vol_z": (frame["volume"] - vol_mean) / vol_std, "body": body, "wick": wick}, index=frame.index)


def spike_events(frame: pd.DataFrame, cut: pd.Timestamp, fade: bool) -> tuple[np.ndarray, np.ndarray]:
    f = spike_features(frame)
    train = _train_mask(f.index, cut)
    q_range, q_vol = f["range_x"][train].quantile(TOP_Q), f["vol_z"][train].quantile(TOP_Q)
    hit = (f["range_x"] >= q_range) & (f["vol_z"] >= q_vol) & (f["wick"] >= WICK_MIN)
    idx = _decluster(np.flatnonzero(hit.fillna(False).to_numpy()))
    direction = (-f["body"] if fade else f["body"]).to_numpy()
    return idx, direction[idx]


def flow_events(frame: pd.DataFrame, flow: pd.DataFrame, k: int, cut: pd.Timestamp, fade: bool) -> tuple[np.ndarray, np.ndarray]:
    """Uitschieter in taker-delta over k minuten. delta = (kopers - verkopers) / volume, gesommeerd over k minuten."""
    f = flow.set_index("timestamp").reindex(frame.index)
    buy, vol = f["buy_volume"].rolling(k).sum(), f["volume"].rolling(k).sum()
    delta = (2 * buy - vol) / vol.replace(0, np.nan)
    thr = delta.abs()[_train_mask(delta.index, cut)].quantile(TOP_Q)
    hit = delta.abs() >= thr
    idx = _decluster(np.flatnonzero(hit.fillna(False).to_numpy()))
    direction = np.sign(delta).to_numpy() * (-1 if fade else 1)
    return idx, direction[idx]


def run_coin(coin: str, frames: dict[str, pd.DataFrame], cut: pd.Timestamp, flows: Optional[dict] = None) -> pd.DataFrame:
    """Alle gebeurtenissen van één alt, over de varianten en horizonnen heen. Kolommen: test, h, at, gross_bp, coin."""
    btc, alt = frames["BTC"], frames[coin]
    rows = []
    variants = []
    if coin != "BTC":
        for k in LEAD_K:
            for need_lag in (True, False):
                variants.append((f"LEAD k={k}{' achterstand' if need_lag else ' alle'}", lead_events(btc, alt, k, cut, need_lag)))
    for fade in (True, False):
        variants.append(("FADE uitputting" if fade else "FOLLOW uitputting", spike_events(alt, cut, fade)))
    if flows and coin in flows:
        for k in (1, 3):
            for fade in (True, False):
                variants.append((f"FLOW k={k} {'tegen' if fade else 'mee'}", flow_events(alt, flows[coin], k, cut, fade)))
    for name, (idx, direction) in variants:
        for h in HORIZONS:
            t = _trades(alt, idx, direction, h)
            t["test"], t["h"], t["coin"] = name, h, coin
            rows.append(t)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def placebo(frames: dict[str, pd.DataFrame], trades: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Per gebeurtenis een willekeurige minuut in hetzelfde uur van de dag, willekeurige kant, dezelfde coin en horizon."""
    rng = np.random.default_rng(seed)
    rows = []
    for (coin, h), g in trades.groupby(["coin", "h"]):
        frame = frames[coin]
        by_hour = {hr: np.flatnonzero(frame.index.hour == hr) for hr in range(24)}
        idx, direction = [], []
        for hr in g["hour"]:
            pool = by_hour[hr]
            idx.append(int(pool[rng.integers(0, len(pool))]))
            direction.append(1.0 if rng.random() < 0.5 else -1.0)
        t = _trades(frame, np.array(idx), np.array(direction), h)
        t["test"], t["h"], t["coin"] = "PLACEBO", h, coin
        rows.append(t)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


@dataclass
class Row:
    test: str
    h: int
    n: int
    gross: float
    net_taker: float
    net_maker: float
    train_net: Optional[float]
    test_net: Optional[float]
    n_train: int
    n_test: int
    t_days: Optional[float]
    placebo_gross: float


def _day_t(g: pd.DataFrame, cost: float) -> Optional[float]:
    daily = (g["gross_bp"] - cost).groupby(g["at"].dt.floor("D")).mean()
    if len(daily) < 5 or daily.std(ddof=1) == 0:
        return None
    return float(daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))))


def summarize(trades: pd.DataFrame, placebos: pd.DataFrame, cut: pd.Timestamp) -> list[Row]:
    out = []
    for (name, h), g in trades.groupby(["test", "h"]):
        tr, te = g[g["at"] < cut], g[g["at"] >= cut]
        p = placebos[placebos["h"] == h] if not placebos.empty else placebos
        out.append(Row(name, h, len(g), float(g["gross_bp"].mean()), float(g["gross_bp"].mean() - COST_TAKER_BP),
                       float(g["gross_bp"].mean() - COST_MAKER_BP),
                       float(tr["gross_bp"].mean() - COST_TAKER_BP) if len(tr) else None,
                       float(te["gross_bp"].mean() - COST_TAKER_BP) if len(te) else None, len(tr), len(te), _day_t(g, COST_TAKER_BP),
                       float(p["gross_bp"].mean()) if len(p) else 0.0))
    return out


def monthly(trades: pd.DataFrame, test: str, h: int) -> pd.DataFrame:
    """Gemiddeld brutorendement (bp) en aantal per maand voor één variant: toont of een voordeel wegzakt of door één maand komt."""
    g = trades[(trades["test"] == test) & (trades["h"] == h)]
    m = g.groupby(g["at"].dt.strftime("%Y-%m"))["gross_bp"].agg(["mean", "count"])
    return m.rename(columns={"mean": "gross_bp", "count": "n"})


def by_coin(trades: pd.DataFrame, test: str, h: int, cut: pd.Timestamp) -> pd.DataFrame:
    """Per coin: aantal, bruto bp in train en in test."""
    g = trades[(trades["test"] == test) & (trades["h"] == h)]
    rows = {}
    for coin, c in g.groupby("coin"):
        rows[coin] = {"n": len(c), "train": c[c["at"] < cut]["gross_bp"].mean(), "test": c[c["at"] >= cut]["gross_bp"].mean()}
    return pd.DataFrame(rows).T


def passes(r: Row, min_n: int = 30) -> bool:
    return (r.n_train >= min_n and r.n_test >= min_n and r.train_net is not None and r.test_net is not None
            and r.train_net > 0 and r.test_net > 0 and r.gross > r.placebo_gross and (r.t_days or 0) > 2)
