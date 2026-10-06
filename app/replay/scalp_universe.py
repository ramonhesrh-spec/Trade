"""Welke coins lenen zich voor een BTC-voorsprong-scalp? Voor elke alt: hoeveel loopt hij achter op BTC, hoe liquide is hij en wat zou de
achterstand opleveren tegenover de kosten. Een snelle schifting op 1m; de echte toets blijft scripts/scalp_scan.py.

achterstand_bp: regressie van het rendement van de alt in de 3 minuten NA een BTC-minuut op dat BTC-rendement, uitgedrukt voor een
BTC-minuut van 30 bp. Dat is wat een alt gemiddeld nog bijtrekt. Moet ruim boven de kosten (6 bp) liggen om te kunnen werken."""
from typing import Optional

import numpy as np
import pandas as pd

LAGS = (1, 2, 3)
BTC_MOVE_BP = 30.0
COST_BP = 6.0


def screen(btc: pd.DataFrame, alt: pd.DataFrame) -> Optional[dict]:
    """btc en alt: 1m-candles met kolommen timestamp, high, low, close, volume."""
    b = btc.set_index("timestamp")[["close"]].join(alt.set_index("timestamp")[["high", "low", "close", "volume"]], how="inner", rsuffix="_alt")
    if len(b) < 5000:
        return None
    rb = np.log(b["close"]).diff()
    ra = np.log(b["close_alt"]).diff()
    fwd = sum(ra.shift(-j) for j in LAGS)
    ok = rb.notna() & ra.notna() & fwd.notna()
    rb, ra, fwd = rb[ok], ra[ok], fwd[ok]
    var = float(rb.var())
    if var == 0:
        return None
    slope = float(np.cov(fwd, rb)[0, 1] / var)
    n = len(rb)
    cross = [float(np.corrcoef(rb.iloc[: n - j], ra.shift(-j).dropna().iloc[: n - j])[0, 1]) for j in LAGS]
    t_lag = float(np.sum(cross) * np.sqrt(n) / np.sqrt(len(LAGS)))
    beta = float(np.cov(ra, rb)[0, 1] / var)
    quote_per_min = float((b["close_alt"] * b["volume"]).median())
    range_bp = float(((b["high"] - b["low"]) / b["close_alt"]).median() * 1e4)
    return {"n": n, "beta": beta, "achterstand_bp": slope * BTC_MOVE_BP, "t_lag": t_lag, "quote_per_min": quote_per_min, "range_bp": range_bp}
