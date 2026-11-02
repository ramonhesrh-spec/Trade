"""De kaart van het HesPulse-model op Kansen, de teksten van de meldingen en het signaal bij de vulling. Pure functies zonder database of netwerk;
de motor (app/model_live.py) en de pagina (web/main.py, app/kansen.py) lezen een rij uit model_scenarios.

Eén kaart per scenario met twee momenten (preregistratie §5): "Scenario ontdekt" (status wacht_sweep, prik, wacht_shift of wacht_fvg; de kaart
zegt waarop we wachten en toont elke stap met het moment waarop hij herkenbaar was) en "Entry beschikbaar" (status afgerond, entry_state wacht:
limiet, stop, doel en R:R, als gewoon limietplan via radar.setup_card). Ongetest; geen tijdfilter en geen kill zones in de tekst."""
import json
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app import btc_context, model, price_text

TRADE_TYPE = model.TRADE_TYPE
LABEL = model.LABEL
TAB_LABEL = "HesPulse"            # past op 375px naast de andere tabnamen
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

STATE_SHORT = {"wacht_sweep": "Wacht op sweep", "prik": "Sweep bezig", "wacht_shift": "Wacht op shift", "wacht_fvg": "Wacht op gap"}
STEP_NAMES = {"ontdekt": "Scenario ontdekt", "sweep": "Sweep", "shift": "Shift", "displacement": "Displacement met gap", "entry": "Entry beschikbaar"}


def key(scenario_id: int) -> str:
    return f"{model.KEY_PREFIX}:{scenario_id}"


def dom_id(scenario_id: int) -> str:
    return f"radar-{model.KEY_PREFIX}-{scenario_id}"


def card_url(scenario_id: int) -> str:
    return f"/smc#{dom_id(scenario_id)}"


def tag(scenario_id: int) -> str:
    return f"hespulse-model-{scenario_id}"


def _iso(v) -> Optional[str]:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _plain(v):
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v


def row_of(coin: str, sc: dict) -> dict:
    """Een scenario uit model.scenarios als rij voor model_scenarios (zonder de momenten van vastleggen: die zet de motor)."""
    steps = {s["stap"]: s for s in sc["steps"]}
    e = sc.get("entry") or {}
    row = {
        "coin": coin, "direction": sc["direction"], "range_id": sc["range_id"], "status": sc["status"],
        "range_low": sc["range_low"], "range_high": sc["range_high"], "eq": sc["eq"], "pool_level": sc["pool0"]["level"],
        "candidates": json.dumps(_plain(sc["candidates"])),
        "steps": json.dumps(_plain({"steps": sc["steps"], "attempts": sc["attempts"], "pool0": sc["pool0"], "range_at": sc["range_at"],
                                    "swing_at": sc["swing_at"], "v1": sc["v1"], "entry": e or None})),
        "discovered_at": _iso(sc["discovered_at"]), "sweep_at": _iso(steps.get("sweep", {}).get("at")),
        "shift_at": _iso(steps.get("shift", {}).get("at")), "entry_at": _iso(e.get("known_at")), "ended_at": _iso(sc["ended_at"]),
    }
    if e:
        row.update({"limit_price": e["limit"], "stop_loss": e["stop"], "take_profit": e["take"], "rr": e["rr"], "zone_low": e["zone_low"],
                    "zone_high": e["zone_high"], "target_kind": e["target_kind"], "target_text": e["target_label"],
                    "ob_overlap": int(e["ob_overlap"]), "poc_samenval": None if e["poc_samenval"] is None else int(e["poc_samenval"]),
                    "shift_label": e["shift_label"], "extreme": e["extreme"], "expires_at": _iso(e["expires_at"])})
    return row


def plan_ok(row: dict) -> bool:
    """Long: stop < limiet < doel; short: doel < limiet < stop. Titel, push, kaart, grafiek en signaal lezen allemaal deze ene rij."""
    stop, limit, take = row.get("stop_loss"), row.get("limit_price"), row.get("take_profit")
    if None in (stop, limit, take):
        return False
    return stop < limit < take if row["direction"] == "long" else take < limit < stop


def btc_of(row: dict) -> dict:
    try:
        return json.loads(row.get("btc_context") or "{}") or {}
    except ValueError:
        return {}


STATUS_WORDS = {"wacht_sweep": "scenario ontdekt", "prik": "scenario ontdekt", "wacht_shift": "scenario ontdekt", "wacht_fvg": "scenario ontdekt",
                "afgerond": "entry beschikbaar", "gevuld": "gevuld"}


def status_word(row: dict) -> str:
    if row.get("entry_state") == "gevuld":
        return "gevuld"
    return STATUS_WORDS.get(row["status"], row["status"])


def context_lines(row: dict) -> list[str]:
    """Drie dingen apart (aanvulling CEO 2026-11-02): de context (4u-richting van de coin en van BTC, gemeten), het entrytype (het model gaat
    altijd met de 4u-structuur mee) en de stand. De BTC-context is die van moment B als die er is, anders van moment A."""
    ctx = btc_of(row)
    btc = ctx.get("b") or ctx.get("a")
    coin_bias = "bullish" if row["direction"] == "long" else "bearish"
    lines = [f"Context: {row['coin']} 4u {coin_bias} · {btc_context.text(btc)}"]
    rel = btc_context.rel_text(btc)
    if rel:
        lines.append(rel)
    lines += [f"Entrytype: met de 4u-structuur mee ({row['direction']})", f"Status: {status_word(row)}"]
    return lines


def face_line(row: dict) -> str:
    """De korte regel op de kaart zelf: stand, entrytype en BTC 4u."""
    btc = (btc_of(row).get("b") or btc_of(row).get("a") or {}).get("btc_4h") or "onbekend"
    return f"{status_word(row).capitalize()} · met de 4u-structuur mee · BTC 4u {btc}"


def detail(row: dict) -> dict:
    try:
        return json.loads(row.get("steps") or "{}")
    except ValueError:
        return {}


def when(stamp: Optional[str], now: Optional[datetime] = None) -> str:
    """'14:15' vandaag, 'gisteren 14:15', anders '3 nov 14:15', in Nederlandse tijd."""
    from app.kansen import when_text
    return when_text(stamp, now)


def _side(direction: str) -> tuple[str, str]:
    return ("onder", "boven") if direction == "long" else ("boven", "onder")


def waiting_text(row: dict) -> str:
    """De zin op de kaart bij moment A (4.13): waarop we wachten, zonder getallen te herhalen die er al staan."""
    below, above = _side(row["direction"])
    half = "discount" if row["direction"] == "long" else "premium"
    status = row["status"]
    if status in ("wacht_shift", "wacht_fvg"):
        return (f"De sweep is gebeurd. Wacht op een 15m-slot {above} de top van vóór de sweep, met displacement en een fair value gap. "
                f"Dan komt de limiet op de gap.")
    if status == "prik":
        return f"De koers prikt {below} de pool. Wacht op een slot terug {above} de pool binnen 6 candles van 15m."
    return (f"Wacht op een sweep van de pool {below} de koers (of een verdere pool in {half}), dan een 15m-slot {above} de top ervoor met "
            f"displacement, dan een limiet op de gap.")


def step_lines(row: dict, now: Optional[datetime] = None) -> list[dict]:
    """Elke stap met het moment waarop hij herkenbaar was, en wat er nog moet gebeuren. Mislukte pogingen staan erbij met de reden."""
    d = detail(row)
    lines = []
    for a in d.get("attempts") or []:
        lines.append({"name": f"Poging op {price_text.nl(a['pool'])}" if a.get("pool") is not None else "Poging",
                      "when": when(a.get("at"), now), "done": False, "note": model.FAIL_REASONS.get(a["reden"], a["reden"])})
    done = {s["stap"]: s for s in d.get("steps") or []}
    for stap in model.STEP_ORDER:
        s = done.get(stap)
        note = ""
        if stap == "sweep" and s:
            note = f"Pool {price_text.nl(s['pool'])}, uiterste {price_text.nl(s['extreme'])}"
        elif stap == "shift" and s:
            note = f"Slot voorbij de top {price_text.nl(s['top'])}" + (f" ({s['label']})" if s.get("label") else "")
        elif stap == "displacement" and s:
            note = f"Candles gesloten {when(s.get('gesloten_at'), now)}"
        if stap == "displacement" and not s and not done.get("entry"):
            continue
        lines.append({"name": STEP_NAMES[stap], "when": when(s["at"], now) if s else "", "done": bool(s), "note": note})
    return lines


def candidate_text(row: dict) -> str:
    try:
        cands = json.loads(row.get("candidates") or "[]")
    except ValueError:
        cands = []
    parts = [("Rand van de range" if c["kind"] == "range" else c["label"]) + f" {price_text.nl(c['price'])}" for c in cands]
    return "Doelen in beeld: " + ", ".join(parts) if parts else ""


def scenario_rows(row: dict) -> list[dict]:
    """Range, evenwicht en pool, hoogste bovenaan, voor het blad. Geen limiet: die komt pas bij moment B."""
    rows = [{"label": "Range boven", "value": row["range_high"], "tone": "win" if row["direction"] == "long" else "loss"},
            {"label": "Evenwicht", "value": row["eq"], "tone": "entry"},
            {"label": "Pool", "value": row["pool_level"], "tone": "entry"},
            {"label": "Range onder", "value": row["range_low"], "tone": "loss" if row["direction"] == "long" else "win"}]
    rows.sort(key=lambda r: -r["value"])
    return [{**r, "text": price_text.nl(r["value"]), "copy": price_text.plain(r["value"])} for r in rows]


def scenario_item(row: dict, now: Optional[datetime] = None) -> dict:
    """Moment A als item voor kansen.page: geen order, wel de stappen en de zin waarop we wachten."""
    sid = row["id"]
    return {"kind": "scenario", "key": key(sid), "dom_id": dom_id(sid), "coin": row["coin"], "direction": row["direction"],
            "title": f"{row['coin']} {row['direction']}", "state": "scenario", "state_short": STATE_SHORT.get(row["status"], "Scenario"),
            "group": "scenarios", "tab": TRADE_TYPE, "trade_type": TRADE_TYPE, "untested": True, "rr_text": "",
            "svg_src": f"/api/kaart_svg/{key(sid)}", "chart": scenario_chart(row), "say": waiting_text(row), "steps_done": step_lines(row, now),
            "candidates_text": candidate_text(row), "rows": scenario_rows(row), "created_at": row.get("detected_at"),
            "shared_text": f"Ontdekt {when(row.get('discovered_at'), now)}", "origin": f"{LABEL} · context 4u, pools 1u, sweep en shift op 15m",
            "num_text": "", "num_label": "", "num_hook": "distance", "share_lines": [], "model_lines": context_lines(row),
            "model_face": face_line(row)}


def chart_zone(row: dict) -> dict:
    """Wat "Groot" (de schuifbare candlegrafiek van levelchart.js, keuze 15m/1u/4u) over de entryzone tekent: het vlak met zijn naam,
    zonder ontstaansmoment, want de rij bewaart dat niet; levelchart.js zegt dan niets over waar hij ontstond."""
    return {"tf": "15m", "kind": "bull" if row["direction"] == "long" else "bear",
            "label": "15m OB" if row.get("ob_overlap") else "15m FVG", "origin": None, "note": None, "note_other_tf": None,
            "note_outside": None, "target_low": None, "target_high": None, "target_label": None}


def scenario_chart(row: dict) -> dict:
    """Moment A heeft nog geen order: "Groot" toont de 4u-range als vlak op een schuifbare grafiek (4u eerst), zonder limiet, stop of doel."""
    return {"direction": row["direction"], "stop": None, "take": None, "limit": None, "entry": None, "price": None,
            "zone_low": row["range_low"], "zone_high": row["range_high"],
            "zone": {"tf": "4h", "kind": "bull" if row["direction"] == "long" else "bear", "label": "4u range", "origin": None,
                     "note": None, "note_other_tf": None, "note_outside": None, "target_low": None, "target_high": None, "target_label": None},
            "label": f"Scenario {row['direction']}: 4u range {price_text.nl(row['range_low'])} tot {price_text.nl(row['range_high'])}"}


def radar_setup(row: dict) -> dict:
    """Moment B (entry beschikbaar) in de vorm die radar.setup_card leest: de zone is de FVG of de overlap met het order block."""
    return {**row, "source": TRADE_TYPE, "limit": row["limit_price"], "preview_stop_loss": row["stop_loss"], "preview_take_profit": row["take_profit"],
            "created_at": row.get("entry_detected_at") or row.get("entry_at"), "chart_zone": chart_zone(row),
            "origin_label": f"{LABEL} · " + ("overlap van gap en order block" if row.get("ob_overlap") else "fair value gap") + " op 15m"
                            + (" · bij een naakte POC" if row.get("poc_samenval") else "")}


def fp(v: float) -> str:
    from app import push_notify
    return push_notify.fmt_price(v)


def target_word(row: dict) -> str:
    return "rand van de range" if row.get("target_kind") == "range" else (row.get("target_text") or "naakte POC")


def entry_title(row: dict) -> str:
    from app import push_notify
    return push_notify.alert_title(row["coin"], row["direction"], "HesPulse · entry")


def entry_body(row: dict) -> str:
    """De ene luide melding (besluit CEO 3): zet de order nu."""
    from app import push_notify
    return "\n".join([f"Limiet {fp(row['limit_price'])}" + (f" · R:R {row['rr']:.1f}" if row.get("rr") else ""),
                      f"Stop {fp(row['stop_loss'])} · Doel {fp(row['take_profit'])} ({target_word(row)})",
                      "Sweep, shift en gap zijn er: zet je limietorder als je hem wilt. 6 uur geldig. Ongetest.", push_notify.OPEN_PLAN_LINE])


def fill_title(row: dict) -> str:
    from app import push_notify
    return push_notify.alert_title(row["coin"], row["direction"], "HesPulse gevuld")


def fill_body(row: dict) -> str:
    from app import push_notify
    return "\n".join([f"Limiet geraakt op {fp(row['limit_price'])}, stop {fp(row['stop_loss'])}, doel {fp(row['take_profit'])}",
                      "Stond jouw limiet er, dan is die nu gevuld. Het systeem plaatst zelf nooit een order. Ongetest.", push_notify.OPEN_PLAN_LINE])


def signal_row(row: dict) -> dict:
    """Het signaal bij de vulling, buiten de openbare ketting (chain_it=False): het model is ongetest."""
    entry = row["limit_price"]
    feats = [f"Doel: {target_word(row)}", "OB-overlap: " + ("ja" if row.get("ob_overlap") else "nee"),
             "POC-samenval: " + ({1: "ja", 0: "nee"}.get(row.get("poc_samenval"), "niet gemeten")),
             f"Shift: {row.get('shift_label') or 'zonder label'}"]
    return {"message_id": None, "coin": row["coin"], "direction": row["direction"], "category": "day_trading", "trade_type": TRADE_TYPE,
            "pattern_name": LABEL, "price": entry, "stop_loss": row["stop_loss"], "take_profit": row["take_profit"],
            "confidence": f"{LABEL} (ongetest)", "technical_confirmed": 1, "hard_gates_ok": 1, "is_practice": 0, "pass_pct": None,
            "reason": "Gemeten: " + " | ".join(feats),
            "plain_explanation": (f"Sweep van de pool {row['pool_level']:.6g}, shift op 15m met displacement, limiet op de gap {entry:.6g}, stop "
                                  f"{row['stop_loss']:.6g} voorbij het uiterste, doel {row['take_profit']:.6g} ({target_word(row)}). Ongetest."),
            "suggested_entry_low": row["zone_low"], "suggested_entry_high": row["zone_high"]}


def local(stamp: Optional[str]) -> str:
    if not stamp:
        return ""
    at = datetime.fromisoformat(str(stamp))
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return at.astimezone(LOCAL_TZ).strftime("%d-%m %H:%M")
