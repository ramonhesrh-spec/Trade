"""Welk ordertype werkt het best voor de plannen van het HesPulse-model: limiet, market of stop-order? (preregistratie, aanvulling
2026-11-03 nacht, B-2026-11-03-13). Zuiver: per plan drie instappen met dezelfde stop en hetzelfde doel, op 5m-candles, met de uitkomstregel
van het model (model.outcome). Alleen meting achteraf; geen regel of melding leest dit.

- limiet: de regel van het model (model.walk_fill vanaf het moment dat het plan bekend was).
- market: instap op de open van de eerste 5m-candle vanaf dat moment (de klik op de melding).
- stop: een stop-order op het uiterste van de 15m-candle die het plan bekend maakte (long: zijn high, short: zijn low); gevuld zodra een
  latere 5m-candle er strikt doorheen gaat, op het niveau of op de open als die er al voorbij lag. Raakt de koers eerst de stop van het
  plan, dan vervalt de order.
Alle drie vervallen op dezelfde vervaltijd en bij een nieuwe 4u-breuk (context_weg), net als de limiet. Een instap die niet tussen stop en
doel ligt, telt niet ('voorbij'). De uitkomst telt voor alle drie vanaf de candle na de vulcandle, de regel van het model live: zo is de
vergelijking eerlijk, al ziet geen van de drie wat er binnen de vulcandle zelf gebeurde."""
from typing import Iterable, Optional

import pandas as pd

from app import model

ARMS = ("limiet", "market", "stop")
STEP = pd.Timedelta(minutes=5)


def _between(direction: str, entry: float, stop: float, take: float) -> bool:
    s = 1 if direction == "long" else -1
    return (take - entry) * s > 0 and (entry - stop) * s > 0


def market_fill(direction: str, stop: float, take: float, known_at: pd.Timestamp, b5: pd.DataFrame) -> dict:
    after = b5[b5["timestamp"] >= known_at]
    if not len(after):
        return {"state": None}
    row = after.iloc[0]
    e = float(row["open"])
    if not _between(direction, e, stop, take):
        return {"state": "voorbij", "at": row["timestamp"]}
    return {"state": "gevuld", "at": row["timestamp"], "entry": e}


def stop_fill(direction: str, trigger: float, stop: float, take: float, known_at: pd.Timestamp, expires_at: Optional[pd.Timestamp],
              b5: pd.DataFrame, breaks_at: Iterable[pd.Timestamp] = ()) -> dict:
    s = 1 if direction == "long" else -1
    if not _between(direction, trigger, stop, take):
        return {"state": "voorbij", "at": known_at}
    brk = sorted(b for b in breaks_at if b > known_at)
    for row in b5[b5["timestamp"] >= known_at].itertuples():
        ts = row.timestamp
        if expires_at is not None and ts >= expires_at:
            return {"state": "vervallen", "at": expires_at}
        if brk and ts >= brk[0]:
            return {"state": "context_weg", "at": brk[0]}
        hi, lo, op = (row.high, row.low, row.open) if s > 0 else (-row.low, -row.high, -row.open)
        if lo <= stop * s:
            return {"state": "stop_eerst", "at": ts}
        if hi > trigger * s:
            e = max(trigger * s, op) * s
            if not _between(direction, e, stop, take):
                return {"state": "voorbij", "at": ts}
            return {"state": "gevuld", "at": ts, "entry": e}
    return {"state": None}


def trigger_level(direction: str, known_at: pd.Timestamp, b15: pd.DataFrame) -> Optional[float]:
    """Het uiterste van de 15m-candle die op known_at sloot."""
    row = b15[b15["timestamp"] == known_at - pd.Timedelta(minutes=15)]
    if not len(row):
        return None
    return float(row["high"].iloc[0] if direction == "long" else row["low"].iloc[0])


def compare_plan(direction: str, plan: dict, b5: pd.DataFrame, b15: pd.DataFrame, breaks_at: Iterable[pd.Timestamp] = ()) -> dict:
    """plan: {known_at, limit, stop, take, expires_at}. Per arm: {state, entry, r (bruto), outcome}. Zonder doel: niets."""
    known, stop, take = pd.Timestamp(plan["known_at"]), plan["stop"], plan.get("take")
    expires = pd.Timestamp(plan["expires_at"]) if plan.get("expires_at") is not None else None
    out = {}
    if take is None:
        return out
    before = b5[b5["timestamp"] < known]
    price = float(before["close"].iloc[-1]) if len(before) else None
    lim = model.walk_fill(direction, plan["limit"], take, known, expires, b5, price_at_publish=price, breaks_at=breaks_at)
    fills = {"limiet": {**lim, "entry": plan["limit"]} if lim["state"] == "gevuld" else lim,
             "market": market_fill(direction, stop, take, known, b5)}
    trig = trigger_level(direction, known, b15)
    fills["stop"] = stop_fill(direction, trig, stop, take, known, expires, b5, breaks_at) if trig is not None else {"state": None}
    for arm, f in fills.items():
        res = {"state": f["state"], "entry": f.get("entry"), "r": None, "outcome": None, "end": None}
        if f["state"] == "gevuld":
            o = model.outcome(direction, f["entry"], stop, take, pd.Timestamp(f["at"]), b5)
            res.update(outcome=o["state"], r=o["r"], end=o["at"])
        out[arm] = res
    return out
