"""Derivatenkenmerken op het moment van een setup, alleen uit rijen die op dat moment al bestonden
(laatste rij op of voor `at`). 'Richting' maakt van een ruwe waarde een bruikbaar kenmerk: een long
met positieve funding zit aan de volle kant van de markt, een short met negatieve funding ook."""
from typing import Optional

import pandas as pd


def features_at(derivs: pd.DataFrame, at: pd.Timestamp, direction: str) -> Optional[dict]:
    hist = derivs[derivs.index <= at]
    if len(hist) < 60:  # minder dan 5 uur geschiedenis: geen betrouwbare verandering
        return None
    now = hist.iloc[-1]
    if (at - hist.index[-1]) > pd.Timedelta(minutes=30):
        return None
    sign = 1 if direction == "long" else -1
    h4 = hist[hist.index <= at - pd.Timedelta(hours=4)]
    oi_change = (now["oi_usd"] / h4.iloc[-1]["oi_usd"] - 1) * 100 if len(h4) else None
    return {
        "funding_vol": sign * now["funding"] > 0,
        "oi_4u_pct": oi_change,
        "taker_in_richting": sign * (now["taker_ratio"] - 1) > 0,
        "publiek_in_richting": sign * (now["global_ls"] - 1) > 0,
        "top_in_richting": sign * (now["top_ls"] - 1) > 0,
    }
