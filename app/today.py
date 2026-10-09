"""Weergave voor de pagina Vandaag: tijdlijn van de komende 24 uur, scenario's uit het markt-script, liquidatiebalken
en de marktstemming. Pure functies zonder database of netwerk, zodat ze met tests te controleren zijn."""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from app import chance_steps
from app import market_script as ms
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
        "ladder": tp.strip_html(s["direction"], s["stop_loss"], s["take_profit"], s["entry"], price, entry=s["entry"]),
    }
    view["steps"] = chance_steps.script_steps(view)
    return view


def nearest_chance(structure_cards: list[dict], scripts: list[dict], smc_cards: list[dict]) -> Optional[dict]:
    """De kans die het eerst aan de beurt is: de kleinste afstand in procent van de koers tot stap 1, over alle soorten heen.
    Alleen kansen met een bekende koers doen mee."""
    found = []
    for c in structure_cards:
        step = c["steps"][0]
        if step["dist"] != "-":
            found.append((abs(float(step["dist"].rstrip("%"))), f"{c['coin']} {c['direction']}", step["dist"], "tot het niveau", "/structuur"))
    for s in scripts:
        for sc in s["scenarios"]:
            if sc["state"] == "waiting" and sc["to_trigger_pct"] is not None:
                found.append((abs(sc["to_trigger_pct"]), f"{s['coin']} {sc['direction']}", f"{sc['to_trigger_pct']:+.2f}%", "tot de voorwaarde", "/vandaag"))
    for c in smc_cards:
        if c["kind"] == "setup" and c["distance_pct"] is not None:
            found.append((abs(c["distance_pct"]), f"{c['coin']} {c['direction']}", f"{c['distance_pct']:+.2f}%", "tot de zone", "/smc"))
    if not found:
        return None
    _, name, dist, what, url = min(found, key=lambda f: f[0])
    return {"name": name, "dist": dist, "what": what, "url": url}


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
