"""Schaduwvarianten: één vooraf vastgelegde parameterwijziging per focus-soort die naast de live motor meedraait op dezelfde coins en momenten,
zonder melding, journaal of signals-rij, en die volgens een vaste regel promoveert of afvalt. De route om een motorregel te verbeteren zonder op data
af te stellen: de variant ligt vast vóór de meting (register met reden), beide armen worden op dezelfde manier gemeten, netto na kosten.

Aansluitbaar (PARAMS): bestaande constanten die de planfunctie van de motor als argument accepteert, met de constante als standaard. De
beslislogica verandert niet; alleen de waarde die erin gaat. Een gepromoveerde waarde staat in engine_overrides en de motor leest hem bij de start
van zijn cyclus (live_params).

De promotieregel (verdict) ligt vast:
  - wachten tot minstens MIN_TRADES afgeronde (doel of stop) variant-trades én MIN_TRADES hoofd-trades sinds de variant er is;
  - promoveren als de netto gemiddelde R van de variant hoger is dan die van de hoofdversie in beide helften van de periode (gesplitst op tijd)
    én het 95%-interval van het verschil, herbemonsterd per week (app/replay/stats.cluster_bootstrap_diff), boven 0 ligt;
  - afvallen als het interval onder 0 ligt (duidelijk slechter, al na MIN_TRADES), of als er na MAX_TRADES per arm geen promotie is;
  - anders wachten.

De meting (step): een plan wacht tot de limiet geraakt wordt op een gesloten 5m-candle die na het plan opende; het doel eerst is 'gemist'; na
expires_at 'verlopen'. Na de vulling telt vanaf de volgende candle: stop eerst (ook stop en doel in één candle), anders doel; na MAX_OPEN 'te_lang_open'.
Een plan zonder doel ('zonder_doel') telt niet mee: de referentie-uitgang van de motoren zonder doel is geen deel van de schaduw. Kosten zoals
track_record._cost_r zonder funding (die meet de schaduw niet), voor beide armen gelijk. Structuur volgt in de schaduw een vaste limiet op het
niveau bij het plan; ook dat geldt voor beide armen."""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from app import config, end_reason, repo
from app.replay import stats

logger = logging.getLogger("shadow")
TRADE_TYPES = ("structuur", "zone_radar", "zone_sweep", "poc_radar")
STATUSES = ("schaduw", "gepromoveerd", "afgevallen")
ARMS = ("hoofd", "variant")
DONE = ("take_profit", "stop_loss")
OPEN = ("waiting", "filled")
MIN_TRADES = 50
MAX_TRADES = 100
BAR = pd.Timedelta(minutes=5)
MAX_OPEN = timedelta(days=7)          # vooraf gekozen: een daytrade die na een week nog loopt, telt niet als uitkomst
NO_TTL = timedelta(days=3)            # voor motoren zonder eigen vervaltermijn (zone-radar, Structuur buiten zijn retest-venster): drie dagen, als de POC-radar
PARAM_TEXT = {"stop_atr": ("stop", "ATR"), "max_distance_pct": ("maximale afstand", "%"), "stop_buffer_atr": ("stopbuffer", "ATR")}
PARAMS = {"zone_radar": ("stop_atr", "max_distance_pct"), "zone_sweep": ("stop_buffer_atr",), "poc_radar": ("stop_atr",), "structuur": ("stop_atr",)}


def defaults(trade_type: str) -> dict:
    """De huidige constanten van de motor, gelezen op het moment zelf (geen kopie die kan afwijken)."""
    if trade_type == "zone_radar":
        from app import zone_radar as zr
        return {"stop_atr": zr.STOP_ATR, "max_distance_pct": zr.MAX_DISTANCE_PCT}
    if trade_type == "zone_sweep":
        from app import zone_sweep as zsw
        from app.replay import zonesweep as zs
        return {"stop_buffer_atr": zs.BUFFERS[zsw.STOP_NAME]}
    if trade_type == "poc_radar":
        from app import poc_radar as pr
        return {"stop_atr": pr.STOP_ATR}
    if trade_type == "structuur":
        from app.replay import breakretest as br
        return {"stop_atr": br.STOP_ATR}
    raise ValueError(f"onbekende soort {trade_type}")


# Het register in code: de wekelijkse verbetersessie (docs/verbeterlus.md) zet hier een variant bij, vooraf vastgelegd met reden. De nacht
# (scripts/schaduw.py --auto) legt elke nieuwe variant vast zodra zijn soort geen actieve schaduw heeft; een besloten variant komt nooit terug.
# Vorm: {"id", "trade_type", "description", "reason", "params"}.
SEEDS: tuple = (
    {"id": "structuur-stop-0.5", "trade_type": "structuur", "description": "Stop een halve ATR achter de terugkeer in plaats van een kwart.",
     "reason": "Nachtexport 2026-11-02, 30 dagen: 43 van 81 Structuur-stops haalden binnen 24 uur toch het doel; de stop lijkt binnen de ruis te staan.",
     "params": {"stop_atr": 0.5}},
    {"id": "zone-radar-stop-0.5", "trade_type": "zone_radar", "description": "Stop een halve ATR voorbij de buitenrand in plaats van een kwart.",
     "reason": "Nachtexport 2026-11-02, 30 dagen: zone-radar netto -0,52R per trade over 111 trades, en 22 van 82 stops haalden binnen 24 uur toch het doel.",
     "params": {"stop_atr": 0.5}},
)


def validate(trade_type: str, params: dict) -> None:
    if trade_type not in PARAMS:
        raise ValueError(f"{trade_type}: geen schaduw mogelijk, alleen {', '.join(TRADE_TYPES)}")
    if not params:
        raise ValueError("een variant wijzigt minstens één parameter")
    for name, value in params.items():
        if name not in PARAMS[trade_type]:
            raise ValueError(f"{trade_type}: parameter {name} is niet aansluitbaar (wel: {', '.join(PARAMS[trade_type])})")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not value > 0:
            raise ValueError(f"{name}: een positief getal, kreeg {value!r}")


def register(variant_id: str, trade_type: str, description: str, reason: str, params: dict, at: datetime) -> None:
    """Legt een variant vooraf vast. Hoogstens één actieve schaduw per soort; elke variant heeft een reden (het lek dat hij moet dichten)."""
    validate(trade_type, params)
    if not variant_id.strip() or not description.strip() or not reason.strip():
        raise ValueError("id, beschrijving en reden zijn verplicht")
    if repo.active_shadow(trade_type):
        raise ValueError(f"{trade_type} heeft al een actieve schaduw; hoogstens één per soort")
    if repo.get_shadow_variant(variant_id):
        raise ValueError(f"variant {variant_id} bestaat al")
    repo.insert_shadow_variant(variant_id, trade_type, description, reason, json.dumps(params), at.isoformat())


def seed(at: datetime) -> list[str]:
    """Legt de varianten uit SEEDS vast die er nog niet zijn en waarvan de soort vrij is, in de volgorde van SEEDS. Geeft de nieuwe ids."""
    added = []
    for s in SEEDS:
        if repo.get_shadow_variant(s["id"]) or repo.active_shadow(s["trade_type"]):
            continue
        try:
            register(s["id"], s["trade_type"], s["description"], s["reason"], s["params"], at)
        except ValueError:
            logger.exception("Seed %s is ongeldig en niet vastgelegd", s.get("id"))      # de verdicts van de andere schaduwen gaan door
            continue
        added.append(s["id"])
    return added


def live_params(trade_type: str) -> dict:
    """De constanten met de gepromoveerde waarden erover: wat de motor deze cyclus gebruikt."""
    base = defaults(trade_type)
    for name, value in repo.list_engine_overrides(trade_type).items():
        if name in base:
            base[name] = value
    return base


def variant_params(variant: dict) -> dict:
    return {**live_params(variant["trade_type"]), **json.loads(variant["params"])}


def label(trade_type: str) -> str:
    """De naam naar buiten: Structuur zonder A/B/C (CLAUDE.md, Structuur zonder oordeel)."""
    return end_reason.LABELS.get(trade_type, trade_type)


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t


def step(row: dict, candles: pd.DataFrame, now: datetime, cost_pct: Optional[float] = None) -> dict:
    """De nieuwe stand van één schaduwplan na deze candles (oudste eerst). Alleen gesloten candles na het plan en na checked_until."""
    cost_pct = config.TRACK_RECORD_COST_PCT if cost_pct is None else cost_pct
    now = _ts(now)
    short = row["direction"] == "short"
    limit, stop, take = row["limit_price"], row["stop_loss"], row.get("take_profit")
    state, filled_at = row["state"], row.get("filled_at")
    upd = {"state": state, "filled_at": filled_at, "outcome_at": None, "checked_until": row.get("checked_until"), "r_gross": None, "r_net": None}
    c = candles[(candles["timestamp"] >= _ts(row["created_at"])) & (candles["timestamp"] + BAR <= now)]
    if row.get("checked_until"):
        c = c[c["timestamp"] > _ts(row["checked_until"])]
    expires = _ts(row["expires_at"])
    for k in c.itertuples():
        ts = _ts(k.timestamp)
        upd["checked_until"] = ts.isoformat()
        if state == "waiting":
            if ts >= expires:
                state = "verlopen"
                break
            if (k.high >= limit) if short else (k.low <= limit):
                filled_at = ts.isoformat()
                state = "filled" if take is not None else "zonder_doel"
                if take is None:
                    break
                continue
            if take is not None and ((k.low <= take) if short else (k.high >= take)):
                state = "gemist"
                break
        elif state == "filled":
            if ts >= _ts(filled_at) + MAX_OPEN:
                state = "te_lang_open"
                break
            hit_stop = (k.high >= stop) if short else (k.low <= stop)
            hit_take = (k.low <= take) if short else (k.high >= take)
            if hit_stop or hit_take:
                risk = abs(limit - stop)
                gross = -1.0 if hit_stop else abs(take - limit) / risk
                stop_pct = risk / limit * 100
                upd.update(outcome_at=ts.isoformat(), r_gross=gross, r_net=gross - (cost_pct / stop_pct if stop_pct else 0.0))
                state = "stop_loss" if hit_stop else "take_profit"
                break
    if state == "waiting" and now >= expires:
        state = "verlopen"
    upd.update(state=state, filled_at=filled_at)
    return upd


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def verdict(rows: list[dict]) -> dict:
    """De vaste promotieregel op de afgeronde schaduwtrades van één variant (beide armen). Zie de moduletekst."""
    done = [r for r in rows if r.get("state") in DONE and r.get("r_net") is not None and r.get("outcome_at")]
    arm = {a: [r for r in done if r["arm"] == a] for a in ARMS}
    n_v, n_h = len(arm["variant"]), len(arm["hoofd"])
    mean_v = _mean([r["r_net"] for r in arm["variant"]])
    mean_h = _mean([r["r_net"] for r in arm["hoofd"]])
    out = {"n_variant": n_v, "n_hoofd": n_h, "netto_variant": mean_v, "netto_hoofd": mean_h,
           "verschil": None if mean_v is None or mean_h is None else mean_v - mean_h, "helften": [], "marge": None}
    if n_v < MIN_TRADES or n_h < MIN_TRADES:
        return {**out, "verdict": "wachten", "reden": f"nog geen {MIN_TRADES} afgeronde trades per arm"}
    times = [_ts(r["outcome_at"]) for r in done]
    mid = min(times) + (max(times) - min(times)) / 2
    for name, part in (("eerste helft", lambda t: t < mid), ("tweede helft", lambda t: t >= mid)):
        v = _mean([r["r_net"] for r in arm["variant"] if part(_ts(r["outcome_at"]))])
        h = _mean([r["r_net"] for r in arm["hoofd"] if part(_ts(r["outcome_at"]))])
        out["helften"].append({"naam": name, "variant": v, "hoofd": h, "beter": v is not None and h is not None and v > h})
    week = lambda r: stats.week_key(_ts(r["outcome_at"]))
    lo, hi = stats.cluster_bootstrap_diff([r["r_net"] for r in arm["variant"]], [week(r) for r in arm["variant"]],
                                          [r["r_net"] for r in arm["hoofd"]], [week(r) for r in arm["hoofd"]])
    out["marge"] = (lo, hi)
    if all(h["beter"] for h in out["helften"]) and lo > 0:
        return {**out, "verdict": "promoveren", "reden": "beter in beide helften en het verschil ligt per week boven 0"}
    if hi < 0:
        return {**out, "verdict": "afvallen", "reden": "duidelijk slechter: het verschil ligt per week onder 0"}
    if n_v >= MAX_TRADES and n_h >= MAX_TRADES:
        return {**out, "verdict": "afvallen", "reden": f"na {MAX_TRADES} trades per arm niet aantoonbaar beter"}
    return {**out, "verdict": "wachten", "reden": "nog niet aantoonbaar beter of slechter"}


def _num(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def change_text(trade_type: str, params: dict, base: dict) -> str:
    """'stop 0,4 ATR in plaats van 0,25' voor elke gewijzigde parameter."""
    parts = []
    for name, value in params.items():
        word, unit = PARAM_TEXT.get(name, (name, ""))
        sep = "" if unit == "%" else " "
        parts.append(f"{word} {_num(value)}{sep}{unit} in plaats van {_num(base[name])}")
    return ", ".join(parts)


def _r(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:+.2f}R".replace(".", ",")


def promote_text(variant: dict, v: dict, base: dict) -> str:
    return (f"{label(variant['trade_type'])}: {change_text(variant['trade_type'], json.loads(variant['params']), base)}, "
            f"netto {_r(v['verschil'])} per trade over {v['n_variant']} trades. Terugdraaien: python3 scripts/schaduw.py --terug {variant['id']}")


def summary_line(variant: dict, v: dict) -> str:
    """Eén regel voor Bewijs (alleen de CEO): variant tegen hoofd, aantallen, netto R en het verdict."""
    base = defaults(variant["trade_type"])
    return (f"Schaduw {variant['id']}: {change_text(variant['trade_type'], json.loads(variant['params']), base)}. Variant {v['n_variant']} trades "
            f"{_r(v['netto_variant'])}, hoofd {v['n_hoofd']} trades {_r(v['netto_hoofd'])} per trade, netto. Verdict: {v['verdict']} ({v['reden']}).")


def bewijs_lines() -> dict[str, list[str]]:
    """Per soort de regels van de actieve schaduwen. structuur_c deelt de motor van structuur en krijgt dezelfde regel niet nog eens."""
    out: dict[str, list[str]] = {}
    for variant in repo.list_shadow_variants(("schaduw",)):
        out.setdefault(variant["trade_type"], []).append(summary_line(variant, verdict(repo.list_shadow_results(variant["id"]))))
    return out


def export_rows() -> list[dict]:
    """Voor de nachtelijke export: elke variant met zijn parameters, status en verdict, en de tellingen per arm en stand."""
    out = []
    for variant in repo.list_shadow_variants(STATUSES):
        rows = repo.list_shadow_results(variant["id"])
        v = verdict(rows)
        counts: dict = {}
        for r in rows:
            counts.setdefault(r["arm"], {}).setdefault(r["state"], 0)
            counts[r["arm"]][r["state"]] += 1
        out.append({"id": variant["id"], "trade_type": variant["trade_type"], "beschrijving": variant["description"], "reden": variant["reason"],
                    "params": json.loads(variant["params"]), "aangemaakt": variant["created_at"], "status": variant["status"],
                    "besluit": variant.get("decision_note"), "standen": counts,
                    "verdict": {**{k: v[k] for k in ("verdict", "reden", "n_variant", "n_hoofd", "netto_variant", "netto_hoofd", "verschil",
                                                     "helften", "marge")},
                                "tekst": f"{v['verdict']}: variant {v['n_variant']} {_r(v['netto_variant'])}, hoofd {v['n_hoofd']} {_r(v['netto_hoofd'])}"}})
    return out
