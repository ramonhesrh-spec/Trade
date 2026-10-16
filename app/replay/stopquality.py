"""Stopkwaliteit zonder vast doel: wat doet de stop van een setup, los van waar jij winst neemt. Per gevulde setup: stopafstand, kosten in R,
MAE en MFE, uren tot de stop, of +1R tot +6R vóór de stop kwamen, of de stop te krap was, en ter vergelijking drie referentie-uitgangen.
Regels in docs/onderzoek/range-sweep/preregistratie.md. Pure functies op 15m-candles; niets kijkt naar candles voor `start` of voorbij de uitkomst
(behalve de te-krap-meting, die per definitie na de stop kijkt)."""
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import trendlab as tl

TTL_15M = 96
HORIZON_15M = 672
TIGHT_BACK_15M = 48
TIGHT_WIN_15M = 192
# Tot 6R: de doelen in de voorbeelden lagen op 5 tot 14R. De tabel laat zien wat de stop toelaat, geen doel.
R_LEVELS = (1, 2, 3, 4, 5, 6)
TRAIL_K = 3.0
REF_NAMES = ("mid", "opp", "trail")


def atr_on_15m(b15: pd.DataFrame, b1h: pd.DataFrame) -> np.ndarray:
    """Per 15m-candle de ATR van de laatste 1u-candle die bij het openen gesloten was."""
    frame = pd.DataFrame({"timestamp": b1h["timestamp"] + pd.Timedelta(hours=1), "atr": b1h["atr"].to_numpy(float)})
    return pd.merge_asof(b15[["timestamp"]].reset_index(drop=True), frame, on="timestamp")["atr"].to_numpy(float)


def simulate_fills(direction: str, legs: list[tuple[float, float]], stop: float, mid: float, b15: pd.DataFrame, start: int) -> dict:
    """Vulling tegen de limietprijs. Vóór de eerste vulling vervalt de setup als een candle voorbij de stop opent, of als de koers het midden van de
    range raakt; na TTL_15M candles vervalt hij. Na de eerste vulling vullen de andere orders tot TTL of tot de candle waarin de stop geraakt wordt.
    Vult een been in dezelfde candle als het midden of de stop geraakt wordt, dan telt de vulling (de volgorde binnen de candle is onbekend en
    `measure` rekent de stop dan als eerste)."""
    short = direction == "short"
    op, hi, lo = (b15[c].to_numpy(float) for c in ("open", "high", "low"))
    waiting, filled = list(legs), []
    for m in range(max(start, 0), min(len(hi), start + TTL_15M)):
        if not filled and ((op[m] >= stop) if short else (op[m] <= stop)):
            return {"filled": [], "first": None, "cancel": "stop voor vulling"}
        for leg in list(waiting):
            if (hi[m] >= leg[1]) if short else (lo[m] <= leg[1]):
                filled.append((leg[0], leg[1], m))
                waiting.remove(leg)
        if not filled and ((lo[m] <= mid) if short else (hi[m] >= mid)):
            return {"filled": [], "first": None, "cancel": "weggelopen"}
        if filled and (not waiting or ((hi[m] >= stop) if short else (lo[m] <= stop))):
            break
    if not filled:
        return {"filled": [], "first": None, "cancel": "verlopen"}
    return {"filled": filled, "first": filled[0][2], "cancel": ""}


def _ref_target(direction, entry, risk, stop, b15, first, last, target) -> Optional[float]:
    """Bruto R bij uitstappen op `target`, met de stop eerst als beide in een candle vallen; de vulcandle telt alleen tegen. Op het einde van de horizon op de close."""
    short = direction == "short"
    if (target >= entry) if short else (target <= entry):
        return None
    op, hi, lo, cl = (b15[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    for m in range(first, last + 1):
        if (hi[m] >= stop) if short else (lo[m] <= stop):
            fill = max(op[m], stop) if short else min(op[m], stop)
            return ((entry - fill) if short else (fill - entry)) / risk
        if m > first and ((lo[m] <= target) if short else (hi[m] >= target)):
            return abs(target - entry) / risk
    return ((entry - cl[last]) if short else (cl[last] - entry)) / risk


def measure(direction: str, filled: list[tuple[float, float, int]], stop: float, b15: pd.DataFrame, atr15: np.ndarray,
            range_high: float, range_low: float, cost_pct: float) -> dict:
    """R-eenheid: het risico dat echt genomen is (gewogen instap tot de stop over de gevulde orders), zodat een stop-uit -1R is hoeveel orders er
    ook vulden. In de vulcandle telt alleen het nadeel. Een candle die de stop en een R-niveau raakt telt als stop. De ref_* zijn bruto R (zonder
    kosten); `cost_r` is de kosten van een rondreis in dezelfde eenheid."""
    short = direction == "short"
    weight = sum(w for w, _, _ in filled)
    if not filled or weight <= 0:
        raise ValueError("measure heeft minstens één gevulde order met gewicht nodig")
    entry = sum(w * p for w, p, _ in filled) / weight
    risk = (stop - entry) if short else (entry - stop)
    if risk <= 0:
        raise ValueError("de stop ligt niet voorbij de instap")
    first = filled[0][2]
    op, hi, lo, cl = (b15[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    last = min(len(cl), first + HORIZON_15M) - 1
    mae = mfe = 0.0
    reach = {k: False for k in R_LEVELS}
    stop_idx, stop_r = None, None
    for m in range(first, last + 1):
        adverse = ((hi[m] - entry) if short else (entry - lo[m])) / risk
        if (hi[m] >= stop) if short else (lo[m] <= stop):
            fill = max(op[m], stop) if short else min(op[m], stop)
            stop_idx, stop_r = m, ((entry - fill) if short else (fill - entry)) / risk
            mae = max(mae, -stop_r)
            break
        mae = max(mae, adverse)
        if m > first:
            fav = ((entry - lo[m]) if short else (hi[m] - entry)) / risk
            mfe = max(mfe, fav)
            for k in R_LEVELS:
                reach[k] = reach[k] or fav >= k
    back = win_after = False
    if stop_idx is not None:
        edge = range_high if short else range_low
        bw = slice(stop_idx + 1, min(len(cl), stop_idx + 1 + TIGHT_BACK_15M))
        back = bool(((cl[bw] < edge) if short else (cl[bw] > edge)).any())
        ww = slice(stop_idx + 1, min(len(cl), stop_idx + 1 + TIGHT_WIN_15M))
        win_after = bool(((lo[ww] <= entry - risk) if short else (hi[ww] >= entry + risk)).any())
    mid, opp = (range_high + range_low) / 2, (range_low if short else range_high)
    # De vulcandle is hierboven al tegen de stop getoetst; de meelopende stop begint op de candle erna.
    if stop_idx == first:
        trail = stop_r
    else:
        trail = tl.exit_trail(b15.assign(atr=atr15), first + 1, -1 if short else 1, entry, stop, TRAIL_K, HORIZON_15M - 1)[0]
    a0 = atr15[first] if np.isfinite(atr15[first]) and atr15[first] > 0 else float("nan")
    return {"entry": entry, "stop": stop, "weight": weight, "stop_pct": risk / entry * 100, "stop_atr": risk / a0, "cost_r": cost_pct / 100 * entry / risk,
            "stop_hit": stop_idx is not None, "stop_r": stop_r, "hours_to_stop": None if stop_idx is None else (stop_idx - first) / 4,
            "mae_r": mae, "mfe_r": mfe, **{f"reach_{k}r": reach[k] for k in R_LEVELS},
            "back_in_range": back, "win_after_stop": win_after, "tight": back and win_after,
            "ref_mid": _ref_target(direction, entry, risk, stop, b15, first, last, mid),
            "ref_opp": _ref_target(direction, entry, risk, stop, b15, first, last, opp), "ref_trail": float(trail)}
