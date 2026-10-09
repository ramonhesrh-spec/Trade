"""Handelsplan van een SMC-setup voor iemand die met een limietorder op de zone instapt: waar de order staat, wat de
R:R vanaf die prijs is, waar de koers nu staat ten opzichte van het plan, en een strook met R:R voor in de
pagina. Alleen rekenen en tekenen, geen database en geen netwerk, zodat live melding, pagina en tests dezelfde
cijfers gebruiken."""
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


def _fmt(value: float) -> str:
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def _nl(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


# Een zone smaller dan dit deel van de balk is niet te zien en zou alleen als extra streep op de instap staan.
MIN_ZONE_SHARE = 0.03


def strip_html(direction: str, stop: float, take: float, limit: float, price: Optional[float] = None,
               zone_low: Optional[float] = None, zone_high: Optional[float] = None, entry: Optional[float] = None) -> str:
    """Strook met R:R: een balk van stop (links) via instap naar doel (rechts), voor long en short in dezelfde volgorde,
    plus drie vakken met de volledige prijzen en een regel risico en doel in R. De balk loopt alleen van stop tot doel:
    de koers is een stip die aan de rand blijft staan als hij erbuiten valt (met een label), zodat een ver weg staande koers
    de schaal nooit uitrekt. Staat de instap niet tussen stop en doel, dan blijven alleen de vakken over. Waarden staan als
    tekst in de markup en in het aria-label."""
    instap = entry if entry is not None else limit
    label = "Entry" if entry is not None else "Limiet"
    span = take - stop
    pos_instap = (instap - stop) / span * 100 if span else -1.0
    risk, reward = abs(instap - stop), abs(take - instap)
    has_bar = span != 0 and 0 < pos_instap < 100 and risk > 0 and reward > 0

    nu_text = f"Nu {_fmt(price)}" if price is not None else ""
    if price is not None and entry is not None and entry != stop:
        nu_text += f"  ·  {live_r(direction, entry, stop, price):+.1f}R".replace(".", ",")
    aria = f"Stop {_fmt(stop)}, instap {_fmt(instap)} ({label.lower()}), doel {_fmt(take)}"
    if price is not None:
        aria += f", koers {_fmt(price)}"
    risk_line = ""
    if has_bar:
        rr_text = f"Risico {_nl(risk / instap * 100, 2)}%  ·  Doel {_nl(reward / risk, 1)}R"
        risk_line = f'<p class="strip-line">{rr_text}</p>'
        aria += f". {rr_text}"

    bar = ""
    if has_bar:
        zone = ""
        if zone_low is not None and zone_high is not None:
            a, b = sorted(((zone_low - stop) / span * 100, (zone_high - stop) / span * 100))
            a, b = max(0.0, a), min(100.0, b)
            if b - a >= MIN_ZONE_SHARE * 100:
                zone = (f'<span class="strip-zone" style="left:{a:.1f}%;width:{b - a:.1f}%" '
                        f'title="Zone {_fmt(zone_low)} tot {_fmt(zone_high)}"></span>')
        dot = ""
        now = ""
        dot_pos = None
        if price is not None:
            raw = (price - stop) / span * 100
            dot_pos = min(100.0, max(0.0, raw))
            tag = "voorbij doel" if raw > 100 else "voorbij stop" if raw < 0 else ""
            dot = f'<span class="strip-dot" data-strip="dot" style="left:{dot_pos:.1f}%"></span>'
            now = (f'<span class="strip-now" data-strip="now" style="left:{dot_pos:.1f}%;--p:{dot_pos:.1f}%">'
                   f'{escape(nu_text)}{f" <em>{tag}</em>" if tag else ""}</span>')
        bar = (f'<div class="strip-track">{now}<div class="strip-bar"><span class="strip-risk" style="width:{pos_instap:.1f}%"></span>'
               f'<span class="strip-reward" style="left:{pos_instap:.1f}%"></span>{zone}'
               f'<span class="strip-tick" style="left:{pos_instap:.1f}%"></span>{dot}</div></div>')
    elif price is not None:
        risk_line = f'<p class="strip-line">{escape(nu_text)}</p>'

    def box(css: str, title: str, value: float, sub: str) -> str:
        return (f'<div class="strip-box strip-box-{css}"><span class="strip-title">{title}</span>'
                f'<span class="strip-price">{_fmt(value)}</span><span class="strip-sub">{sub}</span></div>')

    stop_sub = "−1R" if has_bar else "stop"
    take_sub = f"+{_nl(reward / risk, 1)}R" if has_bar else "doel"
    boxes = (box("stop", "Stop", stop, stop_sub) + box("instap", "Instap", instap, label.lower())
             + box("take", "Doel", take, take_sub))
    key = f"{_fmt(stop)}|{_fmt(instap)}|{_fmt(take)}"
    share = ""
    if has_bar:
        share = (f' data-bar="1" data-instap-pos="{pos_instap:.1f}" data-label="{label.lower()}"'
                 + (f' data-dot="{dot_pos:.1f}" data-now="{escape(nu_text)}"' if price is not None else ""))
    return (f'<div class="trade-strip" role="img" aria-label="{escape(aria)}" data-strip-key="{key}" data-stop="{_fmt(stop)}" '
            f'data-instap="{_fmt(instap)}" data-take="{_fmt(take)}"{share}>{bar}<div class="strip-boxes">{boxes}</div>{risk_line}</div>')
