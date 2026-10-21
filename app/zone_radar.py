"""Zone-radar: de dichtstbijzijnde actieve vraagzone onder de koers (long) en aanbodzone boven de koers (short) op 1u en 4u, als limietplan
voor wie gewoon niveaus wil zien en zelf een limietorder zet. Geen structuurbreuk, sweep of range nodig: de zone zelf is de premisse.

De zones komen uit app/replay/rangesweep.find_zones en zone_active (dezelfde definitie als lab en range sweep), alleen op gesloten candles.
Limiet op de binnenrand, stop voorbij de buitenrand met een kwart ATR en de ondergrens van smc_eval.floor_stop, doel de rand van de
eerstvolgende tegenovergestelde actieve zone, minimaal MIN_RR. Alle drempels liggen vooraf vast; er is niets op data afgesteld.

Eerlijk over wat dit is: ongetest. De kaart beschrijft een niveau, hij voorspelt niets; Bewijs toont de score (trade_type 'zone_radar').
Pure functies zonder database of netwerk: de motor (app/zone_radar_live.py), de pagina en de tests rekenen met dezelfde code."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import smc_eval
from app import trade_plan as tp
from app.replay import rangesweep as rs
from app.replay.lab import add_indicators

TRADE_TYPE = "zone_radar"
LABEL = "Zone-radar"
TFS = ("1h", "4h")
TF_TEXT = {"1h": "1u", "4h": "4u"}
# Vooraf gekozen, niet gemeten: 6% is wat een altcoin op een gewone dag of twee aflegt. Een zone verder weg is een kaart die dagen wacht en de
# Radar vult met plannen waar niemand vandaag iets mee doet; dichterbij dan dit is de zone een order die je nu kunt zetten.
MAX_DISTANCE_PCT = 6.0
# Zelfde buffer als de geteste stop 'zone_025' van de range sweep: net voorbij de buitenrand, buiten een wick die de zone alleen aantikt.
STOP_ATR = 0.25
MIN_RR = 2.0
# 400 candles: een zone blijft hooguit ZONE_MAX_AGE (200) candles actief, en find_zones heeft ervoor ruimte nodig voor de ATR en de
# overlapregel, anders hangt welke zone telt af van waar het venster toevallig begint.
FETCH_LIMIT = 400
MIN_CANDLES = 60


@dataclass(frozen=True)
class ZoneLevel:
    tf: str
    kind: str          # "bull" (vraagzone) of "bear" (aanbodzone), zoals rangesweep.Zone
    low: float
    high: float
    atr: float
    key: str           # tf, soort en openmoment van de order block-candle: dezelfde zone krijgt in elke cyclus dezelfde sleutel


def active_zones(bars: pd.DataFrame, tf: str, now: pd.Timestamp) -> list[ZoneLevel]:
    """Zones die actief zijn op de candle na de laatst gesloten candle. De ATR is die van de laatst gesloten candle van dit timeframe."""
    closed = rs.closed_only(bars, now, tf)
    if len(closed) < MIN_CANDLES:
        return []
    b = add_indicators(closed).reset_index(drop=True)
    atr = float(b["atr"].iloc[-1])
    if not atr > 0:
        return []
    n = len(b)
    return [ZoneLevel(tf, z.kind, z.low, z.high, atr, f"{tf}:{z.kind}:{pd.Timestamp(b.at[z.ob_idx, 'timestamp']).isoformat()}")
            for z in rs.find_zones(b) if rs.zone_active(z, n)]


def _distance_pct(direction: str, z: ZoneLevel, price: float) -> float:
    return (price - z.high) / price * 100 if direction == "long" else (z.low - price) / price * 100


def plan_for(direction: str, zones: list[ZoneLevel], price: float) -> Optional[dict]:
    """Het plan voor de dichtstbijzijnde eigen zone, of None. Alleen die ene zone telt: valt hij af op het doel of de 2R, dan wordt er niet
    naar een verdere zone gezocht die wel past, anders kiest de code net zo lang tot er een kaart uitkomt."""
    own_kind, opp_kind = ("bull", "bear") if direction == "long" else ("bear", "bull")
    own = [z for z in zones if z.kind == own_kind and 0 < _distance_pct(direction, z, price) <= MAX_DISTANCE_PCT]
    if not own:
        return None
    zone = min(own, key=lambda z: (_distance_pct(direction, z, price), TFS.index(z.tf)))
    if direction == "long":
        limit, raw_stop = zone.high, zone.low - STOP_ATR * zone.atr
        targets = [z for z in zones if z.kind == opp_kind and z.low > price]
        target = min(targets, key=lambda z: z.low) if targets else None
        take = target.low if target else None
    else:
        limit, raw_stop = zone.low, zone.high + STOP_ATR * zone.atr
        targets = [z for z in zones if z.kind == opp_kind and z.high < price]
        target = max(targets, key=lambda z: z.high) if targets else None
        take = target.high if target else None
    if target is None:
        return None
    stop = smc_eval.floor_stop(direction, limit, raw_stop)
    plan = tp.limit_plan(direction, zone.low, zone.high, stop, take)
    if plan is None or plan.rr < MIN_RR:
        return None
    # Zelfde wacht als structure_live: een plan dat bij het ontstaan al voorbij doel of stop staat, of al in de zone, is geen kaart om op te wachten.
    if tp.plan_state(direction, zone.low, zone.high, stop, price, take=take) != "wacht":
        return None
    return {"direction": direction, "tf": zone.tf, "zone_key": zone.key, "zone_low": zone.low, "zone_high": zone.high,
            "limit": limit, "stop_loss": stop, "take_profit": take, "rr": plan.rr, "atr": zone.atr,
            "target_tf": target.tf, "target_low": target.low, "target_high": target.high,
            "distance_pct": _distance_pct(direction, zone, price)}


def plans(zones: list[ZoneLevel], price: float) -> list[dict]:
    return [p for d in ("long", "short") if (p := plan_for(d, zones, price))]


def walk(direction: str, limit: float, take: float, candles: pd.DataFrame) -> tuple[Optional[str], Optional[pd.Timestamp]]:
    """Wat er met een wachtende kaart gebeurde op deze candles (oudste eerst): ('filled', tijd) als de limiet geraakt werd, ('doel_geraakt', tijd)
    als de koers eerst het doel haalde, anders (None, None). Raakt één candle beide, dan telt de vulling: een order die daar stond is gevuld,
    en de uitkomst beslist level_check daarna, niet deze functie."""
    for c in candles.itertuples():
        if (c.low <= limit) if direction == "long" else (c.high >= limit):
            return "filled", c.timestamp
        if (c.high >= take) if direction == "long" else (c.low <= take):
            return "doel_geraakt", c.timestamp
    return None, None


def zone_text(direction: str, tf: str) -> str:
    return f"{'Vraagzone' if direction == 'long' else 'Aanbodzone'} {TF_TEXT.get(tf, tf)}"


def target_text(direction: str, tf: str) -> str:
    return f"{'aanbodzone' if direction == 'long' else 'vraagzone'} {TF_TEXT.get(tf, tf)}"


def radar_setup(row: dict) -> dict:
    """Een rij uit zone_radar_setups in de vorm die radar.setup_card leest (zoals web.main._with_preview voor SMC), met source zodat de kaart
    een eigen sleutel en tekst krijgt."""
    return {**row, "source": TRADE_TYPE, "preview_stop_loss": row["stop_loss"], "preview_take_profit": row["take_profit"]}
