"""Wat had elke gemelde kans met vast risico per trade per maand gedaan? Zuivere rekenlaag voor scripts/maandrendement.py.
De R-maten komen uit track_record (signal_r met r_override, kosten per stopafstand) zodat dit exact met Bewijs meeloopt;
alleen vaststaande take- of stopuitkomsten tellen, vervallen en open signalen blijven erbuiten."""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app import config, track_record

MIN_MONTHS = 3
MIN_TRADES = 50


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _trades(rows: list[dict], cost_pct: float, trade_types: Optional[list[str]]) -> list[dict]:
    out = []
    for r in rows:
        if trade_types is not None and r.get("trade_type") not in trade_types:
            continue
        net = track_record.net_signal_r(r, cost_pct)
        if net is None:
            continue
        start = _parse(r["created_at"])
        end = _parse(r.get("auto_outcome_at") or r["created_at"])
        out.append({"net_r": net, "win": track_record.signal_r(r) > 0, "start": start, "end": end, "type": r.get("trade_type")})
    out.sort(key=lambda t: t["end"])
    return out


def _overlapping(trades: list[dict]) -> int:
    """Hoeveel trades hadden op enig moment een andere trade open: dan staat er meer dan het risico per trade tegelijk op het spel."""
    count = 0
    for i, a in enumerate(trades):
        if any(i != j and a["start"] < b["end"] and b["start"] < a["end"] for j, b in enumerate(trades)):
            count += 1
    return count


def _empty_totals() -> dict:
    return {"n": 0, "wins": 0, "winrate_pct": None, "avg_net_r": None, "total_return_pct": 0.0, "best_month": None,
            "worst_month": None, "max_drawdown_pct": 0.0, "longest_losing_streak": 0, "overlapping": 0, "end_equity": None}


def simulate(rows: list[dict], risk_pct: float = 1.0, cost_pct: Optional[float] = None, compound: bool = True,
             start_equity: float = 100.0, trade_types: Optional[list[str]] = None) -> dict:
    cost = config.TRACK_RECORD_COST_PCT if cost_pct is None else cost_pct
    trades = _trades(rows, cost, trade_types)
    mode = "samengesteld" if compound else "vast"
    if not trades:
        return {"months": [], "totals": {**_empty_totals(), "end_equity": start_equity},
                "warnings": ["Geen afgeronde trades (take of stop) gevonden: er valt niets te simuleren."]}

    equity = start_equity
    peak, max_dd = equity, 0.0
    streak = longest = 0
    months: dict[str, dict] = {}
    for t in trades:
        key = t["end"].strftime("%Y-%m")
        m = months.setdefault(key, {"month": key, "trades": 0, "wins": 0, "net_r": 0.0, "start_equity": equity})
        equity = equity * (1 + t["net_r"] * risk_pct / 100) if compound else equity + start_equity * t["net_r"] * risk_pct / 100
        m["trades"] += 1
        m["wins"] += t["win"]
        m["net_r"] += t["net_r"]
        m["end_equity"] = equity
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        streak = streak + 1 if t["net_r"] < 0 else 0
        longest = max(longest, streak)

    month_list = []
    for m in (months[k] for k in sorted(months)):
        base = m["start_equity"] if compound else start_equity
        m["return_pct"] = (m["end_equity"] - m["start_equity"]) / base * 100 if base else 0.0
        month_list.append(m)

    n = len(trades)
    wins = sum(t["win"] for t in trades)
    overlapping = _overlapping(trades)
    totals = {
        "n": n, "wins": wins, "winrate_pct": wins / n * 100, "avg_net_r": sum(t["net_r"] for t in trades) / n,
        "total_return_pct": (equity - start_equity) / start_equity * 100,
        "best_month": max(month_list, key=lambda m: m["return_pct"]), "worst_month": min(month_list, key=lambda m: m["return_pct"]),
        "max_drawdown_pct": max_dd, "longest_losing_streak": longest, "overlapping": overlapping, "end_equity": equity,
    }
    warnings = []
    if len(month_list) < MIN_MONTHS:
        warnings.append(f"Pas {len(month_list)} maanden aan data (minder dan {MIN_MONTHS}): een maand zegt weinig over de volgende.")
    if n < MIN_TRADES:
        warnings.append(f"Pas {n} trades (minder dan {MIN_TRADES}): het resultaat kan nog puur toeval zijn.")
    if overlapping:
        warnings.append(f"{overlapping} van {n} trades liepen tegelijk met een andere: {risk_pct:g}% per trade kan dan meer dan {risk_pct:g}% tegelijk riskeren.")
    warnings.append(f"Kosten: {cost:g}% per rondreis, zoals Bewijs; echte kosten en slippage kunnen hoger liggen.")
    warnings.append(f"Rekenwijze {mode}, risico {risk_pct:g}% per trade; elke trade ingelegd op de gemelde instap, in de volgorde van afronding.")
    return {"months": month_list, "totals": totals, "warnings": warnings}


def simulate_by_type(rows: list[dict], **kw) -> dict[str, dict]:
    """De totalen per soort, zodat zichtbaar is welke soorten opleveren en welke kosten."""
    types = sorted({r.get("trade_type") for r in rows if r.get("trade_type")})
    return {t: simulate(rows, trade_types=[t], **kw)["totals"] for t in types}
