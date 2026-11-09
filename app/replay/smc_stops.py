"""Hoeveel speling moet de stop van een SMC-kans hebben? Een stop vlak achter de sweep wordt vaak geraakt door een wick waarna de koers
alsnog de goede kant op gaat. Dit meet het: dezelfde setups en doelen, maar de stop minimaal X% van de instap. Elke variant telt alleen
kansen die de R:R-ondergrens nog halen, zoals live. Eén replay levert de ruwe signalen (zonder stopafstand-toets en zonder R:R-eis),
alle varianten worden daarna offline op de 1m-candles uitgespeeld."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app import smc_eval
from app.replay.outcome import resolve
from app.setup_eval import MIN_RISK_REWARD_RATIO

FLOORS = (0.2, 0.3, 0.4, 0.5, 0.7, 1.0)


@dataclass
class Row:
    floor: float
    n: int
    wins: int
    losses: int
    expired: int
    avg_net: Optional[float]
    train: Optional[float]
    test: Optional[float]
    n_train: int
    n_test: int


def play(sig, frame: pd.DataFrame, floor_pct: float, max_age: pd.Timedelta, fee_pct: float, slip_pct: float,
         min_rr: float = MIN_RISK_REWARD_RATIO):
    """Uitkomst van één ruw signaal met de stop minstens floor_pct van de instap. None als de R:R dan onder de ondergrens zakt."""
    stop = smc_eval.floor_stop(sig.direction, sig.entry, sig.stop, floor_pct)
    risk = abs(sig.entry - stop)
    if risk <= 0 or abs(sig.take - sig.entry) / risk < min_rr:
        return None
    return resolve(sig.direction, sig.entry, stop, sig.take, frame, sig.at, max_age, fee_pct, slip_pct)


def sweep(signals: list, frames: dict[str, pd.DataFrame], cut: pd.Timestamp, floors=FLOORS, max_age=pd.Timedelta(hours=48),
          fee_pct: float = 0.03, slip_pct: float = 0.01) -> list[Row]:
    rows = []
    for floor in floors:
        results = []
        for s in signals:
            o = play(s, frames[s.coin], floor, max_age, fee_pct, slip_pct)
            if o is not None:
                results.append((s.at, o))
        done = [(t, o) for t, o in results if o.result != "expired"]
        net = [o.r_net for _, o in done]
        tr = [o.r_net for t, o in done if t < cut]
        te = [o.r_net for t, o in done if t >= cut]
        rows.append(Row(floor, len(results), sum(1 for _, o in done if o.result == "take_profit"),
                        sum(1 for _, o in done if o.result == "stop_loss"), len(results) - len(done),
                        float(np.mean(net)) if net else None, float(np.mean(tr)) if tr else None,
                        float(np.mean(te)) if te else None, len(tr), len(te)))
    return rows
