"""Kaarten voor de Trade Radar: elke bouwende SMC-setup en elk open SMC-signaal als handelsplan met prijsladder, status
en afstand tot de limietorder. Pure functies zonder database of netwerk; de route haalt setups, signalen en koersen op en
geeft ze hier door. Dezelfde kaarten voeden de eerste paginaweergave en de live-verversing (/api/radar)."""
from typing import Optional

from markupsafe import Markup

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
    # Een moot plan krijgt geen ladder en geen stappen: er is niets meer te doen, alleen de uitkomst blijft staan.
    return {
        "key": f"setup:{setup['id']}", "kind": "setup", "coin": setup["coin"], "direction": setup["direction"],
        "plan": plan, "price": price, "state": state, "state_label": tp.STATE_LABELS.get(state, "Koers wordt opgehaald"),
        "distance_pct": distance, "live_r": None,
        "ladder": Markup("" if moot else tp.ladder_svg(setup["direction"], plan.stop, plan.take, plan.limit, price, setup["zone_low"], setup["zone_high"])),
        "created_at": setup["created_at"], "setup": setup,
        "steps": [] if moot else chance_steps.smc_steps(plan, setup["zone_low"], setup["zone_high"], price, distance, setup["coin"]),
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


def signal_card(signal: dict, price: Optional[float]) -> Optional[dict]:
    """Een open SMC-signaal: de ladder toont de werkelijke entry, het resultaat loopt live mee in R."""
    entry, stop, take = signal["price"], signal["stop_loss"], signal["take_profit"]
    if not entry or not stop or not take:
        return None
    r = tp.live_r(signal["direction"], entry, stop, price) if price else None
    return {
        "key": f"signal:{signal['id']}", "kind": "signal", "coin": signal["coin"], "direction": signal["direction"],
        "plan": None, "price": price, "state": "open", "state_label": "Open trade",
        "distance_pct": None, "live_r": r,
        "ladder": Markup(tp.ladder_svg(signal["direction"], stop, take, entry, price, entry=entry)),
        "created_at": signal["created_at"], "signal": signal,
        "rr": abs(take - entry) / abs(entry - stop),
    }


def live_payload(cards: list[dict]) -> dict:
    """Wat de browser elke paar seconden ververst: status, afstand, live R en de nieuwe ladder per kaart."""
    return {
        c["key"]: {
            "state": c["state"], "label": c["state_label"], "price": c["price"],
            "distance_pct": c["distance_pct"], "live_r": c["live_r"], "ladder": str(c["ladder"]),
        }
        for c in cards
    }
