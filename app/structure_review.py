"""Beoordeling van de Structuur-motor met aantallen en marges, voor scripts/structure_review.py. Pure functies, geen database.
Doel: 'het gaat goed' vervangen door wat gemeten is. Elke uitkomst heeft een n, een netto cijfer en een betrouwbaarheidsmarge;
onder MIN_N afgeronde trades is een groep te klein voor een conclusie en wordt dat ook zo genoemd."""
import json
import math
import random
from typing import Callable, Optional

from app import chance_checks
from app.track_record import _cost_r, signal_r

MIN_N = 20
BOOTSTRAP = 2000


def net_r(row: dict, cost_pct: float) -> Optional[float]:
    """Resultaat in R van het signaal zoals Bewijs het meet (doel 2 of stop), minus kosten. None zolang er geen uitkomst is."""
    gross = signal_r(row)
    return None if gross is None else gross - _cost_r(row, cost_pct)


def ladder_r(plan_json: Optional[str], cost_r: float = 0.0) -> Optional[float]:
    """Resultaat van de ladder die jij handelt: een derde per doel, stop naar de instap na T1. None zolang de trade loopt.
    Zonder uitkomst in de tijdlijn (nog open) is er geen cijfer."""
    try:
        plan = json.loads(plan_json) if plan_json else {}
    except (TypeError, ValueError):
        return None
    fired = plan.get("fired") or {}
    r_list = plan.get("targets_r") or []
    if not fired or not fired.get("closed") or not r_list:
        return None
    hits = int(fired.get("hits", 0))
    share = 1 / len(r_list)
    realized = sum(r * share for r in r_list[:hits])
    if hits == 0:
        realized = -1.0                      # stop geraakt vóór T1
    return realized - cost_r                 # na T1 staat de stop op de instap: de rest levert 0 op


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_mean(values: list[float], seed: int = 7) -> tuple[float, float]:
    """95%-interval van het gemiddelde door herbemonsteren; vaste seed zodat twee runs hetzelfde zeggen."""
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP))
    return means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]


def summarize(values: list[float]) -> dict:
    n = len(values)
    wins = sum(1 for v in values if v > 0)
    lo, hi = bootstrap_mean(values)
    wlo, whi = wilson(wins, n)
    return {"n": n, "wins": wins, "winrate": wins / n if n else None, "winrate_ci": (wlo, whi), "avg": sum(values) / n if n else None,
            "total": sum(values), "avg_ci": (lo, hi), "enough": n >= MIN_N,
            "verdict": verdict(n, lo, hi)}


def verdict(n: int, lo: float, hi: float) -> str:
    if n < MIN_N:
        return "te klein"
    if lo > 0:
        return "voordeel (marge boven 0)"
    if hi < 0:
        return "verlies (marge onder 0)"
    return "onbeslist (marge omvat 0)"


def max_drawdown(values_in_time_order: list[float]) -> float:
    peak = total = worst = 0.0
    for v in values_in_time_order:
        total += v
        peak = max(peak, total)
        worst = min(worst, total - peak)
    return worst


def longest_losing_streak(values_in_time_order: list[float]) -> int:
    best = run = 0
    for v in values_in_time_order:
        run = run + 1 if v <= 0 else 0
        best = max(best, run)
    return best


def funnel(rows: list[dict]) -> dict:
    """Waar breuken blijven hangen: gezien, plan gemaakt, limiet gevuld, afgerond."""
    states: dict[str, int] = {}
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
    filled = [r for r in rows if r.get("signal_id")]
    done = [r for r in filled if r.get("auto_outcome") in ("take_profit", "stop_loss")]
    return {"gezien": len(rows), "per_status": states, "gevuld": len(filled), "afgerond": len(done)}


def bucket(value: Optional[float], edges: list[float], labels: list[str]) -> str:
    if value is None:
        return "onbekend"
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def features_of(row: dict) -> dict:
    return chance_checks.parse_features(row.get("features"))


DIMENSIONS: dict[str, Callable[[dict], str]] = {
    "oordeel": lambda r: {"A": "sterk (A)", "B": "redelijk (B)", "C": "zwak (C)"}.get(r.get("grade"), "geen oordeel"),
    "soort": lambda r: r["kind"],
    "kant": lambda r: r["direction"],
    "coin": lambda r: r["coin"],
    "met de trend": lambda r: "ja" if features_of(r).get("with_trend") else "nee",
    "aanrakingen": lambda r: bucket(features_of(r).get("touches"), [3, 4], ["2", "3", "4 of meer"]),
    "volume van de breuk": lambda r: bucket(features_of(r).get("vol_ratio"), [1.0, 1.5], ["onder 1x", "1x tot 1,5x", "1,5x of meer"]),
    "lengte structuur": lambda r: bucket(features_of(r).get("span"), [12, 30], ["korter dan 12", "12 tot 30", "30 of langer"]),
    "stopafstand": lambda r: bucket(r.get("risk_pct"), [0.5, 1.0], ["onder 0,5%", "0,5% tot 1%", "1% of meer"]),
    "tweede doel": lambda r: bucket(r.get("target2_r"), [2.0, 3.0], ["onder 2R", "2R tot 3R", "3R of meer"]),
    "wachttijd tot vulling": lambda r: bucket(r.get("wait_hours"), [1.0, 3.0], ["onder 1 uur", "1 tot 3 uur", "3 uur of meer"]),
    "sessie bij vulling (UTC)": lambda r: bucket(r.get("hour_utc"), [7, 13, 21], ["Azië (0-7)", "Londen (7-13)", "New York (13-21)", "nacht (21-24)"]),
}
