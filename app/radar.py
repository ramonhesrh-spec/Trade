"""Kaarten voor de Trade Radar: elke bouwende SMC-setup en elk open SMC-signaal als handelsplan met candlegrafiek, status
en afstand tot de limietorder. Pure functies zonder database of netwerk; de route haalt setups, signalen en koersen op en
geeft ze hier door. Dezelfde kaarten voeden de eerste paginaweergave en de live-verversing (/api/radar)."""
from typing import Optional

from app import chance_steps, trade_plan as tp


def setup_card(setup: dict, price: Optional[float]) -> Optional[dict]:
    """None als stop of doel niet aan de juiste kant van de limietprijs liggen: zo'n setup kan nooit een signaal worden."""
    plan = tp.limit_plan(setup["direction"], setup["zone_low"], setup["zone_high"],
                         setup["preview_stop_loss"], setup["preview_take_profit"])
    if plan is None:
        return None
    state = setup_state(setup, price)
    moot = state == "doel_geraakt"
    distance = tp.distance_to_limit_pct(plan, price) if price and not moot else None
    # Bij een ongeldig plan (koers voorbij de stop) is de afstand tot de instap negatief en zou de balk "vol" tonen terwijl de kaart zegt dat het plan vervalt.
    approach = None if state == "ongeldig" else tp.approach_pct(distance)
    # Een moot plan krijgt geen grafiek en geen stappen: er is niets meer te doen, alleen de uitkomst blijft staan.
    return {
        "key": f"setup:{setup['id']}", "kind": "setup", "coin": setup["coin"], "direction": setup["direction"],
        "plan": plan, "price": price, "state": state, "state_label": tp.STATE_LABELS.get(state, "Koers wordt opgehaald"),
        "distance_pct": distance, "approach_pct": approach, "live_r": None,
        "chart": None if moot else tp.chart_spec(setup["direction"], plan.stop, plan.take, plan.limit, price, setup["zone_low"], setup["zone_high"]),
        "created_at": setup["created_at"], "setup": setup,
        "steps": [] if moot else chance_steps.smc_steps(plan, setup["zone_low"], setup["zone_high"], price, distance, setup["coin"]),
        "levels": [] if moot else chance_steps.level_chips(plan.limit, plan.stop, plan.take),
    }


def setup_state(setup: dict, price: Optional[float]) -> Optional[str]:
    return tp.plan_state(setup["direction"], setup["zone_low"], setup["zone_high"], setup["preview_stop_loss"], price,
                         take=setup["preview_take_profit"]) if price else None


def waiting_cards(cards: list[dict]) -> list[dict]:
    return [c for c in cards if c["kind"] == "setup" and c["state"] != "doel_geraakt"]


def moot_cards(cards: list[dict]) -> list[dict]:
    return [c for c in cards if c["kind"] == "setup" and c["state"] == "doel_geraakt"]


def waiting_count(setups: list[dict], prices: dict) -> int:
    """Aantal bouwende setups voor het menu-getal; een setup waarvan het doel al gehaald is zonder dat de order vulde wacht op niets."""
    return sum(1 for s in setups if setup_state(s, prices.get(s["coin"])) != "doel_geraakt")


def in_zone_count(setups: list[dict], prices: dict) -> int:
    """Bouwende setups waarvan de koers nu in de zone staat, voor het getal op het appicoon. Zonder koers telt een setup niet mee:
    het icoon zou anders iets beloven wat niet gemeten is."""
    return sum(1 for s in setups if setup_state(s, prices.get(s["coin"])) == "in_zone")


def signal_card(signal: dict, price: Optional[float]) -> Optional[dict]:
    """Een open SMC-signaal: de grafiek toont de werkelijke entry, het resultaat loopt live mee in R."""
    entry, stop, take = signal["price"], signal["stop_loss"], signal["take_profit"]
    if not entry or not stop or not take:
        return None
    r = tp.live_r(signal["direction"], entry, stop, price) if price else None
    return {
        "key": f"signal:{signal['id']}", "kind": "signal", "coin": signal["coin"], "direction": signal["direction"],
        "plan": None, "price": price, "state": "open", "state_label": "Open trade",
        "distance_pct": None, "approach_pct": None, "live_r": r,
        "chart": tp.chart_spec(signal["direction"], stop, take, entry, price, entry=entry),
        "created_at": signal["created_at"], "signal": signal,
        "rr": abs(take - entry) / abs(entry - stop),
        "levels": chance_steps.level_chips(entry, stop, take),
    }


def live_payload(cards: list[dict]) -> dict:
    """Wat de browser elke paar seconden ververst: status, afstand, live R en de niveaus voor de grafiek per kaart (getallen, zie trade_plan.chart_spec; None bij een moot plan)."""
    return {
        c["key"]: {
            "state": c["state"], "label": c["state_label"], "price": c["price"],
            "distance_pct": c["distance_pct"], "approach_pct": c["approach_pct"], "live_r": c["live_r"], "chart": c["chart"],
        }
        for c in cards
    }


SPARK_HOURS = 24


def spark_path(closes: list[float], width: float = 120, height: float = 28) -> str:
    """SVG-pad van de slotkoersen (oudste eerst) in een vak van width bij height, met 2px marge. Leeg onder twee punten."""
    if len(closes) < 2:
        return ""
    pad = 2.0
    lo, hi = min(closes), max(closes)
    step = (width - 2 * pad) / (len(closes) - 1)

    def y(v: float) -> float:
        return height / 2 if hi == lo else pad + (hi - v) / (hi - lo) * (height - 2 * pad)

    return "M" + " L".join(f"{pad + i * step:.1f},{y(v):.1f}" for i, v in enumerate(closes))


def spark(closes: list[float]) -> Optional[dict]:
    """Wat spark.js per coin invult: het pad en de verandering over de periode."""
    if len(closes) < 2 or not closes[0]:
        return None
    change = (closes[-1] - closes[0]) / closes[0] * 100
    return {"path": spark_path(closes), "change_pct": change, "change_text": f"{change:+.1f}".replace(".", ",") + "% 24u"}
