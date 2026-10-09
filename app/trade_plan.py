"""Handelsplan van een SMC-setup voor iemand die met een limietorder op de zone instapt: waar de order staat, wat de
R:R vanaf die prijs is, waar de koers nu staat ten opzichte van het plan, en een prijsladder als SVG voor in de
pagina. Alleen rekenen en tekenen, geen database en geen netwerk, zodat live melding, pagina en tests dezelfde
cijfers gebruiken."""
import math
from dataclasses import dataclass
from html import escape
from typing import Optional


@dataclass
class TradePlan:
    direction: str
    limit: float
    stop: float
    take: float
    risk_pct: float
    rr: float


def limit_plan(direction: str, zone_low: float, zone_high: float, stop: float, take: float) -> Optional[TradePlan]:
    """De limietorder staat op de rand van de zone die de koers als eerste raakt: de bovenkant voor een long (de
    koers komt van boven), de onderkant voor een short. None als stop of doel niet aan de juiste kant van die prijs liggen."""
    limit = zone_high if direction == "long" else zone_low
    sign = 1 if direction == "long" else -1
    if (limit - stop) * sign <= 0 or (take - limit) * sign <= 0:
        return None
    risk = abs(limit - stop)
    return TradePlan(direction, limit, stop, take, risk / limit * 100, abs(take - limit) / risk)


def plan_state(direction: str, zone_low: float, zone_high: float, stop: float, price: float,
               take: Optional[float] = None) -> str:
    """Waar de koers staat ten opzichte van een nog niet gevulde setup:
    wacht (nog buiten de zone, aan de kant waar de order wacht), in_zone (de order is waarschijnlijk geraakt),
    door_zone (voorbij de zone maar nog niet de stop), ongeldig (voorbij de stop, het plan is vervallen),
    doel_geraakt (met `take`: de koers is het doel al voorbij zonder de zone te raken, dus er valt niets meer te wachten;
    binnen of voorbij de zone blijft de order mogelijk gevuld, dan geldt dit niet)."""
    if direction == "long":
        if price <= stop:
            return "ongeldig"
        if price > zone_high:
            return "doel_geraakt" if take is not None and price >= take else "wacht"
        return "in_zone" if price >= zone_low else "door_zone"
    if price >= stop:
        return "ongeldig"
    if price < zone_low:
        return "doel_geraakt" if take is not None and price <= take else "wacht"
    return "in_zone" if price <= zone_high else "door_zone"


STATE_LABELS = {
    "wacht": "Wacht op de zone",
    "in_zone": "In de zone: je order is waarschijnlijk geraakt",
    "door_zone": "Koers is door de zone heen",
    "ongeldig": "Plan vervallen, de stop is geraakt",
    "doel_geraakt": "Doel gehaald zonder dat jouw order vulde",
}


def distance_to_limit_pct(plan: TradePlan, price: float) -> float:
    """Procent dat de koers nog van de limietprijs afstaat (positief = moet nog naar de order toe)."""
    return (price - plan.limit) / plan.limit * 100 if plan.direction == "long" else (plan.limit - price) / plan.limit * 100


def live_r(direction: str, entry: float, stop: float, price: float) -> Optional[float]:
    """Huidig resultaat in R voor een open trade; 1R is de afstand van entry tot stop."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return (price - entry) / risk if direction == "long" else (entry - price) / risk


LABEL_GAP = 13
LABEL_CHAR_W = 6.3
ZONE_MIN_PX = 6


def _fmt(value: float) -> str:
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def ladder_svg(direction: str, stop: float, take: float, limit: float, price: Optional[float] = None,
               zone_low: Optional[float] = None, zone_high: Optional[float] = None, entry: Optional[float] = None,
               width: int = 280, height: int = 190) -> str:
    """Prijsladder: doel boven, stop onder (voor een short omgekeerd, de hoogste prijs staat altijd bovenaan), met de
    zone als vlak, de limietprijs (of de werkelijke entry), en de huidige koers als markering. Waarden staan als tekst
    in de SVG zodat ze ook zonder styling leesbaar zijn."""
    # De schaal loopt over stop..doel (plus zone/entry), nooit over een verre koers: die krijgt een pijl net voorbij de
    # eindlijn. Daardoor blijft de ladder compact, ook als de koers ver voorbij doel of stop staat.
    levels = [stop, take, limit] + [v for v in (zone_low, zone_high, entry) if v is not None]
    lo, hi = min(levels), max(levels)
    price_text = None
    if price is not None:
        if price > hi:
            price_text = f"Nu {_fmt(price)} \u2191"
        elif price < lo:
            price_text = f"Nu {_fmt(price)} \u2193"
        else:
            price_text = f"Nu {_fmt(price)}"
    marks = [("take", take, "Doel"), ("stop", stop, "Stop")]
    marks.append(("entry", entry, "Entry") if entry is not None else ("limit", limit, "Limiet"))
    texts = [f"{label} {_fmt(value)}" for _, value, label in marks] + ([price_text] if price_text else [])
    # Labelkolom naar de breedste tekst (monospace, ~0.63 em per teken), zodat niets wordt afgekapt; de lijnen worden
    # korter en pas als die te kort worden groeit de viewBox mee.
    label_col = 8 + math.ceil(max(len(t) for t in texts) * LABEL_CHAR_W) + 6
    width = max(width, label_col + 110)
    top, bottom, left = 8, height - 8, 12
    line_x1, line_x2 = left, width - label_col
    end_pad, marker_off = 14, 10
    span = hi - lo or 1.0
    scale = ((bottom - end_pad) - (top + end_pad)) / span

    def y(value: float) -> float:
        return top + end_pad + (hi - value) * scale

    parts = [f'<svg class="trade-ladder" viewBox="0 0 {width} {height}" role="img" aria-label="Prijsladder van het handelsplan">']
    zone_title = ""
    if zone_low is not None and zone_high is not None:
        zone_h = y(zone_low) - y(zone_high)
        zone_title = f"Zone {_fmt(zone_low)} tot {_fmt(zone_high)}"
        if zone_h >= ZONE_MIN_PX:
            parts.append(f'<rect class="ladder-zone" x="{left}" y="{y(zone_high):.1f}" width="{line_x2 - left}" '
                         f'height="{zone_h:.1f}"><title>{zone_title}</title></rect>')
            zone_title = ""
    labels = [{"css": css, "y": y(value), "text": f"{label} {_fmt(value)}"} for css, value, label in marks]
    for css, value, _ in marks:
        title = f"<title>{zone_title}</title>" if zone_title and css in ("limit", "entry") else ""
        parts.append(f'<line class="ladder-line ladder-{css}" x1="{line_x1}" x2="{line_x2}" y1="{y(value):.1f}" y2="{y(value):.1f}">{title}</line>')
    if price is not None:
        ypos = y(price)
        if price > hi:
            ypos = y(hi) - marker_off
        elif price < lo:
            ypos = y(lo) + marker_off
        parts.append(f'<g class="ladder-price"><line x1="{line_x1}" x2="{line_x2}" y1="{ypos:.1f}" y2="{ypos:.1f}"/>'
                     f'<circle cx="{line_x2}" cy="{ypos:.1f}" r="4"/></g>')
        labels.append({"css": "price", "y": ypos, "text": price_text})
    # Labels die dichtbij elkaar liggen schuiven uit elkaar, de lijnen blijven op hun echte prijs staan.
    labels.sort(key=lambda item: item["y"])
    for i in range(1, len(labels)):
        labels[i]["y"] = max(labels[i]["y"], labels[i - 1]["y"] + LABEL_GAP)
    for i in range(len(labels) - 1, -1, -1):
        labels[i]["y"] = min(labels[i]["y"], bottom + 6 - (len(labels) - 1 - i) * LABEL_GAP)
    for item in labels:
        parts.append(f'<text class="ladder-label ladder-{item["css"]}" x="{line_x2 + 8}" y="{item["y"] + 4:.1f}">{escape(item["text"])}</text>')
    parts.append("</svg>")
    return "".join(parts)
