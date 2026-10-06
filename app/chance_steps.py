"""Eén vorm voor elke kans die nog niet gevuld is: drie stappen met wat je nu doet. Pure functies, de templates tekenen alleen
(macros.steps_list). Structuur, SMC en het markt-script gebruiken dezelfde stappen en dezelfde woorden."""
from typing import Optional

DIST_KEYS = {"vandaag": "data-vd", "radar": "data-radar"}


def fmt(value: float) -> str:
    """0,0957 en 2717,08: vijf cijfers onder de 1 (ook voor kleine munten), vier decimalen onder 100, twee erboven."""
    if abs(value) < 1:
        return f"{value:.5g}"
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def plan_steps(wait_title: str, limit: float, stop: float, take_text: str, risk_pct: float, rr: float, *, state: str = "waiting",
               distance_pct: Optional[float] = None, page: str = "vandaag") -> list[dict]:
    """state: 'waiting' (stap 1 is aan de beurt), 'fired' of 'filled' (stap 2 is aan de beurt), anders alles gedempt.
    distance_pct: hoe ver de koers nog van stap 1 is, voor de live verversing van de pagina."""
    now = 1 if state == "waiting" else 2 if state in ("fired", "filled") else 0
    dist = None if distance_pct is None else f"{distance_pct:+.2f}%"
    return [
        {"title": wait_title, "sub": "te gaan", "dist": dist if dist is not None else "-", "dist_key": DIST_KEYS[page],
         "state": "now" if now == 1 else "done"},
        {"title": f"Zet een limietorder op {fmt(limit)}", "state": "now" if now == 2 else "next"},
        {"title": f"Stop {fmt(stop)}, {take_text}", "state": "next",
         "sub": f"De stop ligt {risk_pct:.2f}% van je instap. Het doel levert {rr:.1f} keer wat je riskeert.", "rr": rr},
    ]


def structure_steps(plan: dict, targets: list[tuple[float, float]], price: Optional[float], direction: str) -> list[dict]:
    level = plan["level"]
    risk_pct = plan["risk_pct"]
    rr = targets[1][1] if len(targets) > 1 else targets[0][1]
    wait = f"Wacht tot de koers terugkeert naar {fmt(level)}"
    dist = (level - price) / price * 100 if price else None
    texts = ", ".join(f"{fmt(t)} ({r:.1f}R)" for t, r in targets)
    return plan_steps(wait, level, plan["stop"], f"doelen {texts}", risk_pct, rr, distance_pct=dist, page="vandaag")


def smc_steps(plan, zone_low: float, zone_high: float, price: Optional[float], distance_pct: Optional[float]) -> list[dict]:
    wait = f"Wacht tot de koers in de zone {fmt(zone_low)} tot {fmt(zone_high)} komt"
    return plan_steps(wait, plan.limit, plan.stop, f"doel {fmt(plan.take)}", plan.risk_pct, plan.rr, distance_pct=distance_pct, page="radar")


def script_steps(sc: dict) -> list[dict]:
    state = "waiting" if sc["state"] == "waiting" else "fired" if sc["state"] == "fired" else "other"
    return plan_steps(f"Wacht tot: {sc['trigger']}", sc["entry"], sc["stop"], f"doel {fmt(sc['take'])}", sc["risk_pct"], sc["rr"],
                      state=state, distance_pct=sc["to_trigger_pct"], page="vandaag")
