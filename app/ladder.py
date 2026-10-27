"""De prijsladder (ontwerp V3, docs/design/hespulse_v3.dc.html): de prijs rechtop, boven is duurder en onder goedkoper. Stop, instap, doel
en zone staan op hun echte plek, de koers is een lijn en de afstand tot de zone een balk. Pure maths zonder database of netwerk; de macro
`ladder` in web/templates/_macros.html tekent, web/static/ladder.js schuift de koers live met dezelfde formules (y_pct, distance_pct).

Posities zijn procenten van de ladderhoogte (0 = boven), zodat de hoogte in CSS mag meebewegen met het scherm. Er wordt niets geschat:
elke lijn is een getal uit het plan, de afstand is dezelfde meting als trade_plan.distance_to_limit_pct."""
from typing import Iterable, Optional

from app import chance_steps

MARGIN = 0.12        # boven en onder de buitenste lijn, als deel van de span: ruimte voor de tag boven de bovenste lijn
TAG_GAP = 7.0        # minimale afstand tussen twee tags in procent; bij 420px hoogte ongeveer 29px, genoeg voor een regel van 12px
NUM_EDGE = 10.0      # het grote getal blijft zo ver van boven- en onderrand
STALE_AFTER_S = 30   # het ontwerp schrapte "Bijgewerkt om"; pas een koers ouder dan dit krijgt een regel


def nl(value: float) -> str:
    """Dezelfde cijfers als chance_steps.fmt, met een komma (zoals nu.nl)."""
    return chance_steps.fmt(value).replace(".", ",")


def bounds(values: Iterable[Optional[float]], margin: float = MARGIN) -> tuple[float, float]:
    vals = [v for v in values if v is not None]
    if not vals:
        raise ValueError("geen niveaus")
    hi, lo = max(vals), min(vals)
    span = hi - lo or abs(hi) * 0.01 or 1.0
    return hi + span * margin, lo - span * margin


def y_pct(price: float, hi: float, lo: float) -> float:
    """Boven = 0, onder = 100. Buiten de schaal blijft de lijn op de rand staan in plaats van uit beeld te vallen."""
    return min(100.0, max(0.0, (hi - price) / (hi - lo) * 100))


def spread(ys: list[float], min_gap: float) -> list[float]:
    """Tagposities zonder overlap, in dezelfde volgorde: de lijn blijft op zijn prijs, alleen het label schuift."""
    if not ys:
        return []
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = [ys[i] for i in order]
    for k in range(1, len(pos)):
        pos[k] = max(pos[k], pos[k - 1] + min_gap)
    over = pos[-1] - 100.0
    if over > 0:                                   # onderaan geen plek meer: alles evenveel omhoog, maar nooit boven 0
        pos = [p - over for p in pos]
        for k in range(len(pos) - 2, -1, -1):
            pos[k] = min(pos[k], pos[k + 1] - min_gap)
        under = -pos[0]
        if under > 0:
            pos = [p + under for p in pos]
    out = [0.0] * len(ys)
    for k, i in enumerate(order):
        out[i] = pos[k]
    return out


def distance_pct(direction: str, limit: float, price: float) -> float:
    """trade_plan.distance_to_limit_pct zonder plan-object: positief = de koers moet nog naar de order toe."""
    return (price - limit) / limit * 100 if direction == "long" else (limit - price) / limit * 100


def stale_text(age_s: Optional[float]) -> str:
    if age_s is None or age_s <= STALE_AFTER_S:
        return ""
    if age_s < 120:
        return f"Koers {int(age_s)} s oud"
    if age_s < 3600:
        return f"Koers {int(age_s // 60)} min oud"
    return f"Koers {int(age_s // 3600)} u oud"


def build(direction: str, stop: float, entry: float, targets: list[tuple[float, float]], price: Optional[float],
          zone_low: Optional[float] = None, zone_high: Optional[float] = None, *, compact: bool = False, trade: bool = False,
          entry_label: str = "Instap") -> dict:
    """De ladder van één plan of trade. `compact` is de uitgezoomde variant voor rust en lijsten: alleen zone, instap en koers, zonder accent.
    `trade` is een gevulde order: geen zone en geen afstandsbalk meer, het getal wordt de live R (dat zet de template)."""
    zone = (zone_low, zone_high) if zone_low is not None and zone_high is not None and not trade else None
    many = len(targets) > 1
    lines = [] if compact else [{"name": "Stop", "tone": "loss", "value": stop}]
    lines.append({"name": entry_label, "tone": "entry", "value": entry})
    if not compact:
        lines += [{"name": f"Doel {i}" if many else "Doel", "tone": "win", "value": t, "r": r} for i, (t, r) in enumerate(targets, 1)]
    lines.sort(key=lambda ln: -ln["value"])
    hi, lo = bounds([ln["value"] for ln in lines] + list(zone or ()) + [price])
    for ln in lines:
        ln.update(y=y_pct(ln["value"], hi, lo), text=nl(ln["value"]), copy=chance_steps.fmt(ln["value"]))
    for ln, tag in zip(lines, spread([ln["y"] for ln in lines], TAG_GAP)):
        ln["tag_y"] = tag

    zone_box = None
    if zone:
        top, bottom = y_pct(max(zone), hi, lo), y_pct(min(zone), hi, lo)
        zone_box = {"low": min(zone), "high": max(zone), "top": top, "height": bottom - top}

    gap, in_zone, num_y, price_box = None, False, 50.0, None
    if price is not None:
        py = y_pct(price, hi, lo)
        price_box = {"value": price, "text": nl(price), "y": py}
        if zone:
            in_zone = min(zone) <= price <= max(zone)
            edge = max(zone) if price > max(zone) else min(zone) if price < min(zone) else price
        else:
            edge = entry
        if not trade:
            ey = y_pct(edge, hi, lo)
            gap = {"top": min(ey, py), "height": abs(py - ey)}
            num_y = gap["top"] + gap["height"] / 2
        else:
            num_y = (py + y_pct(entry, hi, lo)) / 2
    num_y = min(100 - NUM_EDGE, max(NUM_EDGE, num_y))
    if gap and gap["height"] > 2 * NUM_EDGE:
        num_y = min(max(num_y, gap["top"]), gap["top"] + gap["height"])
    return {"direction": direction, "hi": hi, "lo": lo, "lines": lines, "zone": zone_box, "price": price_box, "gap": gap,
            "in_zone": in_zone, "num_y": num_y, "compact": compact, "trade": trade, "entry": entry}
