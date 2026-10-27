"""Het scherm Nu (/vandaag): er is niets te doen, of precies één ding. Pure functies zonder database of netwerk; de route geeft de kaarten
van de Radar (radar.setup_card en radar.signal_card) en de overgeslagen sleutels mee, en de template tekent alleen.

Rust: geen plan in de zone en geen open trade. Dan staat er één zin en het eerstvolgende plan met zijn gemeten afstand tot de limiet.
Zone: een plan staat in de zone; die kaart vult het scherm, een tweede staat klein eronder en nooit ernaast.
Trade: alleen een open trade; die staat er met zijn live R zoals op de Radar."""
import re
from typing import Iterable, Optional

from app import chance_steps, radar

TRADE_TYPE_ZONE = "zone_radar"          # zelfde waarde als zone_radar.TRADE_TYPE; niet importeren houdt dit bestand los van pandas
TRADE_TYPE_SWEEP = "zone_sweep"         # zelfde waarde als zone_sweep.TRADE_TYPE
UNTESTED_SOURCES = (TRADE_TYPE_ZONE, TRADE_TYPE_SWEEP)
MAX_SKIP = 20
SKIP_KEY = re.compile(r"^(zone|zsweep|setup|signal|structuur):\d+$")
DIR_WORD = {"long": "Long", "short": "Short"}


def nl(value: float) -> str:
    """Om te lezen: dezelfde cijfers als chance_steps.fmt, met een komma. Kopiëren gaat altijd met de punt van chance_steps.fmt."""
    return chance_steps.fmt(value).replace(".", ",")


def pct_nl(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + "%"


def r_nl(value: float) -> str:
    return f"{value:+.2f}".replace(".", ",").replace("-", "\u2212") + " R"      # echt minteken, zoals nu.js


def plan_rows(direction: str, entry: float, stop: float, targets: list[tuple[float, float]], entry_label: str = "Instap") -> list[dict]:
    """Stop, instap en doelen op volgorde van prijs, hoogste bovenaan, zoals ze op de grafiek liggen: bij een short staat de stop boven."""
    many = len(targets) > 1
    rows = [{"label": "Stop", "value": stop, "tone": "loss"}, {"label": entry_label, "value": entry, "tone": "entry"}]
    rows += [{"label": (f"Doel {i} · " if many else "Doel · ") + f"{r:.1f} R".replace(".", ","), "value": t, "tone": "win"}
             for i, (t, r) in enumerate(targets, 1)]
    rows.sort(key=lambda r: -r["value"])
    return [{**r, "text": nl(r["value"]), "copy": chance_steps.fmt(r["value"])} for r in rows]


def plan_item(key: str, coin: str, direction: str, limit: float, stop: float, targets: list[tuple[float, float]], *, price: Optional[float],
              state: Optional[str], distance_pct: Optional[float] = None, approach_pct: Optional[float] = None, action: str = "",
              trade_type: str = "smc", untested: bool = False) -> dict:
    return {"kind": "plan", "key": key, "coin": coin, "direction": direction, "dir_word": DIR_WORD.get(direction, direction),
            "limit": limit, "limit_text": nl(limit), "stop": stop, "targets": targets, "price": price, "price_text": nl(price) if price else "",
            "state": state, "distance_pct": distance_pct, "distance_text": pct_nl(distance_pct) if distance_pct is not None else "",
            "approach_pct": approach_pct, "action": action, "trade_type": trade_type, "untested": untested,
            "rows": plan_rows(direction, limit, stop, targets), "checklist_url": f"/nu/order/{key}"}


def _from_setup(c: dict) -> dict:
    source = (c.get("setup") or {}).get("source")
    untested = source in UNTESTED_SOURCES
    p = c["plan"]
    # Een plan zonder doel (zone-sweep) heeft alleen instap en stop: het doel kies je zelf.
    return plan_item(c["key"], c["coin"], c["direction"], p.limit, p.stop, [(p.take, p.rr)] if p.take is not None else [], price=c["price"],
                     state=c["state"], distance_pct=c["distance_pct"], approach_pct=c["approach_pct"], action=c["action"],
                     trade_type=source if untested else "smc", untested=untested)


def _from_signal(c: dict) -> dict:
    s = c["signal"]
    r = c["live_r"]
    return {"kind": "trade", "key": c["key"], "coin": c["coin"], "direction": c["direction"], "dir_word": DIR_WORD.get(c["direction"], c["direction"]),
            "entry": s["price"], "price": c["price"], "price_text": nl(c["price"]) if c["price"] else "", "action": c["action"],
            "live_r": r, "live_r_text": r_nl(r) if r is not None else "", "trade_type": s.get("trade_type") or "smc",
            "untested": s.get("trade_type") in UNTESTED_SOURCES, "created_at": c["created_at"], "url": f"/kans/{s['id']}",
            "rows": plan_rows(c["direction"], s["price"], s["stop_loss"], [(s["take_profit"], c["rr"])])}


def screen(cards: list[dict], skipped: Iterable[str] = (), prefer: Optional[str] = None) -> dict:
    """Wat Nu toont. `cards` zijn de Radar-kaarten; alleen plannen die nog kunnen vullen tellen (radar.OPEN_STATES, dezelfde keuze als de tab
    Wachten). Binnen de zone gaat het plan voor dat het dichtst bij zijn limiet staat; `prefer` (een tik op 'Ook in zone') zet een ander voorop."""
    skipped = set(skipped)
    plans = [_from_setup(c) for c in cards if c["kind"] == "setup" and c["state"] in radar.OPEN_STATES]
    trades = sorted((_from_signal(c) for c in cards if c["kind"] == "signal"), key=lambda t: t["created_at"], reverse=True)
    in_zone = sorted((p for p in plans if p["state"] == "in_zone"), key=lambda p: abs(p["distance_pct"] or 0))
    live = [p for p in in_zone if p["key"] not in skipped]
    live.sort(key=lambda p: p["key"] != prefer)
    waiting = [p for p in plans if p["state"] == "wacht" and p["distance_pct"] is not None]
    base = {"plans": len(plans), "open_trades": len(trades), "skipped": [p for p in in_zone if p["key"] in skipped],
            "nearest": min(waiting, key=lambda p: p["distance_pct"]) if waiting else None}
    if live:
        return {**base, "mode": "zone", "focus": live[0], "also": live[1:], "trades": trades}
    if trades:
        return {**base, "mode": "trade", "focus": trades[0], "also": [], "trades": trades[1:]}
    return {**base, "mode": "rust", "focus": None, "also": [], "trades": []}


def item_for(cards: list[dict], key: str) -> Optional[dict]:
    """Het plan achter een checklist-sleutel, alleen zolang het nog kan vullen; een open trade of een vervallen plan heeft geen order meer."""
    for c in cards:
        if c["key"] == key and c["kind"] == "setup" and c["state"] in radar.OPEN_STATES:
            return _from_setup(c)
    return None


def structure_item(card: dict, price: Optional[float], state: Optional[str]) -> dict:
    """Een klaarstaand Setups-plan (web.main._structure_cards) als checklist-item: limiet op het retest-niveau, met al zijn doelen."""
    level = card["plan"]["level"]
    long = card["direction"] == "long"
    dist = ((price - level) / level * 100 if long else (level - price) / level * 100) if price else None
    return plan_item(f"structuur:{card['id']}", card["coin"], card["direction"], level, card["plan"]["stop"], [tuple(t) for t in card["targets"]],
                     price=price, state=state, distance_pct=dist, trade_type="structuur")


MONTHS = ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december")
DAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


def date_line(dt) -> str:
    return f"{DAYS[dt.weekday()].capitalize()} {dt.day} {MONTHS[dt.month - 1]} · {dt:%H:%M}"


def checklist(item: dict) -> list[dict]:
    """De order-checklist in de volgorde van het orderformulier: instrument en richting, limietprijs, stop, doel. Geen stap voor de grootte:
    positiegrootte zit bewust niet in HesPulse."""
    targets = item["targets"]
    many = len(targets) > 1
    choices = [{"label": f"Doel {i} · {r:.1f} R".replace(".", ","), "text": nl(t), "copy": chance_steps.fmt(t)} for i, (t, r) in enumerate(targets, 1)] if many else []
    goal_sub = "Kies een doel, de rest kun je later bijzetten." if many else f"{targets[0][1]:.1f} R vanaf je instap.".replace(".", ",", 1) if targets else ""

    def step(n, title, sub, value=None, tone=""):
        return {"n": n, "title": title, "sub": sub, "value": value, "text": nl(value) if value is not None else "",
                "copy": chance_steps.fmt(value) if value is not None else "", "tone": tone, "choices": []}

    first = [step(1, f"Open {item['coin']} bij je beurs", f"Kies {item['dir_word']} en Limit in het orderformulier."),
             step(2, "Limietprijs", "Plak in het prijsveld.", item["limit"]),
             step(3, "Stop", "Zet hem meteen mee, niet later.", item["stop"], "loss")]
    if not targets:
        return first + [step(4, "Doel", "Geen doel van HesPulse: dat kies je zelf.")]
    return first + [{**step(4, "Doel", goal_sub, targets[0][0], "win"), "choices": choices}]


def price_note(item: Optional[dict]) -> str:
    """De regel naast 'Koers nu' onderaan de checklist: alleen wat gemeten is (stand en afstand van dezelfde Radar-kaart)."""
    if not item or not item.get("price"):
        return ""
    state = item.get("state")
    if state == "in_zone":
        return "nog in zone"
    if state == "wacht" and item.get("distance_pct") is not None:
        return f"nog {pct_nl(item['distance_pct'])} tot instap"
    if state == "door_zone":
        return "door de zone heen"
    if state == "ongeldig":
        return "plan vervallen, stop geraakt"
    return ""


def parse_skip(raw: Optional[str]) -> frozenset:
    return frozenset(k for k in (raw or "").split(",") if SKIP_KEY.match(k))


def add_skip(raw: Optional[str], key: str) -> str:
    """De overgeslagen sleutels voor de cookie, nieuwste laatst; de oudste vallen eraf na MAX_SKIP."""
    keys = [k for k in (raw or "").split(",") if SKIP_KEY.match(k) and k != key] + ([key] if SKIP_KEY.match(key) else [])
    return ",".join(keys[-MAX_SKIP:])
