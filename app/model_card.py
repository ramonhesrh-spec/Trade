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

# Geen "Wacht op sweep" (CEO 2026-11-03): een sweep is alleen nodig voor A; B, R, V1 en P komen zonder sweep.
STATE_SHORT = {"wacht_sweep": "Wacht op entry", "prik": "Sweep bezig", "wacht_shift": "Wacht op shift", "wacht_fvg": "Wacht op gap"}
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


# Aanvullend besluit CEO 2026-11-03: alle instappunten op één kaart; de gebruiker kiest. Sinds B-2026-11-03-06 staat B0 er ook (ONDO).
ENTRY_INFO = {
    "A": ("Na sweep", "Sweep van een liquiditeitspool, daarna een breuk op 15m met displacement; limiet op de gap."),
    "B": ("Lagere top", "Een lagere 1u-top in premium (long: hogere bodem in discount), daarna een breuk op 15m met displacement; limiet op de gap."),
    "B0": ("Lagere top, ook buiten premium", "Als B, maar de lagere top mag ook onder het evenwicht van de range liggen (long: boven); limiet op de gap."),
    "V1": ("Vroege limiet op de pool", "Limiet op de liquiditeitspool zelf, zonder op de sweep te wachten; stop 1 ATR (1u) erachter."),
    "R": ("Breuk en terugtest", "Een lagere 1u-top in premium (long: hogere bodem in discount), daarna een slot voorbij het laatste 15m-dal; limiet op dat gebroken niveau, zonder displacement of gap."),
    "P": ("POC-limiet", "Limiet op de dichtste naakte dag- of week-POC aan de goede kant van het evenwicht; stop 1 ATR (1u) erachter."),
}
ENTRY_STATE_WORDS = {"wacht": "wacht op vulling", "gevuld": "gevuld", "klaar": "afgerond", "vervallen": "vervallen", "weggelopen": "weggelopen",
                     "context_weg": "context weg", "niet_vulbaar": "niet vulbaar", "geen_doel": "geen doel", "btc_tegen": "tegen BTC, niet gemeld"}


def entry_points(row: dict, v1: Optional[dict], extra: list[dict]) -> list[dict]:
    """Alle instappunten van één scenario, voor de grafiek (letter en limiet) en het detailblad (basis, niveaus, R:R, stand). A alleen als
    moment B er is; V1 uit model_v1; B en P uit model_entries."""
    out = []
    if row.get("limit_price") is not None:
        out.append({"code": "A", "limit": row["limit_price"], "stop": row["stop_loss"], "take": row.get("take_profit"), "rr": row.get("rr"),
                    "known_at": row.get("entry_at"), "state": row.get("entry_state") or "wacht"})
    if v1 and v1.get("limit_price") is not None and v1.get("state") != "geen_doel":
        out.append({"code": "V1", "limit": v1["limit_price"], "stop": v1["stop_loss"], "take": v1.get("take_profit"), "rr": v1.get("rr"),
                    "known_at": v1.get("placed_at"), "state": v1.get("state")})
    for e in sorted(extra, key=lambda e: e["code"]):
        if e["code"] in ENTRY_INFO:
            out.append({"code": e["code"], "limit": e["limit_price"], "stop": e["stop_loss"], "take": e.get("take_profit"), "rr": e.get("rr"),
                        "known_at": e.get("known_at"), "state": e.get("state")})
    for p in out:
        name, basis = ENTRY_INFO[p["code"]]
        p.update(name=name, basis=basis, state_text=ENTRY_STATE_WORDS.get(p["state"], p["state"] or ""),
                 rr_text="" if p["rr"] is None else f"{p['rr']:.1f}".replace(".", ",") + " R:R",
                 levels=f"Limiet {price_text.nl(p['limit'])} · Stop {price_text.nl(p['stop'])}"
                        + (f" · Doel {price_text.nl(p['take'])}" if p["take"] is not None else ""))
    return out


def btc_against(row: dict) -> bool:
    """De BTC-poort (config.MODEL_BTC_GATE): BTC 4u bij moment B wijst de andere kant op. Onbekend of neutraal houdt niets tegen."""
    b = btc_of(row).get("b") or {}
    return (row["direction"], b.get("btc_4h")) in (("long", "bearish"), ("short", "bullish"))


STATUS_WORDS = {"wacht_sweep": "scenario ontdekt", "prik": "scenario ontdekt", "wacht_shift": "scenario ontdekt", "wacht_fvg": "scenario ontdekt",
                "afgerond": "entry beschikbaar", "gevuld": "gevuld"}


def status_word(row: dict) -> str:
    if row.get("entry_state") == "gevuld":
        return "gevuld"
    return STATUS_WORDS.get(row["status"], row["status"])


def context_lines(row: dict) -> list[str]:
    """Drie dingen apart (aanvulling CEO 2026-11-02): de context (4u-richting van de coin en van BTC, gemeten), het entrytype (het model gaat
    altijd met de dagtrend en de 4u-range mee, aanvullend besluit 2026-11-03) en de stand. De BTC-context is die van moment B als die er is, anders van moment A."""
    ctx = btc_of(row)
    btc = ctx.get("b") or ctx.get("a")
    coin_bias = "bullish" if row["direction"] == "long" else "bearish"
    lines = [f"Context: {row['coin']} 4u {coin_bias} · {btc_context.text(btc)}"]
    rel = btc_context.rel_text(btc)
    if rel:
        lines.append(rel)
    lines += [f"Entrytype: met de dagtrend en de 4u-range mee ({row['direction']})", f"Status: {status_word(row)}"]
    return lines


def face_line(row: dict) -> str:
    """De korte regel op de kaart zelf: stand, entrytype en BTC 4u."""
    btc = (btc_of(row).get("b") or btc_of(row).get("a") or {}).get("btc_4h") or "onbekend"
    return f"{status_word(row).capitalize()} · met de dagtrend mee · BTC 4u {btc}"


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
    status = row["status"]
    if status in ("wacht_shift", "wacht_fvg"):
        return (f"De sweep is gebeurd. Wacht op een 15m-slot {above} de top van vóór de sweep, met displacement en een fair value gap. "
                f"Dan komt de limiet op de gap.")
    if status == "prik":
        return f"De koers prikt {below} de pool. Wacht op een slot terug {above} de pool binnen 6 candles van 15m."
    turn = "hogere bodem in discount" if row["direction"] == "long" else "lagere top in premium"
    return (f"Wacht op een entry; een sweep is niet nodig. A: sweep van de pool {below} de koers, dan een 15m-breuk met een gap. "
            f"B en R: een {turn} met een 15m-breuk, zonder sweep. V1 en P: een limiet op de pool of de POC.")


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


READY_CODES = ("B", "B0", "R")


def nearest_point(row: dict) -> tuple[Optional[str], Optional[float]]:
    """Het dichtste wachtende instappunt bij de koers van nu (row['price'], gezet door de route), als (letter, afstand in %). Zonder punt de
    pool. Zonder koers (None, None). Alleen voor de volgorde en de korte regel van de lijst (B-2026-11-03-07), nooit voor een melding."""
    price = row.get("price")
    if not price:
        return None, None
    levels = [(p["code"], p["limit"]) for p in row.get("entry_points") or [] if p.get("state") == "wacht" and p.get("limit") is not None]
    if not levels and row.get("pool_level") is not None:
        levels = [("pool", row["pool_level"])]
    if not levels:
        return None, None
    code, level = min(levels, key=lambda x: abs(price - x[1]))
    return code, abs(price - level) / price * 100


def scenario_item(row: dict, now: Optional[datetime] = None) -> dict:
    """Moment A als item voor kansen.page: geen order, wel de stappen en de zin waarop we wachten. Met een wachtend B-, B0- of R-plan is hij
    `ready` en blijft hij een volle kaart; anders een korte regel (`compact`) met de afstand tot het dichtste instappunt (CEO 2026-11-03:
    "28 open en moet je heel lang scrollen")."""
    sid = row["id"]
    ready = any(p["code"] in READY_CODES and p.get("state") == "wacht" for p in row.get("entry_points") or [])
    code, dist = nearest_point(row)
    ready_codes = [p["code"] for p in row.get("entry_points") or [] if p["code"] in READY_CODES and p.get("state") == "wacht"]
    dist_text = "" if dist is None else f"{dist:.1f}".replace(".", ",") + f"% tot {code}"
    return {"ready": ready, "compact": not ready, "dist_pct": dist, "dist_text": dist_text,"kind": "scenario", "key": key(sid), "dom_id": dom_id(sid), "coin": row["coin"], "direction": row["direction"],
            "title": f"{row['coin']} {row['direction']}", "state": "scenario", "state_short": f"Plan {'/'.join(ready_codes)} klaar" if ready else STATE_SHORT.get(row["status"], "Scenario"),
            "group": "scenarios", "tab": TRADE_TYPE, "trade_type": TRADE_TYPE, "untested": True, "rr_text": "",
            "svg_src": f"/api/kaart_svg/{key(sid)}", "chart": scenario_chart(row), "say": waiting_text(row), "steps_done": step_lines(row, now),
            "candidates_text": candidate_text(row), "rows": scenario_rows(row), "created_at": row.get("detected_at"),
            "shared_text": f"Ontdekt {when(row.get('discovered_at'), now)}", "origin": f"{LABEL} · context 4u, pools 1u, sweep en shift op 15m",
            "num_text": "", "num_label": "", "num_hook": "distance", "share_lines": [], "model_lines": context_lines(row),
            "model_face": face_line(row), "entry_points": row.get("entry_points") or []}


def chart_zone(row: dict) -> dict:
    """Wat "Groot" (de schuifbare candlegrafiek van levelchart.js, keuze 15m/1u/4u) over de entryzone tekent: het vlak met zijn naam,
    zonder ontstaansmoment, want de rij bewaart dat niet; levelchart.js zegt dan niets over waar hij ontstond."""
    return {"tf": "15m", "kind": "bull" if row["direction"] == "long" else "bear",
            "label": "15m OB" if row.get("ob_overlap") else "15m FVG", "origin": None, "note": None, "note_other_tf": None,
            "note_outside": None, "target_low": None, "target_high": None, "target_label": None}


def scenario_chart(row: dict) -> dict:
    """Moment A heeft nog geen order: "Groot" toont de schuifbare grafiek op 1u met de benoemde niveaus (card_chart.model_marks: 4u range high
    en low, evenwicht, de 1u-pool en de andere instappunten), zonder limiet, stop of doel. Eerder stond hier alleen een vlak "4u range", en
    dat zei niets (CEO 2026-11-03)."""
    from app import card_chart
    return {"direction": row["direction"], "stop": None, "take": None, "limit": None, "entry": None, "price": None,
            "zone_low": None, "zone_high": None, "zone": None, "tf": "1h",
            "marks": card_chart.model_marks(row, row.get("entry_points")),
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


def entry_title(row: dict, code: str = "A") -> str:
    from app import push_notify
    return push_notify.alert_title(row["coin"], row["direction"], f"HesPulse {code}")


def levels_line(limit: float, stop: float, take: Optional[float]) -> str:
    """Kort en bondig (CEO 2026-11-03: "nu is het zo'n lange tekst"): alleen de drie niveaus. De uitleg staat op de kaart."""
    return f"Limiet {fp(limit)} · Stop {fp(stop)}" + (f" · Doel {fp(take)}" if take is not None else "")


def entry_body(row: dict) -> str:
    return levels_line(row["limit_price"], row["stop_loss"], row.get("take_profit"))


def fill_title(row: dict) -> str:
    from app import push_notify
    return push_notify.alert_title(row["coin"], row["direction"], "HesPulse gevuld")


def fill_body(row: dict) -> str:
    return f"Gevuld op {fp(row['limit_price'])} · Stop {fp(row['stop_loss'])} · Doel {fp(row['take_profit'])}"


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
