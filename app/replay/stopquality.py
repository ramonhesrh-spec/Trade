"""Stopkwaliteit zonder vast doel: wat doet de stop van een setup, los van waar jij winst neemt. Per gevulde setup: stopafstand, kosten in R,
MAE en MFE, uren tot de stop, of +1R tot +6R vóór de stop kwamen, of de stop te krap was, en ter vergelijking drie referentie-uitgangen.
Regels in docs/onderzoek/range-sweep/preregistratie.md. Pure functies op 15m-candles; niets kijkt naar candles voor `start` of voorbij de uitkomst
(behalve de te-krap-meting, die per definitie na de stop kijkt)."""
from typing import Optional

import numpy as np
import pandas as pd

from app import smc_eval
from app.replay import rangesweep as rs, stats
from app.replay import trendlab as tl

TTL_15M = 96
HORIZON_15M = 672
TIGHT_BACK_15M = 48
TIGHT_WIN_15M = 192
# Tot 6R: de doelen in de voorbeelden lagen op 5 tot 14R. De tabel laat zien wat de stop toelaat, geen doel.
R_LEVELS = (1, 2, 3, 4, 5, 6)
TRAIL_K = 3.0
REF_NAMES = ("mid", "opp", "trail")
# De drempels van de toets op stopkwaliteit. Bevroren in docs/onderzoek/range-sweep/preregistratie.md (blok prereg-constants); een test toetst
# ze daartegen en dat `accept` en `kill_check` geen eigen getal gebruiken. Niet aanpassen na een run.
MIN_FILLS = 300
MIN_WEEKS = 80
MAX_MEDIAN_COST_R = 0.10
MAX_HALF_DIFF = 0.10
MAX_BLOCK_DIFF = 0.15
N_BLOCKS = 6
MIN_PLACEBO_EDGE = 0.05
MAX_TIGHT_RATE = 0.25
# Het aantal toetsen waarover S2 en S3 beslissen (15 varianten, samen 30 toetsen, pre-registratie 'Varianten').
KILL_TESTS = 30


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


def _ref_target(direction, entry, risk, stop, b15, first, last, target, full) -> Optional[float]:
    """Bruto R bij uitstappen op `target`, met de stop eerst als beide in een candle vallen; de vulcandle (bij een split tot en met de laatste vulling) telt alleen tegen. Op het einde van de horizon op de close."""
    short = direction == "short"
    if (target >= entry) if short else (target <= entry):
        return None
    op, hi, lo, cl = (b15[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    for m in range(first, last + 1):
        if (hi[m] >= stop) if short else (lo[m] <= stop):
            fill = max(op[m], stop) if short else min(op[m], stop)
            return ((entry - fill) if short else (fill - entry)) / risk
        if m > full and ((lo[m] <= target) if short else (hi[m] >= target)):
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
    # Bij een split bestaat de volledige positie pas na de laatste vulling: een gunstige beweging daarvoor trof maar een deel van de orders en telt niet,
    # net als in de vulcandle zelf alleen het nadeel telt. De stop geldt wel vanaf de eerste vulling.
    full = max(m for _, _, m in filled)
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
        if m > full:
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
    # De vulcandle is hierboven al tegen de stop getoetst; de meelopende stop begint op de candle na de laatste vulling.
    if stop_idx is not None and stop_idx <= full:
        trail = stop_r
    else:
        trail = tl.exit_trail(b15.assign(atr=atr15), full + 1, -1 if short else 1, entry, stop, TRAIL_K, HORIZON_15M - 1 - (full - first))[0]
    a0 = atr15[first] if np.isfinite(atr15[first]) and atr15[first] > 0 else float("nan")
    return {"entry": entry, "stop": stop, "weight": weight, "stop_pct": risk / entry * 100, "stop_atr": risk / a0, "cost_r": cost_pct / 100 * entry / risk,
            "stop_hit": stop_idx is not None, "stop_r": stop_r, "hours_to_stop": None if stop_idx is None else (stop_idx - first) / 4,
            "mae_r": mae, "mfe_r": mfe, **{f"reach_{k}r": reach[k] for k in R_LEVELS},
            "back_in_range": back, "win_after_stop": win_after, "tight": back and win_after,
            "ref_mid": _ref_target(direction, entry, risk, stop, b15, first, last, mid, full),
            "ref_opp": _ref_target(direction, entry, risk, stop, b15, first, last, opp, full), "ref_trail": float(trail)}


def _pp(x: float) -> str:
    return f"{x * 100:.0f} procentpunt"


def _share(f: pd.DataFrame, col: str, weeks: list) -> dict:
    vals = f[col].astype(float).tolist()
    lo, hi = stats.cluster_bootstrap_mean(vals, weeks)
    return {"p": float(np.mean(vals)), "ci": (lo, hi)}


def summarize(rows: pd.DataFrame) -> dict:
    """Samenvatting van één variant met één stop, uit de rijen van `measure` plus `filled`, `cancel`, `at` en `grade`. Ongevulde rijen tellen
    alleen als setup. Alles is historisch en beschrijvend: een kans of een kost, geen belofte. De ref_* staan ernaast; de kop is de stopkwaliteit."""
    setups = len(rows)
    if not setups:
        return {"setups": 0, "n": 0, "fill_rate": 0.0, "cancels": {}}
    filled_mask = rows["filled"].astype(bool)
    f = rows[filled_mask].sort_values("at", kind="stable")
    cancels = {k: int(v) for k, v in rows.loc[~filled_mask, "cancel"].value_counts().items()}
    out = {"setups": setups, "n": len(f), "fill_rate": len(f) / setups, "cancels": cancels}
    if f.empty:
        return out
    weeks = [stats.week_key(t) for t in f["at"]]
    cut = np.array_split(np.arange(len(f)), 2)
    halves = [f.iloc[c] for c in cut]
    blocks = [f.iloc[c] for c in np.array_split(np.arange(len(f)), N_BLOCKS)] if len(f) >= N_BLOCKS else [f]
    stopped = f[f["stop_hit"].astype(bool)]
    q = (0.25, 0.5, 0.75, 0.9)
    ref = {}
    for name in REF_NAMES:
        ok = f[f[f"ref_{name}"].notna()]
        net = (ok[f"ref_{name}"].astype(float) - ok["cost_r"].astype(float)).tolist()
        ref[name] = {"n": len(net), "avg_net": float(np.mean(net)) if net else None,
                     "ci": stats.cluster_bootstrap_mean(net, [stats.week_key(t) for t in ok["at"]]) if net else (0.0, 0.0)}
    by_grade = {g: {"n": len(p), "reach1": float(p["reach_1r"].mean()), "stop_hit": float(p["stop_hit"].mean())}
                for g, p in f.groupby("grade")} if "grade" in f else {}
    out.update({"weeks": len(set(weeks)), "median_stop_pct": float(f["stop_pct"].median()), "median_stop_atr": float(f["stop_atr"].median()),
                "median_cost_r": float(f["cost_r"].median()), "share_cost_over_01": float((f["cost_r"] > 0.1).mean()),
                "stop_hit": _share(f, "stop_hit", weeks), "reach": {k: _share(f, f"reach_{k}r", weeks) for k in R_LEVELS},
                "median_hours_to_stop": float(stopped["hours_to_stop"].median()) if len(stopped) else None,
                "mae_q": [float(f["mae_r"].quantile(x)) for x in q], "mfe_q": [float(f["mfe_r"].quantile(x)) for x in q],
                "tight_rate": float(stopped["tight"].mean()) if len(stopped) else 0.0,
                "halves": tuple(float(h["reach_1r"].mean()) for h in halves), "blocks": [float(b["reach_1r"].mean()) for b in blocks],
                "ref": ref, "by_grade": by_grade})
    return out


def doelkans_table(summary: dict) -> list[dict]:
    """De tabel die de gebruiker leest: hoe vaak +1R tot +6R vóór de stop kwamen, met de marge per week. Historisch, geen belofte."""
    if not summary.get("n"):
        return []
    return [{"r": k, "p_text": f"{summary['reach'][k]['p'] * 100:.0f}%",
             "ci_text": f"{summary['reach'][k]['ci'][0] * 100:.0f} tot {summary['reach'][k]['ci'][1] * 100:.0f}%", "n": summary["n"]} for k in R_LEVELS]


def placebo_rows(real: pd.DataFrame, b15: pd.DataFrame, bt: pd.DataFrame, active: list, atr15: np.ndarray, cost_pct: float,
                 seed: int = 0, draws: int = 1) -> pd.DataFrame:
    """Per gevulde echte trade `draws` willekeurige instappen: een willekeurig slot van de triggerframe binnen een actieve range van dezelfde coin en
    timeframe (het slot ligt binnen de range), zelfde kant, instap op dat slot, stop op dezelfde afstand in 1u-ATR (`stop_atr`) als de echte
    trade, daarna floor_stop, zelfde meting. `pair_id` koppelt aan de echte trade voor het verschil per paar. Van de echte trade gebruikt dit
    alleen kant, stopafstand en id, nooit zijn uitkomst, en de trekking hangt alleen af van de seed: twee runs geven dezelfde rijen. Meer trekkingen
    per trade maken het gemiddelde van de placebo stabieler; `accept` middelt ze per paar. Een willekeurig slot kan ook een slot zijn waarop de
    echte regel niets zou doen: dat is de bedoeling, de placebo laat zien wat dezelfde stop op een willekeurige plek doet."""
    rng = np.random.default_rng(seed)
    cl, ts = bt["close"].to_numpy(float), bt["timestamp"]
    if len(ts) < 2:
        return pd.DataFrame()
    delta = ts.diff().dropna().min()
    ts15 = b15["timestamp"].to_numpy()
    # De eerste 15m-candle na het slot moet bestaan en een bekende ATR hebben, anders valt het slot hier al af en schuift de trekking niet op.
    nxt = np.searchsorted(ts15, (ts + delta).to_numpy())
    cand = [j for j, r in enumerate(active) if r is not None and r.low < cl[j] < r.high and nxt[j] < len(ts15) and np.isfinite(atr15[nxt[j]])]
    out = []
    if not cand:
        return pd.DataFrame()
    filled = real[real["filled"].astype(bool)] if "filled" in real else real
    for row in filled.itertuples():
        if not (np.isfinite(row.stop_atr) and row.stop_atr > 0):
            continue
        short = row.direction == "short"
        for _ in range(draws):
            j = cand[int(rng.integers(0, len(cand)))]
            r, first = active[j], int(nxt[j])
            entry = float(cl[j])
            stop = smc_eval.floor_stop(row.direction, entry, entry + (1 if short else -1) * float(row.stop_atr) * atr15[first], min_pct=rs.MIN_STOP_PCT)
            m = measure(row.direction, [(1.0, entry, first)], stop, b15, atr15, r.high, r.low, cost_pct)
            out.append({"pair_id": row.row_id, "at": ts.iloc[j], **m})
    return pd.DataFrame(out)


def accept(summary: dict, real: pd.DataFrame, placebo: pd.DataFrame) -> dict:
    """Toets op stopkwaliteit voor één variant en één stop (pre-registratie, 'Wat we meten en wanneer het telt'), met uitsluitend de bevroren
    constanten van deze module. Een PASS betekent: de stop is stabiel (twee helften, zes blokken), goedkoop (mediane kosten in R) en beter dan
    een willekeurige instap met dezelfde stop. Het betekent NIET dat de variant winst bewijst: dat vraagt de aparte toets op een voordeel.
    `verdict` is 'TE WEINIG TRADES' zolang er te weinig vullingen of weken zijn (nooit een PASS), anders 'PASS' of 'FAIL'."""
    n = summary.get("n", 0)
    if len(real) and "filled" in real:
        real = real[real["filled"].astype(bool)]
    pairs = pd.DataFrame()
    if n and len(placebo):
        plac = placebo.assign(plac=placebo["reach_1r"].astype(float)).groupby("pair_id", as_index=False)["plac"].mean()
        pairs = real.merge(plac, left_on="row_id", right_on="pair_id")
    diff = (pairs["reach_1r"].astype(float) - pairs["plac"].astype(float)).tolist() if len(pairs) else []
    dlo, dhi = stats.cluster_bootstrap_mean(diff, [stats.week_key(t) for t in pairs["at"]]) if diff else (0.0, 0.0)
    dmean = float(np.mean(diff)) if diff else 0.0
    p = summary["reach"][1]["p"] if n else 0.0
    checks = {
        f"genoeg vullingen ({MIN_FILLS})": n >= MIN_FILLS,
        f"genoeg weken ({MIN_WEEKS})": summary.get("weeks", 0) >= MIN_WEEKS,
        f"kosten mediaan hooguit {MAX_MEDIAN_COST_R:.2f}R".replace(".", ","): n > 0 and summary["median_cost_r"] <= MAX_MEDIAN_COST_R,
        f"helften stabiel (hooguit {_pp(MAX_HALF_DIFF)})": n > 0 and abs(summary["halves"][0] - summary["halves"][-1]) <= MAX_HALF_DIFF,
        f"blokken stabiel (hooguit {_pp(MAX_BLOCK_DIFF)})": n > 0 and max(abs(b - p) for b in summary["blocks"]) <= MAX_BLOCK_DIFF,
        f"beter dan willekeurig (+1R vóór de stop minstens {_pp(MIN_PLACEBO_EDGE)})": dmean >= MIN_PLACEBO_EDGE and dlo > 0,
        f"stop niet te krap (hooguit {MAX_TIGHT_RATE * 100:.0f}%)": n > 0 and summary["tight_rate"] <= MAX_TIGHT_RATE,
    }
    passes = all(checks.values())
    thin = n < MIN_FILLS or summary.get("weeks", 0) < MIN_WEEKS
    if passes:
        verdict, reason = "PASS", ""
    elif thin:
        verdict, reason = "TE WEINIG TRADES", f"te weinig trades: {n} vullingen in {summary.get('weeks', 0)} weken (nodig: {MIN_FILLS} en {MIN_WEEKS})"
    else:
        verdict, reason = "FAIL", "faalt: " + ", ".join(k for k, ok in checks.items() if not ok)
    return {"checks": checks, "passes": passes, "verdict": verdict, "reason": reason, "placebo_diff": dmean, "placebo_ci": (dlo, dhi),
            "placebo_pairs": len(diff)}


def kill_check(results: list[dict], tests: int = KILL_TESTS) -> dict:
    """Stopcriteria S2 en S3 van de pre-registratie, vooraf vastgelegd. `results`: per toets {"summary": ..., "accept": ...}. S2: geen enkele
    toets slaagt op stopkwaliteit. S3: bij alle toetsen zijn de mediane kosten hoger dan het maximum; een toets zonder vullingen heeft geen
    mediane kosten en houdt S3 dus tegen. Beslist pas over een volledige set van `tests` toetsen (KILL_TESTS voor de range sweep, de zone-sweep geeft
zonesweep_lab.KILL_TESTS); anders status 'onvolledig' en geen van beide."""
    if len(results) != tests:
        return {"status": "onvolledig", "S2": False, "S3": False, "tests": len(results)}
    s2 = not any(r["accept"]["passes"] for r in results)
    costs = [r["summary"].get("median_cost_r") for r in results]
    s3 = all(c is not None and c > MAX_MEDIAN_COST_R for c in costs)
    return {"status": "volledig", "S2": s2, "S3": s3, "tests": len(results)}
