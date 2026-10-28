"""Eerlijk, automatisch gemeten trackrecord per soort melding, in R na kosten: de rekenlaag voor /bewijs.
R is de winst als veelvoud van het risico: een take telt als afstand tot take gedeeld door afstand tot stop,
een stop als -1. Alleen signalen met een vaststaande uitkomst (take of stop) tellen mee in winrate en R; vervallen
en open signalen staan er apart bij, zodat niemand ze kan missen. Kosten komen per signaal in R af: de kosten per
rondreis gedeeld door de stopafstand in procenten (een strakke stop maakt de kosten zwaarder)."""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from app import market_context

RECENT_DAYS = 90
MIN_FOR_STATUS = 30
MIN_FOR_PROVEN = 100
WEEKS_SHOWN = 12

TYPE_LABELS = {
    "smc": "SMC liquidity sweep",
    "patroon": "Chart-patroon",
    "day_trading": "Day trading (4u)",
    "swing": "Swing",
    "samenval": "Samenval SMC en community (ongetest)",
    "script": "Markt-script (ongetest)",
    "structuur": "Structuur-breuk (ongetest)",
    "structuur_c": "Structuur oordeel C",
    "smc_waarschuwing": "SMC met waarschuwing",
    "trend": "Trend (ongetest)",
    "rejectie": "Rejectie op een niveau (ongetest)",
    "don55_trend": "Trend 4u met meelopende stop",
    "range_sweep": "Range sweep (ongetest)",
    "zone_radar": "Zone-radar (ongetest)",
    "zone_sweep": "Zone-sweep (ongetest)",
    "poc_radar": "POC-radar (ongetest)",
}
# Leesbare namen voor de labvarianten (sleutel: Variant.name.lower()); alleen de CEO ziet ze. Onbekend: de ruwe naam.
LAB_LABELS = {
    "don20": "Uitbraak 20 candles, 4u",
    "don20_trend": "Uitbraak 20 candles met trend, 4u",
    "don55": "Uitbraak 55 candles, 4u",
    "don55_trend": "Uitbraak 55 candles met trend, 4u",
    "pull21": "Terugval naar EMA21, 4u",
    "pull50": "Terugval naar EMA50, 4u",
    "sweep_dag_2r": "Sweep dagniveau, doel 2R, 1u",
    "sweep_dag_3r": "Sweep dagniveau, doel 3R, 1u",
    "sweep_week_2r": "Sweep weekniveau, doel 2R, 1u",
    "sweep_week_3r": "Sweep weekniveau, doel 3R, 1u",
    "sw_trend_1h": "Swing trend, 1u",
    "sw_pull_1h": "Swing terugval, 1u",
    "sw_don_1h": "Swing uitbraak, 1u",
    "sw_squeeze_1h": "Swing samentrekking, 1u",
    "kant_1_5m": "Kanteling enkel, 5m",
    "kant_2_5m": "Kanteling dubbel, 5m",
    "kant_1_15m": "Kanteling enkel, 15m",
    "kant_2_15m": "Kanteling dubbel, 15m",
    "kant_1_1h": "Kanteling enkel, 1u",
    "kant_2_1h": "Kanteling dubbel, 1u",
    "rz_30m": "Zone-retest 30m", "rz_1h": "Zone-retest 1u", "rz_2h": "Zone-retest 2u", "rz_4h": "Zone-retest 4u",
    "rz_1h_choch": "Zone-retest 1u, CHoCH 15m", "rz_2h_choch": "Zone-retest 2u, CHoCH 15m", "rz_2h_zonderhtf": "Zone-retest 2u zonder HTF",
    "rz_2h_split": "Zone-retest 2u, 40/60 verdeeld", "rs_30m": "Range sweep 30m", "rs_1h": "Range sweep 1u", "rs_2h": "Range sweep 2u",
    "rs_4h": "Range sweep 4u", "rs_1h_choch": "Range sweep 1u, CHoCH 15m", "rs_1h_zonderhtf": "Range sweep 1u zonder HTF",
    "rs_1h_oiflush": "Range sweep 1u met OI-daling", "range_sweep_stop": "Range sweep, stopkwaliteit",
    "zs_1h": "Zone-sweep 1u", "zs_2h": "Zone-sweep 2u", "zs_4h": "Zone-sweep 4u", "zs_1h_zonderhtf": "Zone-sweep 1u zonder HTF",
    "zs_2h_zonderhtf": "Zone-sweep 2u zonder HTF", "zs_4h_zonderhtf": "Zone-sweep 4u zonder HTF", "zs_2h_midden": "Zone-sweep 2u, midden van de zone",
    "zone_sweep_stop": "Zone-sweep, stopkwaliteit", "zone_sweep": "Zone-sweep, toets op een voordeel",
}
SOURCE_LABELS = {"scan": "Door HesPulse gevonden", "community": "Via de community"}
STATUS_LABELS = {
    "te_weinig": "Nog te weinig data",
    "positief": "Positief, nog niet bewezen",
    "voordeel": "Voordeel gemeten",
    "verlies": "Verlies gemeten",
}


def signal_r(row: dict) -> Optional[float]:
    """r_override is de echte R van een meelopende stop (trade_results); de vaste formule past daar niet op. Alleen bij een
    vaststaande uitkomst, zodat een override nooit een open of vervallen signaal meetelt."""
    ov = row.get("r_override")
    if ov is not None and row.get("auto_outcome") in ("take_profit", "stop_loss"):
        return float(ov)
    risk = abs((row["price"] or 0) - (row["stop_loss"] or 0))
    if row["auto_outcome"] == "take_profit" and risk > 0 and row["take_profit"] is not None:
        return abs(row["take_profit"] - row["price"]) / risk
    if row["auto_outcome"] == "stop_loss" and risk > 0:
        return -1.0
    return None


def _cost_r(row: dict, round_trip_cost_pct: float) -> float:
    stop_pct = abs(row["price"] - row["stop_loss"]) / row["price"] * 100
    return round_trip_cost_pct / stop_pct if stop_pct else 0.0


def net_signal_r(row: dict, round_trip_cost_pct: float) -> Optional[float]:
    """R na kosten van een signaal, zoals Bewijs het rekent; None zolang de uitkomst niet vaststaat (take of stop)."""
    gross = signal_r(row)
    if gross is None or not row.get("price"):
        return None
    return gross - _cost_r(row, round_trip_cost_pct)


def _status(n_resolved: int, avg_net: Optional[float]) -> str:
    if n_resolved < MIN_FOR_STATUS or avg_net is None:
        return "te_weinig"
    if avg_net <= 0:
        return "verlies"
    return "voordeel" if n_resolved >= MIN_FOR_PROVEN else "positief"


def _week_key(moment: datetime) -> tuple[int, int]:
    iso = moment.isocalendar()
    return iso[0], iso[1]


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def day_summary(rows: list[dict], round_trip_cost_pct: float, since: datetime) -> dict:
    """Wat er sinds een moment gemeld en afgerond werd, in R na kosten: voor de dagafsluiting. Open en vervallen tellen niet mee in R."""
    recent = [r for r in rows if _parse(r["created_at"]) >= since]
    resolved = [(r, signal_r(r)) for r in recent]
    resolved = [(r, g) for r, g in resolved if g is not None]
    net = sum(g - _cost_r(r, round_trip_cost_pct) for r, g in resolved)
    return {"signals": len(recent), "resolved": len(resolved), "wins": sum(1 for _, g in resolved if g > 0), "net_r": net}


def week_summary(rows: list[dict], round_trip_cost_pct: float, now: Optional[datetime] = None, days: int = 7, tz=None) -> dict:
    """De laatste dagen in één blik, voor de weekafbeelding: aantallen, R na kosten per dag (oud naar nieuw), de beste en de slechtste afgeronde kans.
    Een dag is een Nederlandse kalenderdag en het venster begint op de nachtgrens van de eerste dag, zodat het totaal en de dagstaven
    precies dezelfde trades tellen en 'vandaag' tussen 00:00 en 02:00 niet nog gisteren is."""
    tz = tz or ZoneInfo("Europe/Amsterdam")
    now = now or datetime.now(timezone.utc)
    first_day = now.astimezone(tz).date() - timedelta(days=days - 1)
    since = datetime.combine(first_day, time.min, tzinfo=tz)
    recent = [r for r in rows if _parse(r["created_at"]) >= since]
    resolved = []
    for r in recent:
        g = signal_r(r)
        if g is not None:
            resolved.append((r, g - _cost_r(r, round_trip_cost_pct)))
    per_day: dict = {}
    for offset in range(days):
        per_day[first_day + timedelta(days=offset)] = 0.0
    for r, net in resolved:
        day = _parse(r["auto_outcome_at"] or r["created_at"]).astimezone(tz).date()
        if day in per_day:
            per_day[day] += net
    cumulative, running = [], 0.0
    for v in per_day.values():
        running += v
        cumulative.append(running)
    best = max(resolved, key=lambda x: x[1], default=None)
    worst = min(resolved, key=lambda x: x[1], default=None)
    pick = lambda item: None if item is None else {"id": item[0].get("id"), "coin": item[0].get("coin"), "direction": item[0].get("direction"), "net_r": item[1]}
    return {"signals": len(recent), "resolved": len(resolved), "wins": sum(1 for _, n in resolved if n > 0),
            "net_r": sum(n for _, n in resolved), "days": list(per_day.items()), "cumulative": cumulative,
            "best": pick(best), "worst": pick(worst) if worst is not best else None}


SCORE_CUT_PCT = 70.0


def _score_split(resolved: list[tuple[dict, float]], net: list[float]) -> Optional[dict]:
    """Gemiddeld resultaat na kosten voor kansen met een hoge tegenover een lage kenmerkenscore (app/chance_checks.py). Alleen als er
    afgeronde kansen mét score zijn: zo toont Bewijs of een hoge score ook echt vaker wint, in plaats van dat we het aannemen."""
    scored = [(r["pass_pct"], n) for (r, _), n in zip(resolved, net) if r.get("pass_pct") is not None]
    if not scored:
        return None
    high = [n for p, n in scored if p >= SCORE_CUT_PCT]
    low = [n for p, n in scored if p < SCORE_CUT_PCT]
    return {"cut": SCORE_CUT_PCT, "high_n": len(high), "high_avg": sum(high) / len(high) if high else None,
            "low_n": len(low), "low_avg": sum(low) / len(low) if low else None}


def _group_stats(items: list[tuple[dict, Optional[float]]]) -> dict:
    resolved = [n for _, n in items if n is not None]
    wins = sum(1 for n in resolved if n > 0)
    return {"n": len(resolved), "wins": wins, "open": len(items) - len(resolved),
            "winrate": wins / len(resolved) if resolved else None, "avg_net": sum(resolved) / len(resolved) if resolved else None}


def funding_split(rows: list[dict], round_trip_cost_pct: float) -> list[dict]:
    """Per kaartsoort: kaarten met extreme funding bij het ontstaan (market_context.is_extreme, vaste drempels) tegenover de rest, in n, winrate en
    R na kosten. Alleen soorten met een bewaarde stand (ctx_funding). Een afgeronde kaart zonder stand telt apart als 'unmeasured', zodat niemand
    denkt dat de tabel alles omvat. Net als _score_split: dit toont of het samengaat, het is geen voorspeller."""
    groups: dict[str, dict] = {}
    for r in rows:
        gross = signal_r(r)
        net = None if gross is None or not r.get("price") else gross - _cost_r(r, round_trip_cost_pct)
        g = groups.setdefault(r["trade_type"], {"extreme": [], "rest": [], "unmeasured": 0, "measured": False})
        if r.get("ctx_funding") is None:
            g["unmeasured"] += net is not None
            continue
        g["measured"] = True
        g["extreme" if market_context.is_extreme(r["ctx_funding"]) else "rest"].append((r, net))
    order = list(TYPE_LABELS)
    return [{"trade_type": t, "label": TYPE_LABELS.get(t, t), "extreme": _group_stats(g["extreme"]), "rest": _group_stats(g["rest"]),
             "unmeasured": g["unmeasured"], "high": market_context.FUNDING_HIGH_PCT, "low": market_context.FUNDING_LOW_PCT}
            for t, g in sorted(groups.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order)) if g["measured"]]


def summarize(rows: list[dict], round_trip_cost_pct: float, now: Optional[datetime] = None) -> list[dict]:
    """Eén entry per (bron, soort), gesorteerd op aantal afgeronde trades. Alles samen staat als laatste entry
    met bron 'alles'. 'recent' zijn de laatste RECENT_DAYS dagen, de status gaat uit van alles sinds het begin."""
    now = now or datetime.now(timezone.utc)
    recent_cut = now - timedelta(days=RECENT_DAYS)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        source = "community" if r["message_id"] is not None else "scan"
        groups[(source, r["trade_type"])].append(r)
        groups[("alles", "alles")].append(r)
        if r.get("samenval"):
            groups[("scan", "samenval")].append(r)    # ook los zichtbaar, zonder het totaal dubbel te tellen

    out = []
    for (source, trade_type), items in groups.items():
        resolved = [(r, signal_r(r)) for r in items]
        resolved = [(r, g) for r, g in resolved if g is not None]
        net = [g - _cost_r(r, round_trip_cost_pct) for r, g in resolved]
        gross = [g for _, g in resolved]
        wins = sum(1 for g in gross if g > 0)
        recent = [(r, n) for (r, _), n in zip(resolved, net) if _parse(r["created_at"]) >= recent_cut]
        weekly: dict[tuple, float] = defaultdict(float)
        for (r, _), n in zip(resolved, net):
            weekly[_week_key(_parse(r["auto_outcome_at"] or r["created_at"]))] += n
        weeks = []
        cursor = now
        for _ in range(WEEKS_SHOWN):
            weeks.append(_week_key(cursor))
            cursor -= timedelta(days=7)
        weeks.reverse()
        cumulative, running = [], 0.0
        before = sum(v for k, v in weekly.items() if k < weeks[0])
        running = before
        for k in weeks:
            running += weekly.get(k, 0.0)
            cumulative.append(running)
        n_resolved = len(resolved)
        avg_net = sum(net) / n_resolved if n_resolved else None
        score_split = _score_split(resolved, net)
        out.append({
            "source": source, "trade_type": trade_type,
            "label": "Alle meldingen samen" if source == "alles" else f"{TYPE_LABELS.get(trade_type, trade_type)}",
            "source_label": "" if source == "alles" else SOURCE_LABELS[source],
            "total": len(items), "resolved": n_resolved, "wins": wins, "losses": n_resolved - wins,
            "open_or_expired": len(items) - n_resolved,
            "winrate": wins / n_resolved if n_resolved else None,
            "avg_gross": sum(gross) / n_resolved if n_resolved else None,
            "avg_net": avg_net, "net_total": sum(net) if n_resolved else None,
            "recent_resolved": len(recent), "recent_avg_net": sum(n for _, n in recent) / len(recent) if recent else None,
            "status": _status(n_resolved, avg_net), "cumulative": cumulative, "cost_pct": round_trip_cost_pct,
            "score_split": score_split,
        })
    out.sort(key=lambda e: (e["source"] == "alles", -e["resolved"]))
    return out


RULE_STATUS_STATES = ("In proef", "Bewezen", "Negatief")
RULE_MIN_LIVE_PROVEN = 50
RULE_WATCH_LAST = 100


def rule_status(lab: Optional[dict], live_r_net: list[float], has_engine: bool = True, stop_lab: Optional[dict] = None) -> dict:
    """Status van één regel, elke keer opnieuw uit de data (niets opgeslagen, dus een Bewezen regel valt vanzelf terug). live_r_net: netto R
    van de afgeronde live trades, oudste eerst. Volgorde: Negatief, Bewezen, anders In proef.
    stop_lab: de labrij van de stopkwaliteit voor een proef die daarom draait (de range sweep). Is die geslaagd, dan maakt een mislukte strenge
    toets (`lab`, het voordeel) de regel niet Negatief: de proef bestaat juist om de stopkwaliteit live te meten. Bewezen vraagt nog steeds
    de geslaagde toets op een voordeel; Negatief komt dan alleen van een mislukte stopkwaliteit of een negatieve live reeks."""
    from app import structure_review      # structure_review importeert dit module al: bovenaan importeren geeft een kringverwijzing
    n = len(live_r_net)
    last100 = live_r_net[-RULE_WATCH_LAST:]
    avg_last100 = sum(last100) / RULE_WATCH_LAST if n >= RULE_WATCH_LAST else None
    out = lambda status, reason: {"status": status, "reason": reason, "n_live": n, "avg_last100": avg_last100}
    lab_passes = bool(lab and lab.get("lab_passes"))
    if not has_engine:
        # Een labvariant zonder live motor kan geen live trades krijgen: "In proef, nog 50 trades" zou iets beloven dat nooit komt.
        return out("Geen motor", f"{'Slaagde' if lab_passes else 'Slaagde niet'} in de test op historische data; er draait geen live motor voor deze regel.")
    last30 = live_r_net[-MIN_FOR_STATUS:]
    if n >= MIN_FOR_STATUS and sum(last30) / MIN_FOR_STATUS < 0:
        return out("Negatief", f"De laatste {MIN_FOR_STATUS} afgeronde trades samen onder nul na kosten.")
    stop_passes = bool(stop_lab and stop_lab.get("lab_passes"))
    if stop_lab is not None:
        if not stop_passes:
            return out("Negatief", "Slaagde niet in de test op stopkwaliteit.")
    elif lab is not None and not lab_passes:
        return out("Negatief", "Slaagde niet in de test op historische data.")
    if lab_passes and n >= RULE_MIN_LIVE_PROVEN and sum(live_r_net) / n >= 0:
        if n < RULE_WATCH_LAST or structure_review.bootstrap_mean(last100)[1] >= 0:
            return out("Bewezen", f"Slaagde in de test en houdt stand over {n} afgeronde trades.")
        return out("In proef", "De laatste 100 trades liggen duidelijk onder nul, de regel is niet langer bewezen.")
    if stop_passes and not lab_passes:
        return out("In proef", f"Stopkwaliteit geslaagd in het lab; de strenge toets op een voordeel slaagde niet, dus niets is bewezen. {n} afgeronde trades.")
    if not lab_passes:
        return out("In proef", f"Nog geen geslaagde test; {n} afgeronde trades.")
    return out("In proef", f"Geslaagde test; nog {max(0, RULE_MIN_LIVE_PROVEN - n)} afgeronde trades nodig voor bewezen.")


def rule_label(rule: str) -> str:
    return TYPE_LABELS.get(rule) or LAB_LABELS.get(rule, rule)


def fmt_r(value: float) -> str:
    """Netto R met teken en decimale komma, bijvoorbeeld +0,09R."""
    return f"{value:+.2f}".replace(".", ",") + "R"


def lab_line(lab: Optional[dict]) -> str:
    """Laatste labuitslag in één regel; wat ontbreekt blijft weg."""
    if not lab:
        return ""
    summary = lab.get("summary") or {}
    text = "Test op historische data: " + ("geslaagd" if lab.get("lab_passes") else "niet geslaagd")
    if summary.get("avg") is not None:
        text += f", gemiddeld {fmt_r(summary['avg'])} netto per trade"
        if summary.get("n") is not None:
            text += f" over {summary['n']} trades"
    elif summary.get("n") is not None:
        text += f", {summary['n']} trades"
    return text


def split_rule_types(types, engine_types) -> tuple[list[str], list[str]]:
    """Regels met een live motor apart van de zuivere labregels."""
    types = sorted(set(types))
    return [t for t in types if t in engine_types], [t for t in types if t not in engine_types]


def other_rule_rows(labs: dict, types) -> list[dict]:
    """Rijen voor 'Andere geteste regels': geslaagd eerst, dan gemiddelde netto R aflopend."""
    rows = []
    for t in types:
        lab = labs.get(t) or {}
        summary = lab.get("summary") or {}
        avg = summary.get("avg")
        rows.append({"rule": t, "label": rule_label(t), "passes": bool(lab.get("lab_passes")), "avg": avg,
                     "avg_text": fmt_r(avg) if avg is not None else "-", "n": summary.get("n")})
    rows.sort(key=lambda r: (not r["passes"], -(r["avg"] if r["avg"] is not None else float("-inf")), r["label"]))
    return rows


PROOF_STATES = {"In proef": "proef", "Bewezen": "bewezen", "Negatief": "negatief", "Geen motor": "proef"}


def rule_proof(lab: Optional[dict], live_r_net: list[float], stop_lab: Optional[dict] = None) -> dict:
    """Bewijsregel onder een kans van een regel met een labtoets, in dezelfde vorm als trust.status maar met de status van rule_status: Bewezen
    vraagt dan ook de labtoets en de bewaking over de laatste 100. Zonder "doel": een meelopende stop heeft er geen, de uitkomst is R."""
    st = rule_status(lab, live_r_net, stop_lab=stop_lab)
    n = len(live_r_net)
    total = sum(live_r_net)
    text = (f"{n} afgeronde {'trade' if n == 1 else 'trades'}, netto {total:+.1f}R, gemiddeld {total / n:+.2f}R per trade. " if n else "Nog geen afgeronde trades. ")
    return {"state": PROOF_STATES[st["status"]], "label": st["status"], "text": text + st["reason"], "n": n, "target": RULE_MIN_LIVE_PROVEN,
            "progress": min(1.0, n / RULE_MIN_LIVE_PROVEN), "wins": sum(1 for r in live_r_net if r > 0), "avg_net": total / n if n else None}


def visible_rule_types(types, ceo: bool, ceo_only=()) -> list[str]:
    """Welke regelstatussen een kijker ziet. De CEO ziet alles; anderen alleen soorten met een openbaar label in TYPE_LABELS die niet CEO-only zijn:
    een labvariant zonder label (don20, sw_trend_1h) is een methodenaam en blijft voor leerlingen weg."""
    return sorted(t for t in set(types) if ceo or (t in TYPE_LABELS and t not in ceo_only))


def live_net_r(rows: list[dict], trade_type: str, round_trip_cost_pct: float) -> list[float]:
    """Netto R van de afgeronde (take of stop) live trades van één soort, oudste afronding eerst."""
    done = [(r, signal_r(r)) for r in rows if r["trade_type"] == trade_type]
    done = sorted(((r, g) for r, g in done if g is not None), key=lambda x: x[0]["auto_outcome_at"] or x[0]["created_at"])
    return [g - _cost_r(r, round_trip_cost_pct) for r, g in done]


def equity_curves(rows: list[dict], round_trip_cost_pct: float) -> list[dict]:
    """Per soort de cumulatieve netto R na elke afgeronde trade (take of stop), oudste afronding eerst, met de terugval vanaf de hoogste
    stand tot dan (start is 0, dus een eerste verlies telt als terugval). Open en vervallen tellen niet mee maar staan als aantal ernaast."""
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["trade_type"]].append(r)
    out = []
    for trade_type, items in by_type.items():
        net = live_net_r(items, trade_type, round_trip_cost_pct)
        if not net:
            continue
        cumulative, drawdown, running, peak = [], [], 0.0, 0.0
        for n in net:
            running += n
            peak = max(peak, running)
            cumulative.append(running)
            drawdown.append(running - peak)
        out.append({"trade_type": trade_type, "label": TYPE_LABELS.get(trade_type, trade_type), "n": len(net), "cumulative": cumulative,
                    "drawdown": drawdown, "max_drawdown": min(drawdown), "total": running, "excluded": len(items) - len(net),
                    "total_text": fmt_r(running), "dd_text": fmt_r(min(drawdown)),
                    "dd_line": "geen terugval" if min(drawdown) == 0 else f"grootste terugval {fmt_r(min(drawdown))}"})
    out.sort(key=lambda c: -c["n"])
    return out


def equity_svg(cumulative: list[float], drawdown: list[float], width: int = 320, height: int = 90) -> str:
    """Lijn van de cumulatieve R vanaf 0, met als schaduw het vlak tussen de hoogste stand tot dan en de lijn (de terugval)."""
    if not cumulative:
        return ""
    values = [0.0] + list(cumulative)
    peaks = [0.0] + [c - d for c, d in zip(cumulative, drawdown)]
    lo, hi = min(min(values), 0.0), max(max(peaks), 0.0)
    span = hi - lo or 1.0
    pad = 4
    step = (width - 2 * pad) / max(1, len(values) - 1)

    def pt(i: int, v: float) -> str:
        return f"{pad + i * step:.1f},{pad + (hi - v) / span * (height - 2 * pad):.1f}"

    line = " ".join(pt(i, v) for i, v in enumerate(values))
    shade = " ".join([pt(i, p) for i, p in enumerate(peaks)] + [pt(i, values[i]) for i in range(len(values) - 1, -1, -1)])
    zero = pad + hi / span * (height - 2 * pad)
    trend = "up" if values[-1] >= 0 else "down"
    return (f'<svg class="equity equity-{trend}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
            f'aria-label="Cumulatief resultaat in R per afgeronde trade, met terugval">'
            f'<polygon class="equity-dd" points="{shade}"/>'
            f'<line class="equity-zero" x1="{pad}" x2="{width - pad}" y1="{zero:.1f}" y2="{zero:.1f}"/>'
            f'<polyline class="equity-line" points="{line}"/></svg>')


HOUR_GRID_MIN_N = 5
WEEKDAYS_SHORT = ("ma", "di", "wo", "do", "vr", "za", "zo")


def _heat(avg: float) -> str:
    """Klasse van de afgeronde waarde die in het vak staat, zodat tekst en kleur nooit verschillen (+0,0 is neutraal, ook bij +0,04)."""
    avg = round(avg, 1)
    if avg >= 0.5:
        return "pos2"
    if avg > 0:
        return "pos1"
    if avg <= -0.5:
        return "neg2"
    return "neg1" if avg < 0 else "nul"


def hour_grid(rows: list[dict], round_trip_cost_pct: float, tz=None, min_n: int = HOUR_GRID_MIN_N) -> dict:
    """Gemiddelde netto R per weekdag en uur van de melding (Nederlandse tijd), alleen afgeronde trades (take of stop). Een vak met minder
    dan min_n trades krijgt geen kleur: een paar trades per uur zeggen niets, en een fel vak zou dat wel suggereren."""
    tz = tz or ZoneInfo("Europe/Amsterdam")
    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    for r in rows:
        net = net_signal_r(r, round_trip_cost_pct)
        if net is None:
            continue
        at = _parse(r["created_at"]).astimezone(tz)
        cells[(at.weekday(), at.hour)].append(net)
    out_rows = []
    for d, day in enumerate(WEEKDAYS_SHORT):
        row_cells = []
        for h in range(24):
            vals = cells.get((d, h), [])
            avg = sum(vals) / len(vals) if vals else None
            weak = len(vals) < min_n
            title = f"{day} {h:02d}:00, {len(vals)} {'trade' if len(vals) == 1 else 'trades'}" + (f", gemiddeld {fmt_r(avg)}" if avg is not None else "")
            row_cells.append({"hour": h, "n": len(vals), "avg": avg, "weak": weak,
                              "heat": "zwak" if weak or avg is None else _heat(avg),
                              "avg_short": ("0,0" if round(avg, 1) == 0 else f"{avg:+.1f}".replace(".", ",")) if avg is not None else "", "title": title})
        out_rows.append({"day": day, "cells": row_cells})
    return {"rows": out_rows, "min_n": min_n, "total": sum(len(v) for v in cells.values())}


def sparkline_svg(values: list[float], width: int = 300, height: int = 56) -> str:
    """Lijn van het cumulatieve resultaat in R over de laatste weken, met een nullijn. Lege of vlakke reeksen
    geven een vlakke lijn in plaats van een fout."""
    if not values:
        return ""
    lo, hi = min(min(values), 0.0), max(max(values), 0.0)
    span = hi - lo or 1.0
    pad = 4

    def y(v: float) -> float:
        return pad + (hi - v) / span * (height - 2 * pad)

    step = (width - 2 * pad) / max(1, len(values) - 1)
    points = " ".join(f"{pad + i * step:.1f},{y(v):.1f}" for i, v in enumerate(values))
    trend = "up" if values[-1] >= values[0] else "down"
    return (f'<svg class="proof-spark proof-spark-{trend}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
            f'aria-label="Cumulatief resultaat in R per week">'
            f'<line class="proof-zero" x1="{pad}" x2="{width - pad}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>'
            f'<polyline points="{escape(points)}"/></svg>')


RANGE_R_LEVELS = (1, 2, 3, 4, 5, 6)
DRIFT_MIN_LIVE = 50
QUANTILES = (0.25, 0.5, 0.75, 0.9)


def _quantile(sorted_values: list[float], q: float) -> float:
    """Lineair geïnterpoleerd, zoals pandas' quantile in het lab, zodat lab en live dezelfde maat gebruiken."""
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def stop_quality_live(trades: list[dict], cost_pct: Optional[float] = None) -> dict:
    """Stopkwaliteit van de live range sweep-trades, zelfde maten als het lab (stopquality.summarize) behalve 'te krap': dat vraagt 48 uur na de stop
    en meet de motor niet. Een trade telt pas als de meting klaar is (stop geraakt of 7 dagen voorbij); lopende staan als aantal ernaast. Dat kleurt
    de eerste weken: wat snel op de stop liep is eerder klaar dan wat nog loopt."""
    done = [t for t in trades if t.get("closed_at") or t.get("stop_hit_at")]
    n = len(done)
    share = lambda key: sum(1 for t in done if t.get(key)) / n if n else None
    pcts = sorted(abs(t["entry"] - t["stop"]) / t["entry"] * 100 for t in done)
    quant = lambda key: ([_quantile(v, q) for q in QUANTILES] if (v := sorted(t[key] for t in done if t.get(key) is not None)) else None)
    median_pct = _quantile(pcts, 0.5) if n else None
    return {"n": n, "open": len(trades) - n, "stop_hit": share("stop_hit_at"), "reach": {k: share(f"reached_{k}r_at") for k in RANGE_R_LEVELS},
            "median_stop_pct": median_pct, "mae_q": quant("mae_r"), "mfe_q": quant("mfe_r"),
            "median_cost_r": cost_pct / median_pct if cost_pct and median_pct else None, "enough": n >= MIN_FOR_STATUS, "tight_known": False}


def _p(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def _r2(x) -> str:
    return f"{x:.2f}".replace(".", ",") + "R"


def _q_text(q: Optional[list]) -> str:
    """Mediaan en 90e percentiel; de rest van de kwantielen staat in het lab-rapport."""
    return "-" if not q else f"{_r2(q[1])} en {_r2(q[3])}"


def stop_lab_view(row: Optional[dict]) -> Optional[dict]:
    """De labrij 'range_sweep_stop' zoals strategy_lab --opslaan hem bewaart ({variant, stop_name, quality, summary, doelkans}) in de vorm die
    stop_quality_rows en drift_warning lezen: {"summary": <stopquality.summarize>}. Een rij zonder meting (geen toets slaagde) geeft een lege samenvatting."""
    if row is None:
        return None
    return {**row, "summary": (row.get("summary") or {}).get("summary") or {}}


def stop_quality_rows(lab: Optional[dict], live: dict) -> list[dict]:
    """Rijen voor de tabel op Bewijs: lab naast live, zelfde maat per rij. Zonder live trades staat er een streepje, nooit een nul."""
    s = (lab or {}).get("summary") or {}
    reach = s.get("reach") or {}
    lab_reach = lambda k: (reach.get(str(k)) or reach.get(k) or {}).get("p")
    has_live = bool(live["n"])
    rows = [("Stop geraakt", _p((s.get("stop_hit") or {}).get("p")), _p(live["stop_hit"]) if has_live else "-")]
    rows += [(f"+{k}R vóór de stop", _p(lab_reach(k)), _p(live["reach"][k]) if has_live else "-") for k in RANGE_R_LEVELS]
    rows += [
        ("Stopafstand (mediaan)", f"{s['median_stop_pct']:.2f}%".replace(".", ",") if s.get("median_stop_pct") else "-",
         f"{live['median_stop_pct']:.2f}%".replace(".", ",") if live.get("median_stop_pct") else "-"),
        ("Tegenbeweging, MAE (mediaan en 90%)", _q_text(s.get("mae_q")), _q_text(live.get("mae_q"))),
        ("Meebeweging, MFE (mediaan en 90%)", _q_text(s.get("mfe_q")), _q_text(live.get("mfe_q"))),
        ("Kosten in R (mediaan)", _r2(s["median_cost_r"]) if s.get("median_cost_r") else "-", _r2(live["median_cost_r"]) if live.get("median_cost_r") else "-"),
        ("Te krappe stops", _p(s.get("tight_rate")) if s.get("tight_rate") is not None else "-", "niet gemeten"),
    ]
    return [{"label": a, "lab_text": b, "live_text": c} for a, b, c in rows]


def drift_warning(lab: Optional[dict], live: dict) -> Optional[str]:
    """Stopcriterium S5: na DRIFT_MIN_LIVE afgeronde trades moet de live kans op +1R vóór de stop binnen het 95%-interval van het lab liggen."""
    reach = ((lab or {}).get("summary") or {}).get("reach") or {}
    one = reach.get("1") or reach.get(1)
    if not one or live.get("n", 0) < DRIFT_MIN_LIVE or live["reach"].get(1) is None:
        return None
    lo, hi = one["ci"]
    if lo <= live["reach"][1] <= hi:
        return None
    return f"Live wijkt af van het lab: +1R vóór de stop {live['reach'][1] * 100:.0f}% tegen {lo * 100:.0f} tot {hi * 100:.0f}% in het lab."


def mark_r(trade: dict, price: Optional[float]) -> Optional[float]:
    """R van een lopende trade als hij nu op deze koers zou sluiten. Een momentopname, geen uitkomst: ze telt nergens mee in winrate of gemiddelde."""
    risk = abs(trade["entry"] - trade["stop"])
    if not price or not risk:
        return None
    return ((trade["entry"] - price) if trade["direction"] == "short" else (price - trade["entry"])) / risk


def reference_live(trades: list[dict], net_r: list[float], prices: dict) -> dict:
    """R bij de referentie-uitgang (meelopende stop 3 ATR op 1u): afgeronde trades als netto gemiddelde, de lopende (nog geen referentie-uitgang)
    als aantal met hun stand op de koers van nu ernaast. `prices` is {coin: koers}. De gemiddelde is geen verwachting voor jouw eigen trade."""
    running = [t for t in trades if t.get("ref_r") is None]
    marks = [m for t in running if (m := mark_r(t, prices.get(t["coin"]))) is not None]
    return {"n": len(net_r), "avg_net": sum(net_r) / len(net_r) if net_r else None, "open": len(running), "marks": marks}


def range_lab_verdict(stop_lab: Optional[dict], edge_lab: Optional[dict], tests_stop: int, tests_register: int, t_min: float) -> dict:
    """Wat het lab over de range sweep zei, in woorden die bij elkaar horen: de stopkwaliteit (de kop van de proef) en ernaast de strenge toets op een
    voordeel. Geen labrij is 'nog niet getoetst', nooit een stil 'niet geslaagd'. De aantallen komen van de aanroeper (stopquality.KILL_TESTS,
    het register uit de pre-registratie, rangesweep_lab.EDGE_T_MIN), zodat er hier geen tweede kopie van staat."""
    t_text = f"{t_min:.1f}".replace(".", ",")
    stop = "nog niet getoetst" if stop_lab is None else ("geslaagd" if stop_lab.get("lab_passes") else "niet geslaagd")
    edge = "nog niet getoetst" if edge_lab is None else ("geslaagd" if edge_lab.get("lab_passes") else "niet geslaagd")
    e = (edge_lab or {}).get("summary") or {}
    detail = []
    if e.get("n") is not None:
        detail.append(f"{e['n']} trades")
    if e.get("avg") is not None:
        detail.append(f"gemiddeld {fmt_r(e['avg'])} netto per trade")
    if e.get("t_week") is not None:
        detail.append(f"t {e['t_week']:.1f}".replace(".", ",") + f" per week, horde {t_text}")
    return {"stop": stop, "edge": edge, "edge_detail": ", ".join(detail), "edge_reason": e.get("reason") or "",
            "tests_text": f"{tests_stop} toetsen op stopkwaliteit, {tests_register} varianten in het register waarop de horde van t {t_text} rekent"}
