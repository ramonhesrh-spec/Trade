"""Rejectie op een niveau: de koers test een niveau dat al meerdere keren gehouden heeft en sluit er weer van weg. Twee vormen, beide richtingen:
  weerstand: minstens TOUCHES zwaaipunten (hoog) op bijna dezelfde prijs, een candle raakt het niveau en sluit er duidelijk onder  -> short
  steun:     idem met zwaaipunten (laag), een candle raakt of prikt door het niveau (sweep) en sluit er duidelijk boven             -> long
Dit is wat Structuur mist: daar telt alleen een breuk met terugkeer. Alles hier is vooraf vastgelegd en niet op data afgestemd.
Pure functies, geen netwerk: live (app/rejection_live.py) en het controlescript gebruiken dezelfde code."""
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import breakretest as br
from app.replay.lab import add_indicators

LOOKBACK = 120          # candles (30m) waarin de aanrakingen liggen, ongeveer 2,5 dag
TOUCHES = 3             # zwaaipunten op bijna dezelfde prijs
CLUSTER_ATR = 0.5       # zo dicht liggen zwaaipunten bij elkaar om als één niveau te tellen
TEST_ATR = 0.15         # de candle moet het niveau tot op zoveel ATR raken
REJECT_ATR = 0.3        # en minstens zoveel ATR terug sluiten
COOLDOWN_BARS = 12      # dezelfde afwijzing van hetzelfde niveau telt binnen zoveel candles één keer
STOP_ATR = 0.25         # stop voorbij de uiterste prik
MAX_STOP_PCT = 2.0
SHORT, LONG = "short", "long"


def find_rejections(bars: pd.DataFrame) -> pd.DataFrame:
    """Kolommen: bar (de afwijzende candle), direction, level, touches, extreme (hoogste/laagste punt van de laatste 3 candles), atr, vol_ratio, swept
    (kwam de candle voorbij het niveau en sloot terug, een sweep)."""
    b = add_indicators(bars).reset_index(drop=True)
    n = len(b)
    high, low, close, open_ = (b[c].to_numpy() for c in ("high", "low", "close", "open"))
    atr, vol = b["atr"].to_numpy(), b["volume"].to_numpy()
    p_high, p_low = br._pivots(b)
    known = {SHORT: [], LONG: []}
    last_event: dict = {}
    out = []
    for i in range(br.PIVOT_K, n):
        q = i - br.PIVOT_K
        if p_high[q]:
            known[SHORT].append(q)
        if p_low[q]:
            known[LONG].append(q)
        if i < 40 or not np.isfinite(atr[i]):
            continue
        for direction in (SHORT, LONG):
            series = high if direction == SHORT else low
            recent = [p for p in known[direction] if i - LOOKBACK <= p <= i - 2]
            if len(recent) < TOUCHES:
                continue
            # Het niveau met de meeste zwaaipunten dicht bij elkaar; bij gelijkstand het meest recente.
            best: list[int] = []
            for anchor in recent:
                group = [p for p in recent if abs(series[p] - series[anchor]) <= CLUSTER_ATR * atr[i]]
                if len(group) > len(best) or (len(group) == len(best) and group and group[-1] > best[-1]):
                    best = group
            if len(best) < TOUCHES:
                continue
            cluster = best
            level = float(np.mean([series[p] for p in cluster]))
            window = slice(max(0, i - 2), i + 1)
            if direction == SHORT:
                touched = high[window].max() >= level - TEST_ATR * atr[i]
                rejected = close[i] <= level - REJECT_ATR * atr[i] and close[i] < open_[i]
                extreme, swept = float(high[window].max()), bool(high[window].max() > level)
            else:
                touched = low[window].min() <= level + TEST_ATR * atr[i]
                rejected = close[i] >= level + REJECT_ATR * atr[i] and close[i] > open_[i]
                extreme, swept = float(low[window].min()), bool(low[window].min() < level)
            if not (touched and rejected):
                continue
            last = last_event.get(direction)
            if last and i - last[0] < COOLDOWN_BARS and abs(level - last[1]) <= CLUSTER_ATR * atr[i]:
                continue            # dezelfde afwijzing blijft een paar candles 'waar', maar telt één keer
            last_event[direction] = (i, level)
            base = np.mean(vol[i - 20:i])
            out.append({"bar": i, "direction": direction, "level": level, "touches": len(cluster), "extreme": extreme, "atr": float(atr[i]),
                        "vol_ratio": float(vol[i] / base) if base > 0 else float("nan"), "swept": swept})
    return pd.DataFrame(out, columns=["bar", "direction", "level", "touches", "extreme", "atr", "vol_ratio", "swept"])


def plan_for(ev, b: pd.DataFrame, floor_stop) -> Optional[dict]:
    """Instap op het slot van de afwijzende candle, stop voorbij de uiterste prik (met de minimale stopafstand van `floor_stop`), doelen op
    zwaaipunten die minstens 1R verderop liggen of anders een ladder van 1, 2 en 3R. None als de stop te ver ligt."""
    entry = float(b["close"].iloc[int(ev.bar)])
    short = ev.direction == SHORT
    raw_stop = ev.extreme + STOP_ATR * ev.atr if short else ev.extreme - STOP_ATR * ev.atr
    stop = floor_stop(ev.direction, entry, raw_stop)
    risk = abs(entry - stop)
    if risk <= 0 or risk / entry * 100 > MAX_STOP_PCT or (short and stop <= entry) or (not short and stop >= entry):
        return None
    p_high, p_low = br._pivots(b)
    levels = br.known_levels(b, p_high, p_low, ev.direction, int(ev.bar))
    nearest = br.ladder_targets(ev.direction, entry, risk, "niveaus", levels)
    ladder = nearest or br.ladder_targets(ev.direction, entry, risk, "ladder 1-2-3R", levels)
    r_list = ladder[0]
    sign = -1 if short else 1
    return {"entry": entry, "stop": stop, "risk_pct": risk / entry * 100, "targets_r": list(r_list),
            "targets": [entry + sign * risk * r for r in r_list], "from_levels": nearest is not None}


def diagnose(bars: pd.DataFrame, i: int, direction: str) -> dict:
    """Waarom de detector op candle i geen afwijzing zag: het beste niveau, de aanrakingen en hoe ver de candle van de eisen zat."""
    b = add_indicators(bars).reset_index(drop=True)
    high, low, close, open_ = (b[c].to_numpy() for c in ("high", "low", "close", "open"))
    atr = float(b["atr"].iloc[i])
    p_high, p_low = br._pivots(b.iloc[: i + 1])
    series = high if direction == SHORT else low
    flags = p_high if direction == SHORT else p_low
    pivots = [p for p in range(max(0, i - LOOKBACK), i - 1) if p + br.PIVOT_K <= i and flags[p]]
    best: list[int] = []
    for anchor in pivots:
        group = [p for p in pivots if abs(series[p] - series[anchor]) <= CLUSTER_ATR * atr]
        if len(group) > len(best):
            best = group
    level = float(np.mean([series[p] for p in best])) if best else None
    out = {"atr": atr, "touches": len(best), "level": level}
    if level is not None:
        window = slice(max(0, i - 2), i + 1)
        if direction == SHORT:
            out["gap_to_level_atr"] = float((level - high[window].max()) / atr)       # positief: de prik bleef onder het niveau
            out["close_from_level_atr"] = float((level - close[i]) / atr)               # moet minstens REJECT_ATR zijn
            out["bearish"] = bool(close[i] < open_[i])
        else:
            out["gap_to_level_atr"] = float((low[window].min() - level) / atr)
            out["close_from_level_atr"] = float((close[i] - level) / atr)
            out["bullish"] = bool(close[i] > open_[i])
    return out


def run(frame_1m: pd.DataFrame, cost_pct: float = 0.06) -> pd.DataFrame:
    """Toets van de Rejectie-regel op 1m-candles: één rij per afwijzing, instap op het slot van de afwijzende 30m-candle, stop en doelen
    zoals live (plan_for met smc_eval.floor_stop), ladder met een derde per doel en de stop naar de instap na het eerste doel."""
    from app import smc_eval
    from app.replay.lab import make_bars
    bars = make_bars(frame_1m, br.BAR_MINUTES)
    events = find_rejections(bars)
    cols = ["at", "direction", "swept", "touches", "vol_ratio", "risk_pct", "net", "outcome", "target_r"]
    if events.empty:
        return pd.DataFrame(columns=cols)
    b = add_indicators(bars).reset_index(drop=True)
    m = br.Minutes(frame_1m)
    rows = []
    for ev in events.itertuples():
        plan = plan_for(ev, b, smc_eval.floor_stop)
        if plan is None:
            continue
        k = m.index(b.at[int(ev.bar), "close_time"])
        if k >= len(m.high):
            continue
        r_list = tuple(plan["targets_r"])
        fractions = tuple(1 / len(r_list) for _ in r_list)
        w = m.window(k)
        _, net, outcome = br.simulate(ev.direction, plan["entry"], plan["stop"], r_list, fractions, True, m.high[w], m.low[w], m.close[w], cost_pct)
        rows.append({"at": b.at[int(ev.bar), "close_time"], "direction": ev.direction, "swept": ev.swept, "touches": int(ev.touches),
                     "vol_ratio": ev.vol_ratio, "risk_pct": plan["risk_pct"], "net": net, "outcome": outcome, "target_r": r_list[-1]})
    return pd.DataFrame(rows, columns=cols)
