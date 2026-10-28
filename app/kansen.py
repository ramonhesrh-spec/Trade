"""De pagina Kansen (/smc, ontwerp V4): een tab per soort met de kansen als compacte kaart (coin en richting, stand, grafiek) en een detailblad
per kaart. Pure functies zonder database of netwerk: de route geeft de Radar-kaarten (radar.setup_card en radar.signal_card), de klaarstaande
Structuur-plannen met hun koers en stand, en de open Structuur-trades mee. Elk getal komt van die kaarten; hier wordt alleen gesorteerd en geteld.

Volgorde binnen een tab: in de zone eerst, dan op gemeten afstand tot de limiet, zonder koers achteraan. De tab met de meeste kansen in de zone
gaat open, anders Structuur."""
from typing import Iterable, Optional

from app import nu, radar, trade_plan as tp

LABELS = {"structuur": "Structuur", "zone_radar": "Zone-radar", "zone_sweep": "Zone-sweep", "smc": "SMC"}
ORDER = ("structuur", "zone_radar", "zone_sweep", "smc")
# Naar buiten is elke structuurkans Structuur (CLAUDE.md, Structuur zonder oordeel): structuur_c staat in dezelfde tab.
TAB_OF = {"structuur": "structuur", "structuur_c": "structuur", "zone_radar": "zone_radar", "zone_sweep": "zone_sweep", "smc": "smc"}
DEFAULT_TAB = "structuur"


def say(state: Optional[str], direction: str) -> str:
    """De zin in het detailblad, alleen voor een plan dat nog niet vulde. De getallen staan in de tabel eronder en worden niet herhaald."""
    if state == "open":
        return ""
    if state == "in_zone":
        return f"De koers staat in de zone: je limit {direction} op de instap is waarschijnlijk gevuld. Houd stop en doel aan."
    return f"Wacht tot de koers de zone bereikt. Zet dan een limit {direction} op de instap, met de stop en het doel uit de tabel."


def _plan(item: dict, dom_id: str) -> dict:
    state = item["state"]
    # In de zone geen groot getal: de stand staat al als pil en in de zin erboven, drie keer "In zone" was ruis.
    if item.get("distance_pct") is not None and item["distance_pct"] > 0:
        num = (item["distance_text"], "distance", "tot de instap")
    else:
        num = ("", "distance", "")
    return {**item, "dom_id": dom_id, "title": f"{item['coin']} {item['direction']}", "tab": TAB_OF.get(item["trade_type"], item["trade_type"]),
            "state_short": tp.STATE_SHORT.get(state, "Geen koers") if state else "Geen koers", "say": say(state, item["direction"]),
            "num_text": num[0], "num_hook": num[1], "num_label": num[2]}


def _trade(item: dict) -> dict:
    return {**item, "dom_id": "radar-" + item["key"].replace(":", "-"), "title": f"{item['coin']} {item['direction']}", "state": "open",
            "tab": TAB_OF.get(item["trade_type"], item["trade_type"]), "state_short": "Open", "say": "",
            "num_text": item["live_r_text"] or "", "num_hook": "live_r", "num_label": "nu, live" if item["live_r_text"] else ""}


def structure_item(card: dict, price: Optional[float], state: Optional[str]) -> dict:
    """Een klaarstaand Structuur-plan (web.main._structure_cards) met de kaartgrafiek van de andere soorten: limiet op het retest-niveau, het
    eerste doel als doel op de grafiek (de andere staan in de tabel van het blad)."""
    item = nu.structure_item(card, price, state)
    chart = tp.chart_spec(card["direction"], card["plan"]["stop"], card["targets"][0][0] if card["targets"] else None, card["plan"]["level"], price)
    return _plan({**item, "chart": chart, "origin": "Structuur · breuk van een lijn of range op 30m"}, f"structuur-{card['id']}")


def _sort_key(item: dict):
    d = item.get("distance_pct")
    return (item.get("skipped", False), item["state"] != "in_zone", d is None, d if d is not None else 0.0)


def _summary(n: int, in_zone: int, trades: int) -> str:
    if not n and not trades:
        return "Geen kansen"
    parts = [f"{n} {'kans' if n == 1 else 'kansen'}", f"{in_zone} in de zone"]
    if trades:
        parts.append(f"{trades} open")
    return " · ".join(parts)


def page(radar_cards: list[dict], structure: Iterable[tuple[dict, Optional[float], Optional[str]]], structure_trades: list[dict],
         kinds: Iterable[str], skipped: Iterable[str] = ()) -> dict:
    """`kinds`: de soorten die een tab krijgen (focus.FOCUS_TYPES met de kijkrechten van de route). Een kaart van een andere soort valt weg.
    `skipped`: plannen die je oversloeg (cookie en plan_skips, een dag); die blijven staan, achteraan en gemarkeerd."""
    wanted = set(kinds)
    plans = [structure_item(card, price, state) for card, price, state in structure]
    plans += [_plan(nu._from_setup(c), "radar-" + c["key"].replace(":", "-")) for c in radar.waiting_cards(radar_cards)]
    skipped = set(skipped)
    for p in plans:
        p["skipped"] = p["key"] in skipped
    trades = [_trade(nu._from_signal(c)) for c in radar_cards + structure_trades if c and c["kind"] == "signal"]
    # Een open trade blijft staan, ook als zijn soort geen nieuwe kansen meer zoekt (focus): dan krijgt die soort toch een tab.
    kinds = [k for k in ORDER if k in set(kinds) or any(t["tab"] == k for t in trades)]
    tabs = []
    for k in kinds:
        mine = sorted((p for p in plans if p["tab"] == k and k in wanted), key=_sort_key)
        open_ = sorted((t for t in trades if t["tab"] == k), key=lambda t: t["created_at"], reverse=True)
        zone = sum(1 for p in mine if p["state"] == "in_zone")
        moot = [{"title": f"{c['coin']} {c['direction']}", "label": c["state_label"], "dom_id": "radar-" + c["key"].replace(":", "-")}
                for c in radar.moot_cards(radar_cards) if TAB_OF.get(c["setup"].get("source") or "smc") == k and k in wanted]
        tabs.append({"key": k, "label": LABELS[k], "href": f"#tab-{k}", "plans": mine, "trades": open_, "n": len(mine), "in_zone": zone,
                     "count": zone or None, "summary": _summary(len(mine), zone, len(open_)), "moot": moot})
    best = max(tabs, key=lambda t: t["in_zone"], default=None)
    active = best["key"] if best and best["in_zone"] else (DEFAULT_TAB if DEFAULT_TAB in kinds else (kinds[0] if kinds else DEFAULT_TAB))
    return {"tabs": tabs, "active": active, "in_zone": sum(t["in_zone"] for t in tabs)}
