"""Zone-sweep als kaart: de setup van de detector (app/replay/zonesweep.py, docs/onderzoek/zone-sweep/preregistratie.md) als limietplan op de
Radar. Pure functies zonder database of netwerk; de motor (app/zone_sweep_live.py), de pagina's en de tests rekenen met dezelfde code.

Wat vastligt in de pre-registratie: varianten ZS_1H, ZS_2H en ZS_4H (limiet op de binnenrand van de zone, met HTF-filter) en de stop wick_025
(zonesweep.final_stop). Een doel heeft de pre-registratie niet, want het lab meet de stopkwaliteit. Voor een bruikbare kaart is het doel de rand
van de eerstvolgende tegenovergestelde actieve zone (zone_radar.target_for), minstens MIN_RR; anders heeft de kaart geen doel en kies je het zelf.

Eerlijk over wat dit is: ongetest. De labrun volgt later; tot dan bewijst niets hier dat de regel werkt. Bewijs toont de score apart."""
from typing import Optional

import pandas as pd

from app import trade_plan as tp
from app import zone_radar as zr
from app.replay import zonesweep as zs

TRADE_TYPE = "zone_sweep"
LABEL = "Zone-sweep"
LIVE_VARIANTS = ("ZS_1H", "ZS_2H", "ZS_4H")
STOP_NAME = "wick_025"
TFS = zs.TFS
TF_TEXT = {"1h": "1u", "2h": "2u", "4h": "4u"}
MIN_RR = zr.MIN_RR
TTL = pd.Timedelta(hours=24)             # pre-registratie: orders vervallen na 24 uur, zoals de range sweep


def zone_levels(frames: dict, now: pd.Timestamp) -> list[zr.ZoneLevel]:
    """De actieve zones op 1u, 2u en 4u op dit moment (alleen gesloten candles), om een doel te zoeken. Dezelfde regels als de zone-radar."""
    out: list[zr.ZoneLevel] = []
    for tf in TFS:
        out += zr.active_zones(frames[tf], tf, now)
    return out


def zone_key(s: dict) -> str:
    """Dezelfde vorm als zone_radar.ZoneLevel.key (tf, soort, openmoment van de order block-candle): de grafiek leest er de herkomst uit."""
    kind = "bear" if s["direction"] == zs.SHORT else "bull"
    return f"{s['tf']}:{kind}:{pd.Timestamp(s['zone_at']).isoformat()}"


def card_row(coin: str, variant: str, s: dict, zones: list[zr.ZoneLevel]) -> dict:
    """De kaart van een setup. Alleen de eerstvolgende tegenovergestelde zone voorbij het slot van de herstelcandle telt als doel: haalt die
    MIN_RR niet, dan geen doel, nooit doorzoeken naar een verdere zone die wel past."""
    direction = s["direction"]
    limit = float(s["legs"][0][1])
    stop = zs.final_stop(s, STOP_NAME)
    target = zr.target_for(direction, zones, s["ref_price"])
    take = rr = None
    if target is not None:
        edge = zr.target_edge(direction, target)
        plan = tp.limit_plan(direction, s["zone_low"], s["zone_high"], stop, edge, limit=limit)
        if plan is not None and plan.rr >= MIN_RR:
            take, rr = edge, plan.rr
    has_target = take is not None
    return {"coin": coin, "direction": direction, "variant": variant, "stop_name": STOP_NAME, "tf": s["tf"], "zone_key": zone_key(s),
            "zone_low": float(s["zone_low"]), "zone_high": float(s["zone_high"]), "zone_at": pd.Timestamp(s["zone_at"]).isoformat(),
            "sweep_at": pd.Timestamp(s["sweep_at"]).isoformat(), "extreme": float(s["extreme"]), "placed_at": s["placed_at"].isoformat(),
            "expires_at": (s["placed_at"] + TTL).isoformat(), "ref_price": float(s["ref_price"]), "range_high": float(s["range_high"]),
            "range_low": float(s["range_low"]), "atr_t": float(s["atr_t"]), "limit_price": limit, "stop_loss": stop, "take_profit": take, "rr": rr,
            "target_tf": target.tf if has_target else None, "target_low": target.low if has_target else None,
            "target_high": target.high if has_target else None,
            "prik_atr": float(s["features"]["prik_atr"]), "herstel_bars": int(s["features"]["herstel_bars"])}


def alive(row: dict, price: Optional[float]) -> bool:
    """Een plan dat bij het ontstaan al voorbij de stop staat of zijn doel haalde zonder vulling, wordt niet gemeld (tp.plan_state). In de zone is
    wel levend: de limiet vult dan meteen."""
    if not price:
        return True
    return tp.plan_state(row["direction"], row["zone_low"], row["zone_high"], row["stop_loss"], price, take=row.get("take_profit")) not in ("ongeldig", "doel_geraakt")


def chart_zone(row: dict) -> Optional[dict]:
    return zr.chart_zone(row, tfs=TFS)


def radar_setup(row: dict) -> dict:
    """Een rij uit zone_sweep_setups in de vorm die radar.setup_card leest, met source zodat de kaart een eigen sleutel ('zsweep:<id>') krijgt."""
    return {**row, "source": TRADE_TYPE, "preview_stop_loss": row["stop_loss"], "preview_take_profit": row["take_profit"],
            "limit": row["limit_price"], "chart_zone": chart_zone(row)}


def zone_text(row: dict) -> str:
    return f"{'Vraagzone' if row['direction'] == 'long' else 'Aanbodzone'} {TF_TEXT.get(row['tf'], row['tf'])}"


def target_text(row: dict) -> str:
    if row.get("take_profit") is None:
        return "geen doel: dat kies je zelf"
    return f"doel {'aanbodzone' if row['direction'] == 'long' else 'vraagzone'} {TF_TEXT.get(row['target_tf'], row['target_tf'])}"


def new_card_body(row: dict) -> str:
    from app import push_notify
    fp = push_notify.fmt_price
    side = "eronder" if row["direction"] == "long" else "erboven"
    first = f"Limiet {fp(row['limit_price'])}" + (f" · R:R {row['rr']:.1f}" if row.get("rr") else "")
    second = f"Stop {fp(row['stop_loss'])} · " + (f"Doel {fp(row['take_profit'])}" if row.get("take_profit") is not None else "geen doel: kies je zelf")
    return "\n".join([first, second, f"{zone_text(row)} {fp(row['zone_low'])} tot {fp(row['zone_high'])}: prik {side} en herstel.",
                      "Ongetest: een proef, Bewijs toont de score.", push_notify.OPEN_PLAN_LINE])


def fill_body(row: dict, entry: float) -> str:
    from app import push_notify
    fp = push_notify.fmt_price
    levels = f"stop {fp(row['stop_loss'])}, " + (f"doel {fp(row['take_profit'])}" if row.get("take_profit") is not None else "doel kies je zelf")
    return "\n".join([f"Limiet geraakt op {fp(entry)}, {levels}",
                      "Stond jouw eigen limiet er, dan is die nu gevuld. Het systeem plaatst zelf nooit een order.", "Ongetest: een proef.",
                      push_notify.OPEN_PLAN_LINE])


def signal_row(row: dict, entry: float) -> dict:
    """Het signaal bij de vulling. Buiten de openbare ketting (de aanroeper legt het met chain_it=False vast): de regel is ongetest."""
    zone = f"{zone_text(row)} {row['zone_low']:.6g} tot {row['zone_high']:.6g}"
    side = "onder" if row["direction"] == "long" else "boven"
    goal = (f"Doel de rand van de {target_text(row)[5:]} op {row['take_profit']:.6g}." if row.get("take_profit") is not None
            else "Geen doel: dat kies je zelf. Bewijs telt de R bij een referentie-uitgang (meelopende stop 3 ATR op 1u).")
    return {"message_id": None, "coin": row["coin"], "direction": row["direction"], "category": "day_trading", "trade_type": TRADE_TYPE,
            "pattern_name": row["variant"], "price": entry, "stop_loss": row["stop_loss"], "take_profit": row.get("take_profit"),
            "confidence": f"{LABEL} (ongetest)", "technical_confirmed": 1, "hard_gates_ok": 1, "is_practice": 0, "pass_pct": None,
            "reason": f"Gemeten: prik {row['prik_atr']:.2f} ATR {side} de zone, herstel in {row['herstel_bars']} candle(s) op 1u.".replace(".", ",", 1),
            "plain_explanation": f"{zone}: de koers prikte erdoor en sloot terug. Limiet {entry:.6g}, stop voorbij de prik {row['stop_loss']:.6g}. {goal} Ongetest.",
            "suggested_entry_low": row["zone_low"], "suggested_entry_high": row["zone_high"]}
