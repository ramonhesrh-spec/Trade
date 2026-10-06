"""Signaalonderzoek zonder patronen: bestaat er informatie in koers en taker-volume die de rendementen van de komende 15 tot 60 minuten voorspelt?

Panel: elke gesloten 5m-candle van elke coin, kenmerken uit alleen die candle en eerdere. Doel: het rendement in basispunten van de instap
(een candle later, zoals een echte order) tot H later. Twee stappen:
1. Per kenmerk de rang-correlatie (IC) met de uitkomst, trainhelft en testhelft apart, met een t-waarde die rekening houdt met overlappende
   uitkomsten. Een voorspeller telt als beide helften dezelfde kant op wijzen.
2. Een ridge-model op alle kenmerken, getraind op de trainhelft. Handelen alleen op de sterkste voorspellingen (bovenste fractie van |voorspelling|,
   drempel uit de trainhelft), kosten eraf, met een permutatietoets op de voorspellingen."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import flow
from app.replay.lab import make_bars

HORIZONS = {"15m": 3, "30m": 6, "60m": 12}
SIGMA_BARS = 288
ENTRY_DELAY = 1
FEATURES = ["r5", "r15", "r60", "r240", "d5", "d15", "d60", "cvd_div", "tr_z", "vol_z", "rng_z", "vwap_dev", "hour_sin", "hour_cos",
            "btc_r5", "btc_r15", "btc_d15"]


def build_panel(frame_1m: pd.DataFrame, flow_1m: pd.DataFrame, btc_panel: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    bars = make_bars(frame_1m, 5)
    f5 = flow.flow_5m(flow_1m, bars["timestamp"])
    close = bars["close"]
    logret = np.log(close).diff()
    sigma = logret.rolling(SIGMA_BARS).std()
    d = lambda n: pd.Series(flow.delta(f5["buy_volume"].rolling(n).sum().to_numpy(), f5["volume"].rolling(n).sum().to_numpy()), index=bars.index)  # noqa: E731
    atr = (bars["high"] - bars["low"]).rolling(14).mean()
    vwap = (close * f5["volume"]).rolling(SIGMA_BARS).sum() / f5["volume"].rolling(SIGMA_BARS).sum()
    hour = bars["timestamp"].dt.hour + bars["timestamp"].dt.minute / 60
    p = pd.DataFrame({"at": bars["close_time"], "close": close})
    for name, n in (("r5", 1), ("r15", 3), ("r60", 12), ("r240", 48)):
        p[name] = np.log(close).diff(n) / (sigma * np.sqrt(n))
    p["d5"], p["d15"], p["d60"] = d(1), d(3), d(12)
    p["cvd_div"] = p["d60"] * np.sign(-p["r60"])                  # kopers terwijl de koers daalde, of omgekeerd
    p["tr_z"] = f5["trades"] / f5["trades"].shift(1).rolling(SIGMA_BARS).mean() - 1
    p["vol_z"] = f5["volume"] / f5["volume"].shift(1).rolling(SIGMA_BARS).mean() - 1
    p["rng_z"] = (bars["high"] - bars["low"]) / atr
    p["vwap_dev"] = (close - vwap) / (sigma * close * np.sqrt(SIGMA_BARS))
    p["hour_sin"], p["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    for label, h in HORIZONS.items():
        p[f"fwd_{label}"] = (close.shift(-(ENTRY_DELAY + h)) / close.shift(-ENTRY_DELAY) - 1) * 1e4
    if btc_panel is not None:
        btc = btc_panel.set_index("at")
        for col in ("r5", "r15", "d15"):
            p[f"btc_{col}"] = p["at"].map(btc[col]).astype(float)
    else:
        p["btc_r5"], p["btc_r15"], p["btc_d15"] = p["r5"], p["r15"], p["d15"]
    return p


def decluster(panel: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Elke `bars`-ste rij: uitkomsten die elkaar niet overlappen, zodat gemiddelden en t-waarden eerlijk zijn."""
    return panel.iloc[::bars]


@dataclass
class IcRow:
    feature: str
    horizon: str
    ic_train: float
    ic_test: float
    t_test: float
    n_test: int


def _ic(x: pd.Series, y: pd.Series) -> float:
    ok = x.notna() & y.notna()
    return float(x[ok].rank().corr(y[ok].rank())) if ok.sum() > 50 else np.nan


def information_coefficients(panel: pd.DataFrame, cut: pd.Timestamp) -> list[IcRow]:
    rows = []
    for label, h in HORIZONS.items():
        sub = decluster(panel, h)
        train, test = sub[sub["at"] < cut], sub[sub["at"] >= cut]
        for feat in FEATURES:
            ic_tr, ic_te = _ic(train[feat], train[f"fwd_{label}"]), _ic(test[feat], test[f"fwd_{label}"])
            n = int((test[feat].notna() & test[f"fwd_{label}"].notna()).sum())
            t = ic_te * np.sqrt(max(n - 2, 1)) / np.sqrt(max(1 - ic_te ** 2, 1e-9)) if n > 2 and not np.isnan(ic_te) else np.nan
            rows.append(IcRow(feat, label, ic_tr, ic_te, t, n))
    return rows


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = 10.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1
    Z = (X - mu) / sd
    ym = y.mean()
    w = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return w, mu, sd, ym


def ridge_predict(model, X: np.ndarray) -> np.ndarray:
    w, mu, sd, ym = model
    return ((X - mu) / sd) @ w + ym


@dataclass
class ModelResult:
    horizon: str
    n_train: int
    ic_test: float
    n_trades: int
    gross_bps: float
    net_bps: float
    winrate: float
    p_value: float


def evaluate_model(panel: pd.DataFrame, label: str, cut: pd.Timestamp, cost_bps: float = 6.0, top_fraction: float = 0.05,
                   permutations: int = 200, seed: int = 0) -> ModelResult:
    h = HORIZONS[label]
    target = f"fwd_{label}"
    data = panel.dropna(subset=FEATURES + [target]).reset_index(drop=True)
    train, test = data[data["at"] < cut], data[data["at"] >= cut]
    # trainen op niet-overlappende rijen scheelt tijd en geeft een eerlijkere kans; de testhelft wordt volledig beoordeeld
    tr = train.iloc[::max(1, h // 3)]
    model = ridge_fit(tr[FEATURES].to_numpy(dtype=float), tr[target].clip(-300, 300).to_numpy(dtype=float))
    thr = np.quantile(np.abs(ridge_predict(model, tr[FEATURES].to_numpy(dtype=float))), 1 - top_fraction)
    te = decluster(test, h)
    pred = ridge_predict(model, te[FEATURES].to_numpy(dtype=float))
    chosen = np.abs(pred) >= thr
    y = te[target].to_numpy(dtype=float)
    gross = np.sign(pred[chosen]) * y[chosen]
    net = gross - cost_bps
    rng = np.random.default_rng(seed)
    better = 0
    for _ in range(permutations):
        sp = rng.permutation(pred)
        sel = np.abs(sp) >= thr
        if sel.sum() and (np.sign(sp[sel]) * y[sel] - cost_bps).mean() >= net.mean() if len(net) else False:
            better += 1
    return ModelResult(label, len(tr), _ic(pd.Series(pred), pd.Series(y)), int(chosen.sum()), float(gross.mean()) if len(gross) else np.nan,
                       float(net.mean()) if len(net) else np.nan, float((net > 0).mean()) if len(net) else np.nan, better / permutations)
