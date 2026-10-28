"""De pagina Kansen (/smc, ontwerp V4): een tab per soort met de kansen als compacte kaart (coin en richting, stand, grafiek) en een detailblad
per kaart. Pure functies zonder database of netwerk: de route geeft de Radar-kaarten (radar.setup_card en radar.signal_card), de klaarstaande
Structuur-plannen met hun koers en stand, en de open Structuur-trades mee. Elk getal komt van die kaarten; hier wordt alleen gesorteerd en geteld.

Volgorde binnen een tab: in de zone eerst, dan op gemeten afstand tot de limiet, zonder koers achteraan. De tab met de meeste kansen in de zone
gaat open, anders Structuur."""
import re
from typing import Iterable, Optional

from app import nu, radar, trade_plan as tp

LABELS = {"structuur": "Structuur", "zone_radar": "Zone-radar", "zone_sweep": "Zone-sweep", "poc_radar": "POC-radar", "smc": "SMC"}
ORDER = ("structuur", "zone_radar", "zone_sweep", "poc_radar", "smc")
# Naar buiten is elke structuurkans Structuur (CLAUDE.md, Structuur zonder oordeel): structuur_c staat in dezelfde tab.
TAB_OF = {"structuur": "structuur", "structuur_c": "structuur", "zone_radar": "zone_radar", "zone_sweep": "zone_sweep", "poc_radar": "poc_radar",
          "smc": "smc"}
DEFAULT_TAB = "structuur"
# Soorten met een eigen getekende kaartgrafiek die de pagina lazy ophaalt (/api/kaart_svg, app/card_chart.py): de zone op zijn eigen tijdframe.
# Structuur draagt zijn momentopname al in `svg`; SMC houdt de generieke kaartgrafiek.
SVG_TYPES = ("zone_radar", "zone_sweep", "poc_radar")


def _svg_src(item: dict) -> Optional[str]:
    return f"/api/kaart_svg/{item['key']}" if item.get("trade_type") in SVG_TYPES else None


def say(state: Optional[str], direction: str, zone: bool = True) -> str:
    """De zin in het detailblad, alleen voor een plan dat nog niet vulde. De getallen staan in de tabel eronder en worden niet herhaald."""
    if state == "open":
        return ""
    if state == "in_zone":
        return f"De koers staat in de zone: je limit {direction} op de instap is waarschijnlijk gevuld. Houd stop en doel aan."
    where = "de zone" if zone else "de instap"
    return f"Wacht tot de koers {where} bereikt. Zet dan een limit {direction} op de instap, met de stop en het doel uit de tabel."


def _plan(item: dict, dom_id: str) -> dict:
    state = item["state"]
    # In de zone geen groot getal: de stand staat al als pil en in de zin erboven, drie keer "In zone" was ruis.
    if item.get("distance_pct") is not None and item["distance_pct"] > 0:
        num = (item["distance_text"], "distance", "tot de instap")
    else:
        num = ("", "distance", "")
    return {**item, "dom_id": dom_id, "title": f"{item['coin']} {item['direction']}", "tab": TAB_OF.get(item["trade_type"], item["trade_type"]), "group": "plans",
            "svg_src": _svg_src(item),
            "state_short": tp.STATE_SHORT.get(state, "Geen koers") if state else "Geen koers", "say": say(state, item["direction"], item.get("zone_low") is not None),
            "num_text": num[0], "num_hook": num[1], "num_label": num[2]}


def _trade(item: dict) -> dict:
    return {**item, "dom_id": "radar-" + item["key"].replace(":", "-"), "title": f"{item['coin']} {item['direction']}", "state": "open", "group": "trades",
            "svg_src": _svg_src(item),
            "tab": TAB_OF.get(item["trade_type"], item["trade_type"]), "state_short": "Open", "say": "",
            "num_text": item["live_r_text"] or "", "num_hook": "live_r", "num_label": "nu, live" if item["live_r_text"] else ""}


def structure_item(card: dict, price: Optional[float], state: Optional[str]) -> dict:
    """Een klaarstaand Structuur-plan (web.main._structure_cards). `svg` is zijn eigen momentopname (setup_chart.setup_svg: de gebroken lijn of
    range, het retest-niveau, de stop en T1 tot T3): de generieke kaartgrafiek liet de breuk weg en daarmee het waarom van het plan. Zonder
    momentopname blijft de kaartgrafiek als terugval."""
    item = nu.structure_item(card, price, state)
    chart = tp.chart_spec(card["direction"], card["plan"]["stop"], card["targets"][0][0] if card["targets"] else None, card["plan"]["level"], price)
    return _plan({**item, "chart": chart, "svg": card.get("chart") or "", "origin": "Structuur · breuk van een lijn of range op 30m"},
                 f"structuur-{card['id']}")


# Twee kaarten van dezelfde soort, coin en richting met een instap binnen 0,2% zijn voor wie de order zet dezelfde kans: 0,2% is vooraf gekozen als
# ruim onder de kleinste stopafstand die een plan mag hebben (SMC_MIN_STOP_PCT, de vloer van smc_eval.floor_stop), zodat twee plannen die
# echt een andere order vragen nooit samenvallen, en ruim boven afrondingsverschillen tussen twee motorrondes. Niet afgesteld op data.
DUP_PCT = 0.2


def similar_text(n: int) -> str:
    if not n:
        return ""
    return f"Nog {n} vergelijkbaar signaal" if n == 1 else f"Nog {n} vergelijkbare signalen"


def dedupe(items: list[dict], price_key: str) -> list[dict]:
    """Eén kaart per coin, richting en instap (binnen DUP_PCT) in deze lijst: de oudste blijft (created_at, daarna de volgorde), met `similar`
    het aantal dat wegviel en `keys` de sleutels van allemaal (Verberg neemt de tweelingen mee). Alleen voor de weergave van Kansen; de signalen
    zelf blijven overal staan (Bewijs, Logboek, meldingen)."""
    kept: list[dict] = []
    for it in sorted(items, key=lambda x: x.get("created_at") or ""):
        p = it.get(price_key)
        twin = next((k for k in kept if k["coin"] == it["coin"] and k["direction"] == it["direction"] and p and k.get(price_key)
                     and abs(p - k[price_key]) / k[price_key] * 100 <= DUP_PCT), None)
        if twin is None:
            kept.append({**it, "similar": 0, "keys": [it["key"]]})
        else:
            twin["similar"] += 1
            twin["keys"].append(it["key"])
    for k in kept:
        k["similar_text"] = similar_text(k["similar"])
    return kept


# Verbergen (tabel kans_hidden): een weergavekeuze per gebruiker. Dezelfde sleutels als de kaarten en het overslaan (nu.SKIP_KEY); MAX_HIDE per
# verzoek is ruim boven wat één tab ooit toont en houdt een verzoek klein.
HIDE_KEY = re.compile(r"^(zone|zsweep|setup|signal|structuur):\d+$")
MAX_HIDE = 200


def parse_keys(raw) -> list[str]:
    """Geldige kaartsleutels uit een verzoek (één sleutel of een lijst), uniek en in volgorde."""
    raw = [raw] if isinstance(raw, str) else (raw if isinstance(raw, list) else [])
    keys: list[str] = []
    for k in raw:
        if isinstance(k, str) and HIDE_KEY.match(k) and k not in keys:
            keys.append(k)
    return keys[:MAX_HIDE]


def hidden_text(titles: list[str]) -> str:
    """De ongedaan-balk: "HYPE short verborgen" of "3 kaarten verborgen". kaarten.js zegt hetzelfde (tests/test_static_js.py)."""
    return f"{titles[0]} verborgen" if len(titles) == 1 else f"{len(titles)} kaarten verborgen"


def hidden_label(n: int) -> str:
    return f"Verborgen ({n})" if n else ""


def _hidden_rows(plans: list[dict], trades: list[dict]) -> list[dict]:
    return [{"key": it["key"], "keys": it["keys"], "title": it["title"], "state": it["state"], "state_short": it["state_short"], "group": group,
             "dom_id": it["dom_id"]} for group, items in (("plans", plans), ("trades", trades)) for it in items]


def _sort_key(item: dict):
    d = item.get("distance_pct")
    return (item.get("skipped", False), item["state"] != "in_zone", d is None, d if d is not None else 0.0)


def summary(n: int, in_zone: int, trades: int) -> str:
    """"12 kansen klaar · 2 in de zone · 3 open": alleen wat er is, dus geen "0 in de zone" en geen "0 open"."""
    if not n and not trades:
        return "Geen kansen"
    parts = [f"{n} {'kans' if n == 1 else 'kansen'} klaar"] if n else []
    if in_zone:
        parts.append(f"{in_zone} in de zone")
    if trades:
        parts.append(f"{trades} open")
    return " · ".join(parts)


def page(radar_cards: list[dict], structure: Iterable[tuple[dict, Optional[float], Optional[str]]], structure_trades: list[dict],
         kinds: Iterable[str], skipped: Iterable[str] = (), hidden: Iterable[str] = ()) -> dict:
    """`kinds`: de soorten die een tab krijgen (focus.FOCUS_TYPES met de kijkrechten van de route). Een kaart van een andere soort valt weg.
    `skipped`: plannen die je oversloeg (cookie en plan_skips, een dag); die blijven staan, achteraan en gemarkeerd.
    `hidden`: kaarten die deze gebruiker verborg (kans_hidden). Die staan niet in de lijst en tellen nergens mee (tab, badge, totaal, ook niet
    als 'vergelijkbaar'), maar wel onderaan hun tab als `hidden` (rijen) en `hidden_cards` (de kaart zelf, voor Toon weer zonder herladen)."""
    wanted = set(kinds)
    plans = [{**structure_item(card, price, state), "created_at": card.get("created_at")} for card, price, state in structure]
    plans += [{**_plan(nu._from_setup(c), "radar-" + c["key"].replace(":", "-")), "created_at": c.get("created_at")} for c in radar.waiting_cards(radar_cards)]
    skipped, hidden = set(skipped), set(hidden)
    for p in plans:
        p["skipped"] = p["key"] in skipped
    # `svg`: de route zet bij een open Structuur-trade zijn getekende setup op de kaart (kans_view.chart); de andere soorten hebben er geen.
    trades = [_trade({**nu._from_signal(c), "svg": c.get("svg") or ""}) for c in radar_cards + structure_trades if c and c["kind"] == "signal"]
    # Een open trade blijft staan, ook als zijn soort geen nieuwe kansen meer zoekt (focus): dan krijgt die soort toch een tab.
    kinds = [k for k in ORDER if k in set(kinds) or any(t["tab"] == k for t in trades)]
    tabs = []
    for k in kinds:
        # Ontdubbelen per tab en per groep: een open trade telt nooit tegen een wachtend plan, en dezelfde coin in een andere tab is een andere soort.
        # Verborgen kaarten gaan eruit vóór het ontdubbelen, zodat ze ook niet als 'vergelijkbaar' meetellen.
        tab_plans = [p for p in plans if p["tab"] == k and k in wanted]
        tab_trades = [t for t in trades if t["tab"] == k]
        mine = sorted(dedupe([p for p in tab_plans if p["key"] not in hidden], "limit"), key=_sort_key)
        open_ = sorted(dedupe([t for t in tab_trades if t["key"] not in hidden], "entry"), key=lambda t: t["created_at"], reverse=True)
        hid_plans = sorted(dedupe([p for p in tab_plans if p["key"] in hidden], "limit"), key=_sort_key)
        hid_trades = sorted(dedupe([t for t in tab_trades if t["key"] in hidden], "entry"), key=lambda t: t["created_at"], reverse=True)
        zone = sum(1 for p in mine if p["state"] == "in_zone")
        moot = [{"title": f"{c['coin']} {c['direction']}", "label": c["state_label"], "dom_id": "radar-" + c["key"].replace(":", "-")}
                for c in radar.moot_cards(radar_cards) if TAB_OF.get(c["setup"].get("source") or "smc") == k and k in wanted and c["key"] not in hidden]
        # `num` staat naast de naam (ook 0, dan weet je dat de tab leeg is), `badge` is de accentteller en alleen er zolang er iets in de zone staat.
        tabs.append({"key": k, "label": LABELS[k], "href": f"#tab-{k}", "plans": mine, "trades": open_, "n": len(mine), "in_zone": zone,
                     "num": len(mine), "badge": zone or None, "count": None, "summary": summary(len(mine), zone, len(open_)), "moot": moot,
                     "hidden": _hidden_rows(hid_plans, hid_trades), "hidden_cards": hid_plans + hid_trades,
                     "hidden_label": hidden_label(len(hid_plans) + len(hid_trades))})
    best = max(tabs, key=lambda t: t["in_zone"], default=None)
    active = best["key"] if best and best["in_zone"] else (DEFAULT_TAB if DEFAULT_TAB in kinds else (kinds[0] if kinds else DEFAULT_TAB))
    n, zone, open_n = sum(t["n"] for t in tabs), sum(t["in_zone"] for t in tabs), sum(len(t["trades"]) for t in tabs)
    return {"tabs": tabs, "active": active, "in_zone": zone, "total": {"n": n, "in_zone": zone, "open": open_n, "text": summary(n, zone, open_n)}}
