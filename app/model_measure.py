"""Meting van het HesPulse-model voor de eerste evaluatie en het besluit (preregistratie §7 "Wat ontbreekt" en §8). Alleen meting: geen motor,
filter of melding leest dit. Pure functies; de route (Bewijs) en scripts/nacht_export.py geven de rijen mee.

  - uitvoerbaarheid: vulbaar na publicatie, gevuld, niet_vulbaar, 'terugtest al geweest', vertraging van herkenbaar tot in de app (A en B);
  - netto R per trade (zoals Bewijs: track_record.net_signal_r, kosten en funding), interval per ISO-week op 98,75% (Bonferroni, vier toetsen);
  - N_eff: trades in dezelfde richting waarvan de looptijden overlappen (ook via een keten) zijn één cluster;
  - langste verliesreeks, grootste daling, en het 95e percentiel van de grootste daling bij 2000 herschikkingen;
  - gemiddelde zonder de beste 5% (naar boven afgerond, minstens één), en per helft op tijd;
  - de trechter per scenario (A, sweep, shift, B, gevuld, uitkomst);
  - V1 − H, V2 − H en V3 − H met cluster_bootstrap_diff op hetzelfde niveau (alleen voor de CEO)."""
import json
import math
import random
from datetime import datetime, timezone
from statistics import median
from typing import Iterable, Optional

from app.replay import stats

LEVEL = 0.9875                  # 95% met Bonferroni voor vier toetsen (§8)
SHUFFLES = 2000
SEED = 7
FIRST_EVAL_TRADES = 50          # §8: eerste evaluatie, alleen technisch
DECISION_TRADES, DECISION_WEEKS, DECISION_NEFF = 150, 12, 60


def _dt(v) -> Optional[datetime]:
    if not v:
        return None
    d = datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def n_eff(trades: list[dict]) -> int:
    """trades: {direction, start, end} (datetimes). Per richting gesorteerd op begin; een trade die begint voordat het cluster klaar is, hoort
    erbij (de keten verlengt het cluster)."""
    clusters = 0
    for d in {t["direction"] for t in trades}:
        end = None
        for t in sorted((t for t in trades if t["direction"] == d), key=lambda t: t["start"]):
            if end is None or t["start"] > end:
                clusters += 1
                end = t["end"]
            else:
                end = max(end, t["end"])
    return clusters


def cluster_ids(trades: list[dict]) -> list[int]:
    """Het cluster van elke trade (zelfde volgorde als de invoer), voor het gemiddelde per cluster."""
    ids = [0] * len(trades)
    k = 0
    for d in sorted({t["direction"] for t in trades}):
        end = None
        for i in sorted((i for i, t in enumerate(trades) if t["direction"] == d), key=lambda i: trades[i]["start"]):
            if end is None or trades[i]["start"] > end:
                k += 1
                end = trades[i]["end"]
            else:
                end = max(end, trades[i]["end"])
            ids[i] = k
    return ids


def longest_losing_streak(rs: list[float]) -> int:
    best = cur = 0
    for r in rs:
        cur = cur + 1 if r < 0 else 0
        best = max(best, cur)
    return best


def max_drawdown(rs: Iterable[float]) -> float:
    peak = total = dd = 0.0
    for r in rs:
        total += r
        peak = max(peak, total)
        dd = max(dd, peak - total)
    return dd


def shuffled_drawdown_p95(rs: list[float], n: int = SHUFFLES, seed: int = SEED) -> Optional[float]:
    """Het 95e percentiel van de grootste daling bij n willekeurige volgordes van dezelfde trades (zelfde gemiddelde)."""
    if len(rs) < 2:
        return None
    rng = random.Random(seed)
    xs = list(rs)
    dds = []
    for _ in range(n):
        rng.shuffle(xs)
        dds.append(max_drawdown(xs))
    dds.sort()
    return dds[min(len(dds) - 1, int(0.95 * len(dds)))]


def mean_without_best(rs: list[float], share: float = 0.05) -> Optional[float]:
    if len(rs) < 2:
        return None
    k = max(1, math.ceil(share * len(rs)))
    rest = sorted(rs)[:-k]
    return sum(rest) / len(rest) if rest else None


def _mean(xs: list[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def _q(xs: list[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def arm(trades: list[dict]) -> dict:
    """trades: {net, direction, start, end} met end het moment van de uitkomst. Alle maten van §8 voor één arm, op volgorde van uitkomst."""
    ts = sorted(trades, key=lambda t: t["end"])
    rs = [t["net"] for t in ts]
    weeks = [stats.week_key(t["end"]) for t in ts]
    out = {"n": len(rs), "mean": _mean(rs), "ci": None, "weeks": len(set(weeks)), "n_eff": n_eff(ts), "cluster_mean": None,
           "streak": longest_losing_streak(rs), "max_dd": max_drawdown(rs), "dd_p95": shuffled_drawdown_p95(rs), "dd_flag": False,
           "mean_wo_best": mean_without_best(rs), "half1": None, "half2": None}
    if rs:
        out["ci"] = stats.cluster_bootstrap_mean(rs, weeks, level=LEVEL)
        ids = cluster_ids(ts)
        per = {}
        for r, c in zip(rs, ids):
            per.setdefault(c, []).append(r)
        out["cluster_mean"] = _mean([_mean(v) for v in per.values()])
        h = len(rs) // 2
        out["half1"], out["half2"] = _mean(rs[:h]), _mean(rs[h:])
        out["dd_flag"] = out["dd_p95"] is not None and out["max_dd"] > out["dd_p95"]
    return out


def diff(a: list[dict], b: list[dict]) -> Optional[tuple[float, float]]:
    """Interval van gemiddelde(a) − gemiddelde(b) per gedeelde ISO-week, op LEVEL."""
    if not a or not b:
        return None
    return stats.cluster_bootstrap_diff([t["net"] for t in a], [stats.week_key(t["end"]) for t in a], [t["net"] for t in b],
                                        [stats.week_key(t["end"]) for t in b], level=LEVEL)


def signal_trades(rows: list[dict], trade_type: str, cost_pct: float) -> list[dict]:
    """Afgeronde signalen (doel of stop) van één soort, netto zoals Bewijs. Oefentrades tellen nooit."""
    from app import track_record
    out = []
    for r in rows:
        if r.get("trade_type") != trade_type or r.get("is_practice") or r.get("auto_outcome") not in ("take_profit", "stop_loss"):
            continue
        net = track_record.net_signal_r(r, cost_pct)
        start, end = _dt(r.get("created_at")), _dt(r.get("auto_outcome_at"))
        if net is None or start is None or end is None:
            continue
        stop_pct = abs(r["price"] - r["stop_loss"]) / r["price"] * 100 if r.get("price") else None
        out.append({"net": net, "direction": r["direction"], "start": start, "end": end, "cost_r": cost_pct / stop_pct if stop_pct else None,
                    "funding_unknown": r.get("funding_r") is None})
    return out


def v1_trades(rows: list[dict], cost_pct: float) -> list[dict]:
    """V1 uit model_v1: bruto R op 5m min de kosten van een rondreis in R. Funding wordt voor V1 niet gemeten (geen signaal); dat staat erbij."""
    out = []
    for v in rows:
        if v.get("outcome") not in ("take_profit", "stop_loss") or v.get("r_gross") is None:
            continue
        stop_pct = abs(v["limit_price"] - v["stop_loss"]) / v["limit_price"] * 100
        out.append({"net": v["r_gross"] - (cost_pct / stop_pct if stop_pct else 0.0), "direction": v["direction"], "start": _dt(v["filled_at"]),
                    "end": _dt(v["outcome_at"])})
    return out


def _minutes(a, b) -> Optional[float]:
    a, b = _dt(a), _dt(b)
    return (b - a).total_seconds() / 60 if a and b else None


def execution(scenarios: list[dict]) -> dict:
    """Uitvoerbaarheid uit model_scenarios (§8 maat 1)."""
    published = [s for s in scenarios if s.get("entry_detected_at")]
    attempts = []
    for s in scenarios:
        try:
            attempts += json.loads(s.get("steps") or "{}").get("attempts") or []
        except ValueError:
            pass
    delay_a = [m for s in scenarios if (m := _minutes(s.get("discovered_at"), s.get("detected_at"))) is not None]
    delay_b = [m for s in published if (m := _minutes(s.get("entry_at"), s.get("entry_detected_at"))) is not None]
    n = len(published)
    fillable = [s for s in published if s.get("vulbaar") == 1]
    return {"published": n, "vulbaar": len(fillable), "vulbaar_pct": len(fillable) / n * 100 if n else None,
            "gevuld": sum(1 for s in published if s.get("entry_state") == "gevuld"),
            "gevuld_na_vulbaar_pct": (sum(1 for s in fillable if s.get("entry_state") == "gevuld") / len(fillable) * 100) if fillable else None,
            "niet_vulbaar": sum(1 for s in published if s.get("entry_state") == "niet_vulbaar"),
            "terugtest_al_geweest": sum(1 for a in attempts if a.get("reden") == "terugtest_al_geweest"),
            "delay_a_median": median(delay_a) if delay_a else None, "delay_a_p90": _q(delay_a, 0.9),
            "delay_b_median": median(delay_b) if delay_b else None, "delay_b_p90": _q(delay_b, 0.9)}


def funnel(scenarios: list[dict], outcomes: dict) -> dict:
    """A → sweep → shift → B → gevuld → uitkomst. outcomes: {signal_id: auto_outcome}. Een sweep of shift in een mislukte poging telt mee."""
    def had(s, stap):
        try:
            d = json.loads(s.get("steps") or "{}")
        except ValueError:
            return False
        return any(x["stap"] == stap for x in d.get("steps") or []) or any(y["stap"] == stap for a in d.get("attempts") or [] for y in a.get("steps") or [])
    return {"ontdekt": len(scenarios), "sweep": sum(1 for s in scenarios if had(s, "sweep")), "shift": sum(1 for s in scenarios if had(s, "shift")),
            "entry": sum(1 for s in scenarios if s.get("entry_detected_at")), "gevuld": sum(1 for s in scenarios if s.get("entry_state") == "gevuld"),
            "uitkomst": sum(1 for s in scenarios if outcomes.get(s.get("signal_id")) in ("take_profit", "stop_loss"))}


def report(scenarios: list[dict], v1: list[dict], signal_rows: list[dict], cost_pct: float, ceo: bool = False) -> dict:
    """Alles voor Bewijs en de nachtexport. De vergelijkingen (V1, V2, V3) alleen met ceo=True."""
    h = signal_trades(signal_rows, "hespulse_model", cost_pct)
    costs = [t["cost_r"] for t in h if t["cost_r"] is not None]
    out = {"execution": execution(scenarios), "funnel": funnel(scenarios, {r["id"]: r.get("auto_outcome") for r in signal_rows if r.get("id")}),
           "h": arm(h), "cost_median_r": median(costs) if costs else None, "funding_unknown": sum(1 for t in h if t["funding_unknown"]),
           "level": LEVEL, "first_eval_ready": len(h) >= FIRST_EVAL_TRADES,
           "decision_ready": len(h) >= DECISION_TRADES and arm(h)["weeks"] >= DECISION_WEEKS and n_eff(h) >= DECISION_NEFF}
    if ceo:
        v1t = v1_trades(v1, cost_pct)
        v2, v3 = signal_trades(signal_rows, "zone_sweep", cost_pct), signal_trades(signal_rows, "poc_radar", cost_pct)
        out["compare"] = [{"key": "V1", "label": "V1 vroege limiet op de pool", "arm": arm(v1t), "diff": diff(v1t, h), "note": "zonder funding"},
                          {"key": "V2", "label": "V2 Zone-sweep (referentie)", "arm": arm(v2), "diff": diff(v2, h), "note": ""},
                          {"key": "V3", "label": "V3 POC-radar (referentie)", "arm": arm(v3), "diff": diff(v3, h), "note": ""}]
    return out


def r_text(x: Optional[float]) -> str:
    return "–" if x is None else f"{x:+.2f}".replace(".", ",").replace("-", "−") + " R"


def ci_text(ci: Optional[tuple[float, float]]) -> str:
    return "–" if not ci else f"{r_text(ci[0])} tot {r_text(ci[1])}"


def jsonable(rep: dict) -> dict:
    """Voor de nachtexport: tuples als lijsten, None blijft None."""
    return json.loads(json.dumps(rep, default=lambda o: list(o) if isinstance(o, tuple) else str(o)))
