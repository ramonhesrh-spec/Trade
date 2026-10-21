"""Eén vorm voor elke kans die nog niet gevuld is: drie stappen met wat je nu doet. Pure functies, de templates tekenen alleen
(macros.steps_list). Structuur, SMC en het markt-script gebruiken dezelfde stappen en dezelfde woorden."""
import json
import math
from typing import Optional

from app import trade_plan

DIST_KEYS = {"vandaag": "data-vd", "radar": "data-radar"}


def fmt(value: float) -> str:
    """0,0957 en 2717,08: vijf cijfers onder de 1 (ook voor kleine munten), vier decimalen onder 100, twee erboven."""
    if abs(value) < 1:
        if value == 0:
            return "0"
        # Vast puntje en nooit 1.23e-05: dit komt in orderveldjes terecht.
        decimals = 4 - math.floor(math.log10(abs(value)))
        return f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def plan_steps(wait_title: str, limit: float, stop: float, take_text: str, risk_pct: float, rr: float, *, state: str = "waiting",
               distance_pct: Optional[float] = None, page: str = "vandaag", live: Optional[tuple[str, float, str]] = None) -> list[dict]:
    """state: 'waiting' (stap 1 is aan de beurt), 'fired' of 'filled' (stap 2 is aan de beurt), anders alles gedempt.
    distance_pct: hoe ver de koers nog van stap 1 is, voor de live verversing van de pagina."""
    now = 1 if state == "waiting" else 2 if state in ("fired", "filled") else 0
    dist = None if distance_pct is None else f"{distance_pct:+.2f}%"
    first = {"title": wait_title, "sub": "te gaan", "dist": dist if dist is not None else "-", "dist_key": DIST_KEYS[page],
             "state": "now" if now == 1 else "done"}
    if live:
        # De browser rekent de afstand zelf uit bij elke koers van de beurs: (niveau - koers) / koers, of een van de varianten voor de radar.
        first["live_coin"], first["live_level"], first["live_mode"] = live
    return [
        first,
        {"title": f"Zet een limietorder op {fmt(limit)}", "state": "now" if now == 2 else "next"},
        {"title": f"Stop {fmt(stop)}, {take_text}", "state": "next",
         "sub": f"De stop ligt {risk_pct:.2f}% van je instap. Het doel levert {rr:.1f} keer wat je riskeert.", "rr": rr},
    ]


def structure_steps(plan: dict, targets: list[tuple[float, float]], price: Optional[float], direction: str, coin: str = "") -> list[dict]:
    level = plan["level"]
    risk_pct = plan["risk_pct"]
    rr = targets[1][1] if len(targets) > 1 else targets[0][1]
    wait = f"Wacht tot de koers terugkeert naar {fmt(level)}"
    dist = (level - price) / price * 100 if price else None
    texts = ", ".join(f"{fmt(t)} ({r:.1f}R)" for t, r in targets)
    steps = plan_steps(wait, level, plan["stop"], f"doelen {texts}", risk_pct, rr, distance_pct=dist, page="vandaag",
                       live=(coin, level, "lp") if coin else None)
    # Het teken van dist is hier de richting van de koers, niet hoe ver je nog moet: de balk kijkt alleen naar de afstand.
    steps[0]["approach"] = trade_plan.approach_pct(None if dist is None else abs(dist))
    return steps


def smc_steps(plan, zone_low: float, zone_high: float, price: Optional[float], distance_pct: Optional[float], coin: str = "") -> list[dict]:
    wait = f"Wacht tot de koers in de zone {fmt(zone_low)} tot {fmt(zone_high)} komt"
    return plan_steps(wait, plan.limit, plan.stop, f"doel {fmt(plan.take)}", plan.risk_pct, plan.rr, distance_pct=distance_pct, page="radar",
                      live=(coin, plan.limit, "pl" if plan.direction == "long" else "ll") if coin else None)


def script_steps(sc: dict) -> list[dict]:
    state = "waiting" if sc["state"] == "waiting" else "fired" if sc["state"] == "fired" else "other"
    return plan_steps(f"Wacht tot: {sc['trigger']}", sc["entry"], sc["stop"], f"doel {fmt(sc['take'])}", sc["risk_pct"], sc["rr"],
                      state=state, distance_pct=sc["to_trigger_pct"], page="vandaag",
                      live=(sc["coin"], sc["trigger_level"], "lp") if state == "waiting" and sc.get("coin") else None)


def now_line(state: Optional[str], direction: str, entry: float, stop: float, take: Optional[float] = None, *,
             wait_for: Optional[str] = None) -> str:
    """Eén zin bovenaan een kaart: wat je nu doet, in gewone woorden. `state` is een radarstand (wacht, in_zone, door_zone, ongeldig,
    doel_geraakt), 'open' voor een lopende trade, of 'fired'/'vervallen' voor een scenario; None (nog geen koers) leest als wacht.
    `wait_for` vervangt het instapniveau in de wachtzin (de voorwaarde van een scenario)."""
    levels = f"stop {fmt(stop)}" + (f", doel {fmt(take)}" if take is not None else "")
    order = f"limit {direction} op {fmt(entry)}, {levels}"
    if state == "open":
        return f"Trade loopt. {levels[0].upper()}{levels[1:]}."
    if state == "fired":
        return f"De voorwaarde is geraakt. Zet nu een {order}."
    if state == "in_zone":
        return f"De koers staat in de zone: je limit {direction} op {fmt(entry)} is waarschijnlijk gevuld. Houd {levels} aan."
    if state == "door_zone":
        return f"De koers ging door de zone heen. Is je limit gevuld, houd dan {levels} aan."
    if state == "ongeldig":
        return f"Plan vervallen: de koers raakte de stop. Haal je limit op {fmt(entry)} weg als die nog openstaat."
    if state == "doel_geraakt":
        return f"Het doel is gehaald zonder dat je limit vulde. Haal je limit op {fmt(entry)} weg."
    if state == "vervallen":
        return "Dit scenario is voorbij. Er is niets meer te doen."
    wait = f"Wacht tot {wait_for}." if wait_for else f"Wacht tot de koers {fmt(entry)} bereikt."
    return f"{wait} Zet dan een {order}."


def level_chips(entry: float, stop: float, take: Optional[float]) -> list[dict]:
    """Instap, stop en doel als losse getallen voor de tik-om-te-kopiëren-knoppen. Zelfde notatie als in de stappen, met een punt als
    decimaalteken, want dat accepteert elk orderveld van een beurs. Zonder doel (meelopende stop) alleen instap en stop."""
    return [{"key": key, "label": label, "value": value, "text": fmt(value)}
            for key, label, value in (("entry", "Instap", entry), ("stop", "Stop", stop), ("take", "Doel", take)) if value is not None]


FAMILY_WORD = {"zone": "de zone", "sweep": "het order block"}


def range_legs(row: dict) -> list[tuple[float, float]]:
    return [(float(w), float(p)) for w, p in json.loads(row["legs"])]


def range_distance_pct(row: dict, price: Optional[float]) -> Optional[float]:
    """Hoe ver de koers nog is van de eerste limiet die hij raakt: bij een short de laagste, bij een long de hoogste."""
    if not price:
        return None
    prices = [p for _, p in range_legs(row)]
    nearest = min(prices) if row["direction"] == "short" else max(prices)
    return (nearest - price) / price * 100


def range_sweep_steps(row: dict, price: Optional[float], coin: str) -> list[dict]:
    """Zelfde drie stappen als elke kans, maar stap drie heeft geen doel: HesPulse levert de stop, het doel kies je zelf; midden en overkant
    van de range staan erbij als referentie, niet als advies."""
    legs = range_legs(row)
    short = row["direction"] == "short"
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    nearest = min(p for _, p in legs) if short else max(p for _, p in legs)
    dist = range_distance_pct(row, price)
    mid, opp = (row["range_high"] + row["range_low"]) / 2, row["range_low"] if short else row["range_high"]
    first = {"title": f"Wacht tot de koers terugkeert in {FAMILY_WORD[row['family']]} bij {fmt(nearest)}", "sub": "te gaan",
             "dist": f"{dist:+.2f}%" if dist is not None else "-", "dist_key": DIST_KEYS["vandaag"], "state": "now",
             "approach": trade_plan.approach_pct(None if dist is None else abs(dist))}
    if coin:
        first["live_coin"], first["live_level"], first["live_mode"] = coin, nearest, "lp"
    if len(legs) > 1:
        second = "Zet limietorders: " + " en ".join(f"{w * 100:.0f}% op {fmt(p)}" for w, p in legs)
    else:
        second = f"Zet een limietorder op {fmt(legs[0][1])}"
    return [first,
            {"title": second, "state": "next"},
            {"title": f"Stop {fmt(row['stop'])}, doel kies je zelf", "state": "next",
             "sub": f"De stop ligt {abs(planned - row['stop']) / planned * 100:.2f}% van je instap, voorbij de zone. Referentie, geen doel: Midden {fmt(mid)} · Overkant {fmt(opp)}."}]


def range_chips(legs, stop: float, mid: float, opp: float) -> list[dict]:
    names = ["Limiet"] if len(legs) == 1 else [f"Limiet {w * 100:.0f}%" for w, _ in legs]
    items = [(f"limit{k}", n, p) for k, (n, (_, p)) in enumerate(zip(names, legs), 1)]
    items += [("stop", "Stop", stop), ("mid", "Midden (ref.)", mid), ("opp", "Overkant (ref.)", opp)]
    return [{"key": key, "label": label, "value": value, "text": fmt(value)} for key, label, value in items]
