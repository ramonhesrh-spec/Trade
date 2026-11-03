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


ENTRY_NAMES = {"B": "B lagere top", "B0": "B0 zonder premium-eis", "R": "R breuk en terugtest", "K": "K consolidatiebreuk", "P": "P POC-limiet"}


def entry_trades(entries: list[dict], code: str, cost_pct: float) -> list[dict]:
    """Eén instappunt uit model_entries (aanvullend besluit 2026-11-03): netto R zoals V1, zonder funding (geen signaal)."""
    out = []
    for e in entries:
        if e.get("code") != code or e.get("outcome") not in ("take_profit", "stop_loss") or e.get("r_gross") is None:
            continue
        stop_pct = abs(e["limit_price"] - e["stop_loss"]) / e["limit_price"] * 100
        out.append({"net": e["r_gross"] - (cost_pct / stop_pct if stop_pct else 0.0), "direction": e["direction"],
                    "start": _dt(e["filled_at"]), "end": _dt(e["outcome_at"])})
    return out


# Stopregel per instappunt (B-2026-11-03-08, vooraf vast, CEO "ja prima"): na FIRST_LOOK afgeronde trades een eerste blik, na DECIDE_N beslist
# het interval van de netto R per week (LEVEL). Ligt dat helemaal onder 0, dan meldt het punt niet meer luid; de stille meting loopt door.
FIRST_LOOK = 30
DECIDE_N = 50
VERDICT_TEXT = {"meten": "meten", "eerste_blik": "eerste blik", "door": "melding blijft", "stop": "geen melding meer: netto duidelijk onder 0"}


def verdict(a: dict) -> str:
    if a["n"] < FIRST_LOOK:
        return "meten"
    if a["n"] < DECIDE_N:
        return "eerste_blik"
    return "stop" if a["ci"] is not None and a["ci"][1] < 0 else "door"


def point_verdict(entries: list[dict], code: str, cost_pct: float) -> str:
    return verdict(arm(entry_trades(entries, code, cost_pct)))


LOUD_CODES = ("B", "B0", "R", "K")


def _htf(raw) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def htf_split(scenarios: list[dict], signal_rows: list[dict], entries: list[dict], cost_pct: float) -> list[dict]:
    """Hogere tijdframes als kenmerk (app/htf_zones.py, B-2026-11-03-09): per kenmerk de afgeronde plannen die melden (A, B, B0, R) met en
    zonder, netto zoals hierboven. Onbekend telt apart, nooit als 'zonder'. Beschrijft, voorspelt niets tot er genoeg trades zijn."""
    from app import htf_zones
    by_signal = {s.get("signal_id"): _htf(s.get("htf")) for s in scenarios if s.get("signal_id")}
    pool = [(t, by_signal.get(r.get("id"), {})) for r in signal_rows for t in signal_trades([r], "hespulse_model", cost_pct)]
    pool += [(t, _htf(e.get("htf"))) for e in entries if e.get("code") in LOUD_CODES for t in entry_trades([e], e["code"], cost_pct)]
    out = []
    for key, label in htf_zones.NAMES.items():
        met = [t for t, f in pool if f.get(key) is True]
        zonder = [t for t, f in pool if f.get(key) is False]
        out.append({"key": key, "label": label, "met": arm(met), "zonder": arm(zonder), "onbekend": sum(1 for _, f in pool if f.get(key) is None)})
    return out


REASON_TEXT = {"run": "door de pool, geen sweep", "geen_herstel": "geen slot terug binnen 6 candles", "geen_top": "geen top om te breken",
               "geen_shift": "geen breuk op tijd", "geen_displacement": "breuk zonder kracht of gap", "terugtest_al_geweest": "terugtest al geweest",
               "premium": "limiet niet in premium/discount", "geen_doel": "geen doel voorbij de limiet",
               "niet_in_premium": "top niet in premium (long: bodem niet in discount)", "niet_lager_dan_vorige": "geen lagere top (long: hogere bodem)",
               "buiten_de_range": "buiten de range", "te_ver_van_de_koers": "te ver van de koers", "geen_vorige_swing": "geen vorige top om mee te vergelijken"}


def reasons(scenarios: list[dict]) -> list[dict]:
    """Waarom een poging géén plan werd, per instappunt en reden (audit 2026-11-03). A uit de mislukte pogingen, B, B0, R en K uit alt_log;
    'gevonden' is geen afwijzing en telt niet. Alleen meting, oudste scenario's zonder alt_log tellen voor B/B0/R/K niet mee."""
    counts: dict = {}
    for s in scenarios:
        for a in _htf(s.get("steps")).get("attempts") or []:
            counts.setdefault(("A", a.get("reden")), 0)
            counts[("A", a.get("reden"))] += 1
        for code, log in _htf(s.get("alt_log")).items():
            for x in log or []:
                if x.get("wat") != "gevonden":
                    counts[(code, x.get("wat"))] = counts.get((code, x.get("wat")), 0) + 1
    order = ("A", "B", "B0", "R", "K")
    return [{"code": c, "reden": r, "tekst": REASON_TEXT.get(r, r), "n": n}
            for (c, r), n in sorted(counts.items(), key=lambda kv: (order.index(kv[0][0]) if kv[0][0] in order else 9, -kv[1]))]


def entry_arms(entries: list[dict], cost_pct: float, names: Optional[dict] = None) -> list[dict]:
    """Per instappunt: hoeveel gevonden, gevuld en afgerond, de arm met dezelfde maten als H (§8) en de stand van de stopregel."""
    out = []
    for code, name in (names or ENTRY_NAMES).items():
        mine = [e for e in entries if e.get("code") == code]
        a = arm(entry_trades(entries, code, cost_pct))
        v = verdict(a)
        out.append({"code": code, "label": name, "gevonden": len(mine), "gevuld": sum(1 for e in mine if e.get("filled_at")), "arm": a,
                    "verdict": v, "verdict_text": VERDICT_TEXT[v]})
    return out


def gate_trades(scenarios: list[dict], cost_pct: float) -> list[dict]:
    """De entries die de BTC-poort tegenhield (entry_state 'btc_tegen'), stil gevolgd (cf_*): netto R zoals V1, zonder funding."""
    out = []
    for s in scenarios:
        if s.get("entry_state") != "btc_tegen" or s.get("cf_outcome") not in ("take_profit", "stop_loss") or s.get("cf_r") is None:
            continue
        stop_pct = abs(s["limit_price"] - s["stop_loss"]) / s["limit_price"] * 100
        out.append({"net": s["cf_r"] - (cost_pct / stop_pct if stop_pct else 0.0), "direction": s["direction"], "start": _dt(s["cf_filled_at"]),
                    "end": _dt(s["cf_at"])})
    return out


def gate(scenarios: list[dict], cost_pct: float) -> dict:
    """Wat de BTC-poort tegenhield en wat die entries stil deden. Een positief gemiddelde hier betekent dat de poort winst kost."""
    held = [s for s in scenarios if s.get("entry_state") == "btc_tegen"]
    trades = gate_trades(scenarios, cost_pct)
    return {"tegengehouden": len(held), "gevuld": sum(1 for s in held if s.get("cf_filled_at")), "arm": arm(trades)}


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


# Bevriezing (B-2026-11-03-09): de instapregels liggen drie weken vast. Alleen wat na het bevriezingsmoment (settings model_freeze_at, gezet
# bij de eerste start van de motor met deze code) en niet met terugwerkende kracht ontstond, telt in de hoofdcijfers. Terugwerkend: de app
# legde het meer dan RETRO_MIN minuten na het herkenbare moment vast. Dat gebeurt bij een update (VPS 2 november: scenario's van 30 en 31
# oktober opgeslagen om 19:35, FIL en UNI binnen vijf minuten gevuld en gestopt).
RETRO_MIN = 30


def _late(known, detected) -> bool:
    k, d = _dt(known), _dt(detected)
    return bool(k and d and (d - k).total_seconds() > RETRO_MIN * 60)


def split(scenarios: list[dict], v1: list[dict], signal_rows: list[dict], entries: list[dict], freeze_at: Optional[datetime]) -> tuple[dict, dict]:
    """(telt, apart): dezelfde vier lijsten, gesplitst. Zonder bevriezingsmoment telt alles (oude databases, tests)."""
    if freeze_at is None:
        return ({"scenarios": scenarios, "v1": v1, "signals": signal_rows, "entries": entries},
                {"scenarios": [], "v1": [], "signals": [], "entries": []})
    ok_sc = {s["id"] for s in scenarios if (_dt(s.get("detected_at")) or freeze_at) >= freeze_at
             and not _late(s.get("discovered_at"), s.get("detected_at"))}
    ok_sig = {s.get("signal_id") for s in scenarios if s["id"] in ok_sc and s.get("signal_id")}
    model_sig = {s.get("signal_id") for s in scenarios if s.get("signal_id")}
    keep = {
        "scenarios": [s for s in scenarios if s["id"] in ok_sc],
        "v1": [v for v in v1 if v.get("scenario_id") in ok_sc],
        # Een signaal van een andere soort (V2, V3) valt buiten de bevriezing en telt altijd.
        "signals": [r for r in signal_rows if r.get("id") not in model_sig or r.get("id") in ok_sig],
        "entries": [e for e in entries if (_dt(e.get("detected_at")) or freeze_at) >= freeze_at and not _late(e.get("known_at"), e.get("detected_at"))],
    }
    apart = {k: [x for x in v if x not in keep[k]] for k, v in
             {"scenarios": scenarios, "v1": v1, "signals": signal_rows, "entries": entries}.items()}
    return keep, apart


def counted_entries(entries: list[dict], freeze_at: Optional[datetime]) -> list[dict]:
    """De instappunten die meetellen voor de stopregel per punt: dezelfde scheiding als de hoofdcijfers, zonder de arm tegen de dagtrend."""
    return split([], [], [], [e for e in entries if not str(e.get("scenario_range_id") or "").startswith("tegen:")], freeze_at)[0]["entries"]


COUNTER_PREFIX = "tegen:"           # model.COUNTER_PREFIX
COUNTER_NAMES = {"A": "A na sweep", **ENTRY_NAMES}


def _is_counter(range_id) -> bool:
    return bool(range_id) and str(range_id).startswith(COUNTER_PREFIX)


def report(scenarios: list[dict], v1: list[dict], signal_rows: list[dict], cost_pct: float, ceo: bool = False,
           entries: Optional[list[dict]] = None, freeze_at: Optional[datetime] = None, strict: Optional[list[dict]] = None,
           placebo_rs: Optional[dict] = None) -> dict:
    """Alles voor Bewijs en de nachtexport, alleen over wat na de bevriezing ontstond; de rest staat samengevat onder `apart`. De
    vergelijkingen (V1, V2, V3) alleen met ceo=True. De stille arm tegen de dagtrend (B-2026-11-03-11) telt nergens mee in de hoofdcijfers en
    staat apart onder `tegen`, met dezelfde scheiding rond de bevriezing."""
    entries = entries or []
    c_sc = [x for x in scenarios if _is_counter(x.get("range_id"))]
    c_v1 = [x for x in v1 if _is_counter(x.get("scenario_range_id"))]
    c_en = [x for x in entries if _is_counter(x.get("scenario_range_id"))]
    scenarios = [x for x in scenarios if not _is_counter(x.get("range_id"))]
    v1 = [x for x in v1 if not _is_counter(x.get("scenario_range_id"))]
    entries = [x for x in entries if not _is_counter(x.get("scenario_range_id"))]
    ck, _ = split(c_sc, c_v1, [], c_en, freeze_at)
    tegen = {"scenarios": len(ck["scenarios"]), "punten": entry_arms(ck["entries"], cost_pct, COUNTER_NAMES),
             "v1": arm(v1_trades(ck["v1"], cost_pct))}
    keep, rest = split(scenarios, v1, signal_rows, entries, freeze_at)
    out = _report(keep["scenarios"], keep["v1"], keep["signals"], cost_pct, ceo, keep["entries"])
    out["freeze_at"] = freeze_at
    rh = signal_trades(rest["signals"], "hespulse_model", cost_pct)
    rv = v1_trades(rest["v1"], cost_pct)
    re_ = [t for code in ENTRY_NAMES for t in entry_trades(rest["entries"], code, cost_pct)]
    out["tegen"] = tegen
    # De vier metingen tijdens de bevriezing (B-2026-11-03-12), op dezelfde getelde trades als de hoofdcijfers.
    out["strikt"] = strict_compare(strict or [], cost_pct)
    out["excursie"] = excursions(keep["scenarios"], keep["entries"], {r["id"]: r.get("auto_outcome") for r in keep["signals"] if r.get("id")})
    out["placebo"] = placebo(placebo_pairs(keep["scenarios"], keep["signals"], keep["entries"], placebo_rs or {}, cost_pct))
    out["apart"] = {"scenarios": len(rest["scenarios"]), "h": arm(rh), "v1": arm(rv), "punten": arm(re_),
                    "terugwerkend": sum(1 for s in scenarios if _late(s.get("discovered_at"), s.get("detected_at")))}
    return out


def _report(scenarios: list[dict], v1: list[dict], signal_rows: list[dict], cost_pct: float, ceo: bool = False,
            entries: Optional[list[dict]] = None) -> dict:
    h = signal_trades(signal_rows, "hespulse_model", cost_pct)
    costs = [t["cost_r"] for t in h if t["cost_r"] is not None]
    out = {"execution": execution(scenarios), "funnel": funnel(scenarios, {r["id"]: r.get("auto_outcome") for r in signal_rows if r.get("id")}),
           "h": arm(h), "cost_median_r": median(costs) if costs else None, "funding_unknown": sum(1 for t in h if t["funding_unknown"]),
           "level": LEVEL, "first_eval_ready": len(h) >= FIRST_EVAL_TRADES, "btc_poort": gate(scenarios, cost_pct),
           "instappunten": entry_arms(entries or [], cost_pct), "hogere_tf": htf_split(scenarios, signal_rows, entries or [], cost_pct),
           "redenen": reasons(scenarios),
           "decision_ready": len(h) >= DECISION_TRADES and arm(h)["weeks"] >= DECISION_WEEKS and n_eff(h) >= DECISION_NEFF}
    if ceo:
        v1t = v1_trades(v1, cost_pct)
        v2, v3 = signal_trades(signal_rows, "zone_sweep", cost_pct), signal_trades(signal_rows, "poc_radar", cost_pct)
        out["compare"] = [{"key": "V1", "label": "V1 vroege limiet op de pool", "arm": arm(v1t), "diff": diff(v1t, h), "note": "zonder funding"},
                          {"key": "V2", "label": "V2 Zone-sweep (referentie)", "arm": arm(v2), "diff": diff(v2, h), "note": ""},
                          {"key": "V3", "label": "V3 POC-radar (referentie)", "arm": arm(v3), "diff": diff(v3, h), "note": ""}]
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------
# De vier metingen tijdens de bevriezing (aanvulling preregistratie 2026-11-03 avond, B-2026-11-03-12). Alleen meting.

STRICT_CODES = ("A", "B", "B0", "R", "K")
DONE = ("take_profit", "stop_loss")


def _gross(outcome: Optional[str], limit: float, stop: float, take: Optional[float]) -> Optional[float]:
    """Bruto R van een afgeronde trade uit zijn niveaus: stop −1, doel de afstand tot het doel in R. Gewone en strenge arm delen de niveaus."""
    if outcome == "stop_loss":
        return -1.0
    if outcome == "take_profit" and take is not None and limit != stop:
        return abs(take - limit) / abs(limit - stop)
    return None


def _cost_r(limit: float, stop: float, cost_pct: float) -> float:
    stop_pct = abs(limit - stop) / limit * 100 if limit else 0.0
    return cost_pct / stop_pct if stop_pct else 0.0


def strict_compare(rows: list[dict], cost_pct: float) -> dict:
    """M1: per instappunt de gewone arm (aanraken vult) naast de strenge (strikt door de limiet), op precies dezelfde plannen. rows: uit
    repo.list_model_strict_compare. Een plan dat pas ruim na het herkenbare moment werd vastgelegd (_late) telt niet, net als in de
    hoofdcijfers. De arm tegen de dagtrend staat apart."""
    out = {"main": [], "tegen": []}
    for counter, key in ((0, "main"), (1, "tegen")):
        for code in STRICT_CODES:
            rs = [r for r in rows if r["code"] == code and int(r.get("counter") or 0) == counter and not _late(r.get("known"), r.get("detected"))]
            if not rs:
                continue
            net_n, net_s = [], []
            for r in rs:
                c = _cost_r(r["limit_price"], r["stop_loss"], cost_pct)
                g = _gross(r.get("n_outcome"), r["limit_price"], r["stop_loss"], r["take_profit"])
                if g is not None:
                    net_n.append(g - c)
                g = _gross(r.get("outcome"), r["limit_price"], r["stop_loss"], r["take_profit"])
                if g is not None:
                    net_s.append(g - c)
            out[key].append({"code": code, "name": COUNTER_NAMES.get(code, code), "plans": len(rs),
                             "fill_n": sum(1 for r in rs if r.get("n_filled_at")), "fill_s": sum(1 for r in rs if r.get("filled_at")),
                             "done_n": len(net_n), "done_s": len(net_s), "mean_n": _mean(net_n), "mean_s": _mean(net_s)})
    return out


def excursions(scenarios: list[dict], entries: list[dict], outcomes: dict) -> list[dict]:
    """M2: per instappunt de MAE bij winnaars (mediaan en 90e percentiel), het aandeel verliezers dat eerst +1R haalde, en de gemiddelde
    stopslip (ondergrens). outcomes: {signal_id: auto_outcome} voor A. Zonder meting (leeg) telt een trade als onbekend."""
    rows = [{"code": "A", "outcome": outcomes.get(s.get("signal_id")), "mae_r": s.get("mae_r"), "mfe_r": s.get("mfe_r"), "slip_r": s.get("slip_r")}
            for s in scenarios if s.get("signal_id")]
    rows += [{"code": e["code"], "outcome": e.get("outcome"), "mae_r": e.get("mae_r"), "mfe_r": e.get("mfe_r"), "slip_r": e.get("slip_r")}
             for e in entries]
    out = []
    for code in STRICT_CODES:
        done = [r for r in rows if r["code"] == code and r["outcome"] in DONE]
        if not done:
            continue
        known = [r for r in done if r["mae_r"] is not None]
        wins = [r["mae_r"] for r in known if r["outcome"] == "take_profit"]
        losses = [r for r in known if r["outcome"] == "stop_loss"]
        slips = [r["slip_r"] for r in done if r["outcome"] == "stop_loss" and r["slip_r"] is not None]
        out.append({"code": code, "name": COUNTER_NAMES.get(code, code), "n": len(done), "unknown": len(done) - len(known),
                    "mae_win_med": median(wins) if wins else None, "mae_win_p90": _q(wins, 0.9),
                    "loss_1r": sum(1 for r in losses if (r["mfe_r"] or 0) >= 1.0) / len(losses) if losses else None, "losses": len(losses),
                    "slip_mean": _mean(slips), "slip_n": len(slips)})
    return out


def placebo(pairs: list[dict]) -> dict:
    """M3: per afgeronde trade zijn netto R min het gemiddelde netto R van zijn willekeurige instappen (zelfde coin, richting en geometrie).
    pairs: {net, end, cost_r, rs (bruto R van de placebo's)}. Het interval per ISO-week op LEVEL. Boven 0: de timing voegt iets toe."""
    diffs, weeks, models, placebos = [], [], [], []
    for p in pairs:
        if not p.get("rs"):
            continue
        pm = _mean([g - p["cost_r"] for g in p["rs"]])
        diffs.append(p["net"] - pm)
        weeks.append(stats.week_key(p["end"]))
        models.append(p["net"])
        placebos.append(pm)
    out = {"n": len(diffs), "mean_model": _mean(models), "mean_placebo": _mean(placebos), "diff": _mean(diffs), "ci": None,
           "missing": sum(1 for p in pairs if not p.get("rs"))}
    if diffs:
        out["ci"] = stats.cluster_bootstrap_mean(diffs, weeks, level=LEVEL)
    return out


def placebo_pairs(scenarios: list[dict], signal_rows: list[dict], entries: list[dict], placebo_rs: dict, cost_pct: float) -> list[dict]:
    """De afgeronde trades (A als signaal, B, B0, R, K als instappunt) met hun placebo's; netto zoals de hoofdcijfers."""
    from app import track_record
    sig = {r["id"]: r for r in signal_rows if r.get("id")}
    out = []
    for s in scenarios:
        r = sig.get(s.get("signal_id"))
        if not r or r.get("auto_outcome") not in DONE or r.get("is_practice"):
            continue
        net, end = track_record.net_signal_r(r, cost_pct), _dt(r.get("auto_outcome_at"))
        if net is None or end is None:
            continue
        out.append({"net": net, "end": end, "cost_r": _cost_r(r["price"], r["stop_loss"], cost_pct), "rs": placebo_rs.get(("A", s["id"]))})
    for e in entries:
        if e.get("code") not in STRICT_CODES or e.get("outcome") not in DONE or e.get("r_gross") is None:
            continue
        c = _cost_r(e["limit_price"], e["stop_loss"], cost_pct)
        out.append({"net": e["r_gross"] - c, "end": _dt(e["outcome_at"]), "cost_r": c, "rs": placebo_rs.get(("E", e["id"]))})
    return [p for p in out if p["end"] is not None]


def r_text(x: Optional[float]) -> str:
    return "–" if x is None else f"{x:+.2f}".replace(".", ",").replace("-", "−") + " R"


def ci_text(ci: Optional[tuple[float, float]]) -> str:
    return "–" if not ci else f"{r_text(ci[0])} tot {r_text(ci[1])}"


def jsonable(rep: dict) -> dict:
    """Voor de nachtexport: tuples als lijsten, None blijft None."""
    return json.loads(json.dumps(rep, default=lambda o: list(o) if isinstance(o, tuple) else str(o)))
