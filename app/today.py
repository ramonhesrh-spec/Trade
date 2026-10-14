"""Weergave voor de pagina Vandaag: tijdlijn van de komende 24 uur, scenario's uit het markt-script, liquidatiebalken
en de marktstemming. Pure functies zonder database of netwerk, zodat ze met tests te controleren zijn."""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from app import chance_steps
from app import market_script as ms
from app import push_policy
from app import trade_plan as tp

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

# Gemeten met scripts/calendar_scan.py op 1m-candles van 2025-08 tot 2026-10, zeven coins: de beweging in het uur na het
# moment, gedeeld door die in een gewoon uur. Alleen waarden die duidelijk afwijken worden getoond (zie vol_note).
MEASURED_VOLATILITY = {"vs_open": 1.86, "funding": 1.01, "opties_expiry": 1.06}
VOL_NOTE_MIN = 1.3

KIND_LABEL = {"funding": "Funding", "vs_open": "VS opent", "opties_expiry": "Opties-expiry", "macro": "Macro"}
STATE_LABELS = {
    "waiting": "Wacht op de voorwaarde",
    "fired": "Afgegaan: melding verstuurd",
    "expired": "Vervallen",
    "missed": "Gemist: prijs was al voorbij stop of take",
}


def agenda(moments: list[dict]) -> list[dict]:
    """Alleen momenten die iets te zeggen hebben: macro-uitslagen altijd, de rest alleen als de toets een duidelijk grotere
    beweging mat. Funding-resets (1,01x) en opties-expiry (1,06x) bewegen de markt niet meetbaar en vulden de agenda met ruis."""
    return [m for m in moments if m["kind"] == "macro" or MEASURED_VOLATILITY.get(m["kind"], 0) >= VOL_NOTE_MIN]


def vol_note(kind: str) -> Optional[str]:
    x = MEASURED_VOLATILITY.get(kind)
    return f"beweegt {x:.1f}x harder dan normaal".replace(".", ",") if x and x >= VOL_NOTE_MIN else None


def local(dt: datetime) -> datetime:
    return dt.astimezone(LOCAL_TZ)


def timeline_svg(now: datetime, moments: list[dict], hours: int = 24, width: int = 760, height: int = 118) -> str:
    """Horizontale as van nu tot `hours` uur verder. De nu-marker staat links en schuift dus nooit: wat verandert is wat
    er op de as staat. Labels wisselen af tussen boven en onder de lijn zodat ze niet over elkaar vallen."""
    pad, axis_y = 22, 62
    span = width - 2 * pad

    def x_of(at: datetime) -> float:
        return pad + (at - now).total_seconds() / (hours * 3600) * span

    parts = [f'<svg class="vd-timeline" viewBox="0 0 {width} {height}" role="img" aria-label="Agenda van de komende {hours} uur">',
             f'<line class="vd-axis" x1="{pad}" x2="{width - pad}" y1="{axis_y}" y2="{axis_y}"/>']
    first_tick = (local(now).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    t = first_tick
    while t <= local(now) + timedelta(hours=hours):
        if t.hour % 4 == 0:
            x = x_of(t)
            parts.append(f'<line class="vd-tick" x1="{x:.1f}" x2="{x:.1f}" y1="{axis_y - 4}" y2="{axis_y + 4}"/>'
                         f'<text class="vd-tick-label" x="{x:.1f}" y="{axis_y + 18}" text-anchor="middle">{t:%H:%M}</text>')
        t += timedelta(hours=1)
    flip = 0
    for m in moments:
        at = m["at"].astimezone(timezone.utc)
        if not now <= at <= now + timedelta(hours=hours):
            continue
        x = x_of(at)
        up = flip % 2 == 0
        flip += 1
        y_label = axis_y - 22 if up else axis_y + 38
        anchor = "start" if x < width * 0.12 else "end" if x > width * 0.88 else "middle"
        note = vol_note(m["kind"])
        label = escape(m["label"])
        parts.append(
            f'<g class="vd-moment vd-moment-{escape(m["kind"])}">'
            f'<line class="vd-stem" x1="{x:.1f}" x2="{x:.1f}" y1="{axis_y}" y2="{(y_label + 4) if up else (y_label - 12):.1f}"/>'
            f'<circle cx="{x:.1f}" cy="{axis_y}" r="4.5"/>'
            f'<text class="vd-moment-label" x="{x:.1f}" y="{y_label}" text-anchor="{anchor}">{local(at):%H:%M} {label}</text>'
            + (f'<text class="vd-moment-note" x="{x:.1f}" y="{y_label + 11}" text-anchor="{anchor}">{escape(note)}</text>' if note else "")
            + '</g>')
    parts.append(f'<g class="vd-now"><circle cx="{pad}" cy="{axis_y}" r="6"/><text x="{pad}" y="{axis_y + 20}" text-anchor="start">Nu</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def scenario_view(s: dict, price: Optional[float], now: datetime, coin: str = "") -> dict:
    """Eén scenario als kaartje: voorwaarde in woorden, plan, R:R, afstand tot de voorwaarde, tijd tot verval."""
    expires = datetime.fromisoformat(s["expires_at"])
    expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
    hours_left = max(0.0, (expires - now).total_seconds() / 3600)
    rr = ms.rr_of(s["direction"], s["entry"], s["stop_loss"], s["take_profit"])
    to_trigger = None
    if price and s["state"] == "waiting":
        to_trigger = (s["trigger_level"] - price) / price * 100
    state = s["state"] if s["state"] != "waiting" or hours_left > 0 else "expired"
    view = {
        "id": s["id"], "coin": coin, "trigger_level": s["trigger_level"], "direction": s["direction"], "state": state, "state_label": STATE_LABELS.get(state, state),
        "trigger": ms.trigger_text(s["trigger_type"], s["direction"], s["trigger_level"]), "reason": s["reason"],
        "entry": s["entry"], "stop": s["stop_loss"], "take": s["take_profit"], "rr": rr,
        "risk_pct": abs(s["entry"] - s["stop_loss"]) / s["entry"] * 100, "hours_left": hours_left, "to_trigger_pct": to_trigger,
        "chart": tp.chart_spec(s["direction"], s["stop_loss"], s["take_profit"], s["entry"], price, entry=s["entry"]),
    }
    view["steps"] = chance_steps.script_steps(view)
    view["levels"] = chance_steps.level_chips(s["entry"], s["stop_loss"], s["take_profit"])
    return view


OPEN_SIGNAL_HOURS = 6
SIGNAL_LABELS = {"structuur": "Structuur gevuld", "structuur_c": "Structuur C gevuld", "trend": "Trend", "rejectie": "Rejectie", "smc": "SMC",
                 "smc_waarschuwing": "SMC met waarschuwing", "script": "Markt-script", "don55_trend": "Proefmotor"}
OPEN_PLAN_STATES = (None, "wacht", "in_zone")        # None: koers onbekend, dan is er niets dat het plan ongeldig maakt


def _aware(iso: str) -> datetime:
    at = datetime.fromisoformat(iso)
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def structure_state(setup: dict, plan: dict, price: Optional[float], now: datetime) -> Optional[str]:
    """Stand van een wachtend Structuur-plan: 'verlopen' na zijn eigen tijdstip, anders tp.plan_state op het retest-niveau
    (de engine zet de rij pas bij zijn volgende scan op expired, tot dan staat hij nog op waiting)."""
    if setup.get("expires_at") and _aware(setup["expires_at"]) <= now:
        return "verlopen"
    if not price:
        return None
    level = plan["level"]
    return tp.plan_state(setup["direction"], level, level, plan["stop"], price, take=plan["targets"][0])


def signal_is_open(signal: dict, price: Optional[float]) -> bool:
    """Een melding zonder uitkomst telt alleen mee zolang de koers nog tussen stop en doel staat; level_check sluit hem pas bij zijn volgende ronde."""
    stop, take = signal.get("stop_loss"), signal.get("take_profit")
    if not price or not stop or not take:
        return True
    return stop < price < take if signal["direction"] == "long" else take < price < stop


def open_chances(structure_cards: list[dict], scripts: list[dict], smc_cards: list[dict], signals: list[dict],
                 prices: dict, now: datetime) -> list[dict]:
    """De enige definitie van een open kans, voor het getal bij Kansen open, de tabteller, de ondertitel en de lijst die Vandaag toont.
    Alles wat hier binnenkomt is al door de kijker te zien (rule_live.for_viewer) en door het plan zelf als geldig bevonden:
    structuurkaarten komen uit web.main._structure_cards (niet verlopen, niet voorbij stop of doel), SMC-kaarten tellen alleen
    in 'wacht' of 'in_zone', scenario's alleen wachtend en niet vervallen, meldingen alleen zonder uitkomst en binnen OPEN_SIGNAL_HOURS.
    Gesorteerd op afstand tot de instap; zonder koers staat een kans achteraan."""
    items = []
    for c in structure_cards:
        step = c["steps"][0]["dist"] if c.get("steps") else "-"
        items.append({"kind": "structure", "coin": c["coin"], "direction": c["direction"], "soort": "Structuur", "state": "Wacht op de terugkeer",
                      "dist": abs(float(step.rstrip("%"))) if step != "-" else None, "dist_text": step if step != "-" else "", "url": "/structuur", "card": c})
    for c in smc_cards:
        if c["kind"] == "setup" and c["state"] in OPEN_PLAN_STATES:
            d = c["distance_pct"]
            items.append({"kind": "smc", "coin": c["coin"], "direction": c["direction"], "soort": "SMC-zone", "state": c["state_label"],
                          "dist": abs(d) if d is not None else None, "dist_text": f"{d:+.2f}%" if d is not None else "", "url": "/smc", "card": None})
    for s in scripts:
        for sc in s["scenarios"]:
            if sc["state"] == "waiting" and sc["hours_left"] > 0:
                d = sc["to_trigger_pct"]
                items.append({"kind": "scenario", "coin": s["coin"], "direction": sc["direction"], "soort": "Markt-script", "state": "Wacht op de voorwaarde",
                              "dist": abs(d) if d is not None else None, "dist_text": f"{d:+.2f}%" if d is not None else "", "url": "/vandaag#scripts", "card": None})
    since = now - timedelta(hours=OPEN_SIGNAL_HOURS)
    for g in signals:
        if g.get("auto_outcome") or g["trade_type"] not in SIGNAL_LABELS or _aware(g["created_at"]) < since or not signal_is_open(g, prices.get(g["coin"])):
            continue
        items.append({"kind": "signal", "coin": g["coin"], "direction": g["direction"], "soort": SIGNAL_LABELS[g["trade_type"]],
                      "state": "Open, gemeld", "dist": None, "dist_text": "", "url": f"/kans/{g['id']}", "card": None})
    return sorted(items, key=lambda i: (i["dist"] is None, i["dist"] or 0))


def nearest_chance(chances: list[dict]) -> Optional[dict]:
    """Het eerste van de lijst open kansen (die staat op afstand gesorteerd); '-' op de pagina alleen als de lijst leeg is."""
    if not chances:
        return None
    first = chances[0]
    return {"name": f"{first['coin']} {first['direction']}", "dist": first["dist_text"], "url": first["url"]}


def chances_unit(n: int) -> str:
    return "kans" if n == 1 else "kansen"


def ago_text(iso: Optional[str], now: datetime) -> str:
    """Hoe lang geleden een opgeslagen tijdstip was, in dezelfde woorden als de tijdlabels in base.html; '-' zonder tijdstip."""
    if not iso:
        return "-"
    at = datetime.fromisoformat(iso)
    mins = int((now - (at if at.tzinfo else at.replace(tzinfo=timezone.utc))).total_seconds() // 60)
    if mins < 1:
        return "net nu"
    if mins < 60:
        return f"{mins} min geleden"
    if mins < 60 * 24:
        return f"{mins // 60} uur geleden"
    return f"{mins // 1440} dgn geleden"


def script_view(script: dict, price: Optional[float], now: datetime) -> dict:
    created = datetime.fromisoformat(script["created_at"])
    created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    return {"coin": script["coin"], "summary": script["summary"], "bias": script["bias"], "price": price,
            "age_hours": (now - created).total_seconds() / 3600, "written": local(created),
            "scenarios": [scenario_view(s, price, now, script["coin"]) for s in script["scenarios"]], "n_dropped": script["n_dropped"]}


def mood(scripts: list[dict]) -> dict:
    """Marktstemming uit de scripts: hoeveel coins long, short of neutraal. Geen eigen oordeel, alleen optellen."""
    counts = {"long": 0, "short": 0, "neutraal": 0}
    waiting = {"long": 0, "short": 0}
    for s in scripts:
        counts[s["bias"] if s["bias"] in counts else "neutraal"] += 1
        for sc in s.get("scenarios", []):
            if sc["state"] == "waiting" and sc["direction"] in waiting:
                waiting[sc["direction"]] += 1
    total = sum(counts.values())
    return {**counts, "total": total, **{f"{k}_pct": (v / total * 100 if total else 0) for k, v in counts.items()},
            "wait_long": waiting["long"], "wait_short": waiting["short"], "wait_total": waiting["long"] + waiting["short"],
            "wait_long_pct": waiting["long"] / (waiting["long"] + waiting["short"]) * 100 if waiting["long"] + waiting["short"] else 0}


def liquidation_rows(by_coin: dict[str, list[dict]]) -> list[dict]:
    """Per coin de som over de meegegeven blokken, met breedtes ten opzichte van de grootste coin (voor de balken)."""
    rows = []
    for coin, blocks in by_coin.items():
        long_usd, short_usd = sum(b["long_usd"] for b in blocks), sum(b["short_usd"] for b in blocks)
        if long_usd or short_usd:
            rows.append({"coin": coin, "long_usd": long_usd, "short_usd": short_usd, "total": long_usd + short_usd})
    top = max((r["total"] for r in rows), default=0)
    for r in rows:
        r["width_pct"] = r["total"] / top * 100 if top else 0
        r["long_share"] = r["long_usd"] / r["total"] * 100
    return sorted(rows, key=lambda r: -r["total"])


def money(usd: float) -> str:
    if usd >= 1e6:
        return f"{usd / 1e6:.1f}M".replace(".", ",")
    if usd >= 1e3:
        return f"{usd / 1e3:.0f}K"
    return f"{usd:.0f}"


DAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def nl_stamp(dt: datetime) -> str:
    return f"{DAYS[dt.weekday()]} {dt:%d-%m, %H:%M}"


def fmt_price(value: float) -> str:
    """Vier decimalen onder de 100, twee erboven: 0,1632 en 67350,00 blijven allebei leesbaar."""
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def budget_ring(sent: int, budget: Optional[int], default: int = push_policy.DEFAULT_BUDGET) -> dict:
    """Pushes voor nieuwe kansen in de laatste 24 uur tegenover het dagbudget. Zelfde venster en zelfde telling als push_policy.decide,
    zodat de ring vol is precies wanneer nieuwe kansen alleen nog op de meldingenpagina komen. budget None = standaard, 0 = geen budget."""
    limit = default if budget is None else budget
    noun = "melding" if sent == 1 else "meldingen"
    if limit <= 0:
        return {"sent": sent, "limit": 0, "off": True, "offset": 100.0, "full": False, "label": f"{sent} {noun} in 24 uur, geen budget"}
    share = min(1.0, sent / limit)
    return {"sent": sent, "limit": limit, "off": False, "offset": round(100 - share * 100, 1), "full": sent >= limit,
            "label": f"{sent} van {limit} meldingen in 24 uur"}
