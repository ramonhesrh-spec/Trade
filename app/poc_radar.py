"""POC-radar: per coin de dichtstbijzijnde naakte dag- of week-POC (app/poc.py) onder de koers (long) en erboven (short), als limietplan op Kansen.
Live op uitdrukkelijk verzoek van de CEO (2026-10-28), zonder labrun: altijd ongetest, Bewijs toont de score (trade_type 'poc_radar').

Vaste regels, vooraf gekozen en nergens op afgesteld:
  - Instap: de dichtstbijzijnde naakte POC binnen MAX_DISTANCE_PCT (6%, dezelfde grens als de zone-radar) aan die kant van de koers. Alleen die
    ene telt: valt hij af, dan wordt er niet naar een verder niveau gezocht.
  - Limiet op de POC, stop een kwart ATR (1u, ATR 14 op gesloten candles) voorbij de POC met de ondergrens van smc_eval.floor_stop.
  - Doel: het eerste niveau voorbij de koers in de richting van de trade: een dag- of week-POC (naakt of niet) of de rand van de eerstvolgende
    tegenovergestelde actieve zone (zone_radar.target_for). Haalt dat ene niveau geen MIN_RR (2R), dan heeft de kaart geen doel: die volgt de
    motor zoals de zone-sweep zonder doel, met de referentie-uitgang. Nooit doorzoeken naar een verder doel.
  - Een kaart die niet vulde vervalt na TTL.
Pure functies zonder database of netwerk; de motor (app/poc_radar_live.py), de pagina en de tests rekenen met dezelfde code."""
from typing import Iterable, Optional

import pandas as pd

from app import poc, smc_eval
from app import trade_plan as tp
from app import zone_radar as zr

TRADE_TYPE = "poc_radar"
LABEL = "POC-radar"
MAX_DISTANCE_PCT = zr.MAX_DISTANCE_PCT
STOP_ATR = zr.STOP_ATR
MIN_RR = zr.MIN_RR
# Vooraf gekozen: drie dagen. Een limiet die zo lang niet vult, hoort niet meer bij de markt van vandaag; een dag-POC is dan al drie nieuwe dagen oud.
TTL = pd.Timedelta(days=3)
PERIOD_ORDER = poc.PERIODS                  # bij gelijke afstand eerst de dag-POC; dezelfde prijs is dezelfde order


def _distance_pct(direction: str, level: float, price: float) -> float:
    return (price - level) / price * 100 if direction == "long" else (level - price) / price * 100


def next_target(direction: str, levels: Iterable[poc.PocLevel], zones: list[zr.ZoneLevel], price: float) -> Optional[dict]:
    """Het eerste niveau voorbij `price` in de richting van de trade: een POC (naakt of niet) of de rand van de eerstvolgende tegenovergestelde zone."""
    sign = 1 if direction == "long" else -1
    options = [{"price": lv.price, "kind": "poc", "text": poc.period_text(lv.period, lv.start), "tf": None, "low": None, "high": None}
               for lv in levels if (lv.price - price) * sign > 0]
    zone = zr.target_for(direction, zones, price)
    if zone is not None:
        options.append({"price": zr.target_edge(direction, zone), "kind": "zone", "text": zr.target_text(direction, zone.tf), "tf": zone.tf,
                        "low": zone.low, "high": zone.high})
    if not options:
        return None
    return min(options, key=lambda o: (o["price"] - price) * sign)


def plan_for(direction: str, levels: list[poc.PocLevel], zones: list[zr.ZoneLevel], price: float, atr: float) -> Optional[dict]:
    """Het plan voor de dichtstbijzijnde naakte POC aan deze kant, of None. Zonder doel is ook een plan: dan zijn take_profit en rr None."""
    own = [lv for lv in levels if lv.naked and 0 < _distance_pct(direction, lv.price, price) <= MAX_DISTANCE_PCT]
    if not own or not atr > 0:
        return None
    level = min(own, key=lambda lv: (_distance_pct(direction, lv.price, price), PERIOD_ORDER.index(lv.period)))
    limit = level.price
    raw_stop = limit - STOP_ATR * atr if direction == "long" else limit + STOP_ATR * atr
    stop = smc_eval.floor_stop(direction, limit, raw_stop)
    target = next_target(direction, levels, zones, price)
    take = rr = None
    if target is not None:
        plan = tp.limit_plan(direction, limit, limit, stop, target["price"], limit=limit)
        if plan is not None and plan.rr >= MIN_RR:
            take, rr = target["price"], plan.rr
    if tp.limit_plan(direction, limit, limit, stop, take, limit=limit) is None:
        return None
    if tp.plan_state(direction, limit, limit, stop, price, take=take) != "wacht":
        return None
    has = take is not None
    return {"direction": direction, "period": level.period, "period_start": level.start.isoformat(), "level_key": level.key, "level": limit,
            "limit_price": limit, "stop_loss": stop, "take_profit": take, "rr": rr, "atr": atr,
            "target_kind": target["kind"] if has else None, "target_text": target["text"] if has else None,
            "target_tf": target["tf"] if has else None, "target_low": target["low"] if has else None, "target_high": target["high"] if has else None,
            "distance_pct": _distance_pct(direction, limit, price)}


def plans(levels: list[poc.PocLevel], zones: list[zr.ZoneLevel], price: float, atr: float) -> list[dict]:
    return [p for d in ("long", "short") if (p := plan_for(d, levels, zones, price, atr))]


def walk(direction: str, limit: float, take: Optional[float], candles: pd.DataFrame) -> tuple[Optional[str], Optional[pd.Timestamp]]:
    """Zoals zone_radar.walk, ook zonder doel: ('filled', tijd) bij een aanraking van de limiet, ('doel_geraakt', tijd) als het doel eerst kwam.
    Raakt één candle beide, dan telt de vulling."""
    for c in candles.itertuples():
        if (c.low <= limit) if direction == "long" else (c.high >= limit):
            return "filled", c.timestamp
        if take is not None and ((c.high >= take) if direction == "long" else (c.low <= take)):
            return "doel_geraakt", c.timestamp
    return None, None


def level_text(row: dict) -> str:
    """'Naakte dag-POC 27 okt' (hoofdletter: begin van een regel)."""
    return f"Naakte {poc.period_text(row['period'], row['period_start'])}"


def target_line(row: dict) -> str:
    if row.get("take_profit") is None:
        return "geen doel: dat kies je zelf"
    return f"doel {row['target_text']}"


def radar_setup(row: dict) -> dict:
    """Een rij uit poc_radar_setups in de vorm die radar.setup_card leest. De 'zone' is het niveau zelf: een POC is één prijs, geen vak."""
    return {**row, "source": TRADE_TYPE, "zone_low": row["level"], "zone_high": row["level"], "limit": row["limit_price"],
            "preview_stop_loss": row["stop_loss"], "preview_take_profit": row["take_profit"], "chart_zone": None, "no_zone": True,
            "origin_label": level_text(row)}


def new_card_body(row: dict) -> str:
    from app import push_notify
    fp = push_notify.fmt_price
    first = f"Limiet {fp(row['limit_price'])}" + (f" · R:R {row['rr']:.1f}" if row.get("rr") else "")
    second = f"Stop {fp(row['stop_loss'])} · " + (f"Doel {fp(row['take_profit'])} ({row['target_text']})" if row.get("take_profit") is not None
                                                  else "geen doel: kies je zelf")
    return "\n".join([first, second, f"{level_text(row)}: hier lag het meeste volume en de koers kwam er sindsdien niet meer.",
                      "Zet je limietorder klaar als je hem wilt. Ongetest: Bewijs toont de score.", push_notify.OPEN_PLAN_LINE])


def fill_body(row: dict, entry: float) -> str:
    from app import push_notify
    fp = push_notify.fmt_price
    levels = f"stop {fp(row['stop_loss'])}, " + (f"doel {fp(row['take_profit'])}" if row.get("take_profit") is not None else "doel kies je zelf")
    return "\n".join([f"Limiet geraakt op {fp(entry)}, {levels}",
                      "Stond jouw eigen limiet er, dan is die nu gevuld. Het systeem plaatst zelf nooit een order.", "Ongetest: een proef.",
                      push_notify.OPEN_PLAN_LINE])


def signal_row(row: dict, entry: float) -> dict:
    """Het signaal bij de vulling, buiten de openbare ketting (chain_it=False): de regel is ongetest."""
    goal = (f"Doel {row['target_text']} op {row['take_profit']:.6g}." if row.get("take_profit") is not None
            else "Geen doel: dat kies je zelf. Bewijs telt de R bij een referentie-uitgang (meelopende stop 3 ATR op 1u).")
    return {"message_id": None, "coin": row["coin"], "direction": row["direction"], "category": "day_trading", "trade_type": TRADE_TYPE,
            "pattern_name": "Week-POC" if row["period"] == "week" else "Dag-POC", "price": entry, "stop_loss": row["stop_loss"],
            "take_profit": row.get("take_profit"), "confidence": f"{LABEL} (ongetest)", "technical_confirmed": 1, "hard_gates_ok": 1,
            "is_practice": 0, "pass_pct": None,
            "reason": f"Gemeten: {level_text(row).lower()} op {row['level']:.6g}, sindsdien niet geraakt op 5m.",
            "plain_explanation": f"{level_text(row)} op {row['level']:.6g}: de prijs met het meeste volume in die periode. Limiet {entry:.6g}, "
                                 f"stop {row['stop_loss']:.6g}. {goal} Ongetest.",
            "suggested_entry_low": row["level"], "suggested_entry_high": row["level"]}
