"""Toets van drie ideeën die niet op een zone of patroon steunen, met vaste uitstaptijd in plaats van stop en take:

A. voorloop: BTC maakt een uitschieter van enkele sigma's in 5 minuten terwijl een alt nog niet bewogen heeft.
B. relatieve kracht: elke 4 uur de sterkste en zwakste coin van de zeven, vastgehouden voor H.
C. uitputting: een uitschieter in het uur ervoor (3 sigma), gevolgd of juist tegengehandeld.

Alles uit gesloten 5m-candles, instap een candle na het signaal (de vertraging van een echte order), uitstap H later.
Per idee, uitstaptijd en kant (volgen of tegenhandelen): aantal onafhankelijke trades (overlap binnen H overgeslagen),
bruto en netto in basispunten, t-waarde, train en test, en een controle op willekeurige momenten."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

BAR = "5min"
HORIZONS = {"15m": 3, "30m": 6, "1u": 12, "4u": 48}
SIGMA_WINDOW = 288          # een dag aan 5m-candles
LEAD_Z = 2.5
LAG_Z = 1.0
EXHAUST_Z = 3.0
RANK_EVERY = 48
ENTRY_DELAY = 1


def closes_5m(frames_1m: dict) -> pd.DataFrame:
    """Slotkoersen per 5m, kolom per coin. Frames hebben kolommen timestamp en close."""
    out = {}
    for coin, f in frames_1m.items():
        s = f.set_index("timestamp")["close"].astype(float)
        out[coin] = s.resample(BAR, label="right", closed="right").last()
    return pd.DataFrame(out).dropna(how="all")


def _z(ret: pd.Series) -> pd.Series:
    return ret / ret.rolling(SIGMA_WINDOW).std().shift(1)


def forward_bps(close: pd.Series, bars: int) -> pd.Series:
    """Rendement in basispunten van instap (ENTRY_DELAY candles na het signaal) tot `bars` later."""
    entry = close.shift(-ENTRY_DELAY)
    exit_ = close.shift(-(ENTRY_DELAY + bars))
    return (exit_ / entry - 1) * 1e4


def events(closes: pd.DataFrame) -> pd.DataFrame:
    """Alle signalen: kolommen at, coin, idee, richting (+1 volgen van het signaal, -1 omgekeerd gebeurt later)."""
    rows = []
    if "BTC" in closes:
        btc_z = _z(closes["BTC"].pct_change())
        for coin in closes.columns:
            if coin == "BTC":
                continue
            alt_z = _z(closes[coin].pct_change())
            hit = (btc_z.abs() > LEAD_Z) & (alt_z.abs() < LAG_Z)
            for at in btc_z.index[hit.fillna(False)]:
                rows.append((at, coin, "A voorloop", int(np.sign(btc_z[at]))))
    for coin in closes.columns:
        z1h = _z(closes[coin].pct_change(12))
        hit = z1h.abs() > EXHAUST_Z
        for at in z1h.index[hit.fillna(False)]:
            rows.append((at, coin, "C uitputting", int(np.sign(z1h[at]))))
    r4 = closes.pct_change(RANK_EVERY)
    for at in closes.index[RANK_EVERY::RANK_EVERY]:
        row = r4.loc[at].dropna()
        if len(row) >= 4:
            rows.append((at, row.idxmax(), "B relatieve kracht", 1))
            rows.append((at, row.idxmin(), "B relatieve kracht", -1))
    return pd.DataFrame(rows, columns=["at", "coin", "idee", "richting"])


def decluster(ev: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Per coin en idee alleen signalen die minstens `bars` na het vorige behouden signaal liggen."""
    keep = []
    gap = pd.Timedelta(minutes=5 * bars)
    for _, g in ev.sort_values("at").groupby(["coin", "idee"]):
        last = None
        for i, at in zip(g.index, g["at"]):
            if last is None or at - last >= gap:
                keep.append(i)
                last = at
    return ev.loc[keep]


@dataclass
class Row:
    idee: str
    horizon: str
    kant: str
    n: int
    gross: float
    net: float
    t: float
    train_net: Optional[float]
    test_net: Optional[float]
    n_train: int
    n_test: int
    placebo_net: float


def _stats(x: np.ndarray) -> tuple[float, float]:
    if len(x) < 2:
        return (float(x.mean()) if len(x) else 0.0), 0.0
    sd = x.std(ddof=1)
    return float(x.mean()), float(x.mean() / (sd / np.sqrt(len(x)))) if sd > 0 else 0.0


def evaluate(closes: pd.DataFrame, cost_bps: float, seed: int = 0) -> list[Row]:
    """cost_bps is de rondreis in basispunten (0,06% = 6). Volgen en tegenhandelen delen dezelfde signalen."""
    ev = events(closes)
    if ev.empty:
        return []
    cut = closes.index[int(len(closes) * 0.7)]
    rng = np.random.default_rng(seed)
    fwd_cache = {}
    out: list[Row] = []
    for hname, bars in HORIZONS.items():
        for coin in closes.columns:
            fwd_cache[(coin, bars)] = forward_bps(closes[coin], bars)
        sub = decluster(ev, bars)
        for idee, g in sub.groupby("idee"):
            gross = np.array([d * fwd_cache[(c, bars)].get(a, np.nan) for a, c, d in zip(g["at"], g["coin"], g["richting"])])
            ok = ~np.isnan(gross)
            gross, at_s = gross[ok], g["at"][ok].reset_index(drop=True)
            if len(gross) == 0:
                continue
            # placebo: dezelfde coins op willekeurige momenten met willekeurige richting
            coins = g["coin"].to_numpy()[ok]
            rand_idx = rng.integers(SIGMA_WINDOW, len(closes) - 60, size=len(coins))
            plac = np.array([rng.choice([-1, 1]) * fwd_cache[(c, bars)].iloc[i] for c, i in zip(coins, rand_idx)])
            plac = plac[~np.isnan(plac)]
            for kant, sign in (("volgen", 1), ("tegenhandelen", -1)):
                x = sign * gross
                net = x - cost_bps
                m, _ = _stats(x)
                nm, t = _stats(net)
                before = (at_s < cut).to_numpy()
                tr, te = net[before], net[~before]
                out.append(Row(idee, hname, kant, len(x), m, nm, t,
                               float(tr.mean()) if len(tr) else None, float(te.mean()) if len(te) else None,
                               len(tr), len(te), float((plac - cost_bps).mean()) if len(plac) else 0.0))
    return out


def passes(r: Row, min_n: int = 30) -> bool:
    return (r.n_train >= min_n and r.n_test >= min_n and r.train_net is not None and r.test_net is not None
            and r.train_net > 0 and r.test_net > 0 and r.t > 2.0)
