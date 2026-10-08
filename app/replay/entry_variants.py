"""Entry-varianten voor dezelfde breuken: een structuurbreuk gaat snel, en wie wacht op een terugkeer naar het exacte niveau mist veel beweging.
Dezelfde detector, dezelfde stop en dezelfde ladder (1R, 2R, 3R, stop naar de instap na het eerste doel) als app/replay/breakretest.py; alleen de instap verschilt:
  RETEST  limiet op het gebroken niveau (zoals live)
  ZONE25  limiet een kwart ATR vóór het niveau, de koers hoeft minder ver terug
  ZONE50  limiet een halve ATR vóór het niveau
  MARKT   instap op het slot van de breukcandle
  SPLIT   de helft MARKT en de helft RETEST (alleen de helft MARKT als de terugkeer uitblijft)
De eerlijke maat is netto R per GEZIENE BREUK, niet per vulling: een variant die vaker vult maar slechter scoort per trade kan toch meer opleveren, en andersom.
Stop volgens dezelfde regel als live (smc_eval.floor_stop). Pure functies; draai via scripts/entry_variants.py."""
from typing import Callable, Optional

import numpy as np
import pandas as pd

from app import smc_eval
from app.replay import breakretest as br
from app.replay.lab import add_indicators, make_bars

MODES = ("RETEST", "ZONE25", "ZONE50", "MARKT", "SPLIT")
LADDER = "ladder 1-2-3R"
ZONE_FRACTION = {"ZONE25": 0.25, "ZONE50": 0.5}


def _plan_zone(ev, b: pd.DataFrame, m: br.Minutes, frac: float) -> Optional[tuple[int, float, float, int]]:
    """Zoals br._plan_retest, maar de limiet ligt frac * ATR vóór het niveau (korter bij de koers). De stop blijft achter het niveau."""
    direction, i, n = ev.direction, ev.bar, len(b)
    sign = 1 if direction == "long" else -1
    for j in range(i + 1, min(i + 1 + br.RETEST_BARS, n)):
        prev_level = br.level_at(ev, j - 1)
        if -sign * (b.at[j - 1, "close"] - prev_level) > br.BREAK_ATR * ev.atr:
            return None
        level = br.level_at(ev, j)
        entry = level - frac * ev.atr if direction == br.SHORT else level + frac * ev.atr
        start, end = m.index(b.at[j, "timestamp"]), m.index(b.at[j, "close_time"])
        reach = m.high[start:end] >= entry if direction == br.SHORT else m.low[start:end] <= entry
        if not reach.any():
            continue
        extreme = b["high"].iloc[i:j].max() if direction == br.SHORT else b["low"].iloc[i:j].min()
        stop = max(level, extreme) + br.STOP_ATR * ev.atr if direction == br.SHORT else min(level, extreme) - br.STOP_ATR * ev.atr
        return start + int(np.argmax(reach)), float(entry), float(stop), j
    return None


def _trade(ev, b, m, plan, levels, cost_pct) -> Optional[tuple[float, float, str]]:
    """(netto R, stopafstand %, uitkomst) of None als de instap ongeldig is. Stop is verbreed tot de minimale afstand van live."""
    k, entry, stop, _ = plan
    stop = smc_eval.floor_stop(ev.direction, entry, stop)
    risk = abs(entry - stop)
    risk_pct = risk / entry * 100
    if not risk or risk_pct > br.MAX_STOP_PCT or k >= len(m.high) or (ev.direction == br.SHORT and entry >= stop) or (ev.direction == "long" and entry <= stop):
        return None
    tg = br.ladder_targets(ev.direction, entry, risk, LADDER, levels)
    w = m.window(k)
    _, net, outcome = br.simulate(ev.direction, entry, stop, tg[0], tg[1], True, m.high[w], m.low[w], m.close[w], cost_pct)
    return net, risk_pct, outcome


def run_variants(frame_1m: pd.DataFrame, cost_pct: float = 0.06) -> pd.DataFrame:
    """Eén rij per breuk en variant. filled=False betekent geen trade (net 0), zodat de som per gezien breuk eerlijk is."""
    bars = make_bars(frame_1m, br.BAR_MINUTES)
    events = br.find_breaks(bars)
    if events.empty:
        return pd.DataFrame(columns=["at", "direction", "kind", "mode", "filled", "net", "risk_pct", "outcome"])
    b = add_indicators(bars).reset_index(drop=True)
    m = br.Minutes(frame_1m)
    p_high, p_low = br._pivots(b)
    planners: dict[str, Callable] = {"RETEST": br._plan_retest, "MARKT": br._plan_market,
                                     **{name: (lambda ev, bb, mm, f=frac: _plan_zone(ev, bb, mm, f)) for name, frac in ZONE_FRACTION.items()}}
    rows = []
    for ev in events.itertuples():
        levels = br.known_levels(b, p_high, p_low, ev.direction, ev.bar)
        at = b.at[ev.bar, "close_time"]
        results: dict[str, Optional[tuple]] = {}
        for mode, plan_fn in planners.items():
            plan = plan_fn(ev, b, m)
            results[mode] = _trade(ev, b, m, plan, levels, cost_pct) if plan is not None else None
        market, retest = results["MARKT"], results["RETEST"]
        if market:
            half = 0.5 * market[0] + 0.5 * (retest[0] if retest else 0.0)
            results["SPLIT"] = (half, market[1], market[2])
        else:
            results["SPLIT"] = None
        for mode in MODES:
            res = results.get(mode)
            rows.append({"at": at, "direction": ev.direction, "kind": ev.kind, "mode": mode, "filled": res is not None,
                         "net": res[0] if res else 0.0, "risk_pct": res[1] if res else None, "outcome": res[2] if res else "geen trade"})
    return pd.DataFrame(rows)


def compare(rows: pd.DataFrame) -> list[dict]:
    """Per variant: gevulde trades, vulgraad, gemiddeld per trade en netto per gezien breuk (de eerlijke maat) met 95%-marge."""
    from app import structure_review as sr
    out = []
    for mode in MODES:
        part = rows[rows["mode"] == mode]
        if part.empty:
            continue
        per_break = part["net"].tolist()
        filled = part[part["filled"]]
        lo, hi = sr.bootstrap_mean(per_break)
        out.append({"mode": mode, "breaks": len(part), "filled": len(filled), "fill_rate": len(filled) / len(part),
                    "avg_per_fill": float(filled["net"].mean()) if len(filled) else None, "total": float(part["net"].sum()),
                    "per_break": sum(per_break) / len(per_break), "ci": (lo, hi), "median_risk_pct": float(filled["risk_pct"].median()) if len(filled) else None})
    return out
