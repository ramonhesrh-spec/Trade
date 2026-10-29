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
TF_TEXT = {"1h": "1u", "2h": "2u", "4h": "4u"}
# Vooraf gekozen, niet gemeten: 6% is wat een altcoin op een gewone dag of twee aflegt. Een zone verder weg is een kaart die dagen wacht en de
# Radar vult met plannen waar niemand vandaag iets mee doet; dichterbij dan dit is de zone een order die je nu kunt zetten.
MAX_DISTANCE_PCT = 6.0
# Zelfde buffer als de geteste stop 'zone_025' van de range sweep: net voorbij de buitenrand, buiten een wick die de zone alleen aantikt.
STOP_ATR = 0.25
MIN_RR = 2.0
# Een 4u-zone bleef 200 candles (33 dagen) actief: de steun van 24 september verdween daardoor op 28 oktober, anderhalve dag voordat de koers
# terugkwam en de CEO er met de hand op kocht (WLD, 29 oktober 2026). De 4u-zone leeft nu 400 candles (66 dagen), de 1u-zone blijft op 200 (8 dagen).
# Vooraf gekozen, niet afgesteld. Alleen de zone-radar: lab en range sweep houden ZONE_MAX_AGE.
MAX_AGE = {"1h": rs.ZONE_MAX_AGE, "4h": 2 * rs.ZONE_MAX_AGE}
# De candles die find_zones nodig heeft: de levensduur plus ruimte voor de ATR en de overlapregel, anders hangt welke zone telt af van waar het
# venster toevallig begint.
FETCH_LIMIT_BY_TF = {tf: age + 200 for tf, age in MAX_AGE.items()}
FETCH_LIMIT = max(FETCH_LIMIT_BY_TF.values())
MIN_CANDLES = 60


@dataclass(frozen=True)
class ZoneLevel:
    tf: str
    kind: str          # "bull" (vraagzone) of "bear" (aanbodzone), zoals rangesweep.Zone
    low: float
    high: float
    atr: float
    key: str           # tf, soort en openmoment van de order block-candle: dezelfde zone krijgt in elke cyclus dezelfde sleutel


def active_zones(bars: pd.DataFrame, tf: str, now: pd.Timestamp, max_age: Optional[int] = None) -> list[ZoneLevel]:
    """Zones die actief zijn op de candle na de laatst gesloten candle. De ATR is die van de laatst gesloten candle van dit timeframe.
    `max_age` (candles) is standaard de levensduur van de zone-radar (MAX_AGE); de zone-sweep geeft de geteste ZONE_MAX_AGE mee."""
    age = max_age or MAX_AGE.get(tf, rs.ZONE_MAX_AGE)
    closed = rs.closed_only(bars, now, tf)
    if len(closed) < MIN_CANDLES:
        return []
    b = add_indicators(closed).reset_index(drop=True)
    atr = float(b["atr"].iloc[-1])
    if not atr > 0:
        return []
    n = len(b)
    return [ZoneLevel(tf, z.kind, z.low, z.high, atr, f"{tf}:{z.kind}:{pd.Timestamp(b.at[z.ob_idx, 'timestamp']).isoformat()}")
            for z in rs.find_zones(b, age) if rs.zone_active(z, n, age)]


def _distance_pct(direction: str, z: ZoneLevel, price: float) -> float:
    return (price - z.high) / price * 100 if direction == "long" else (z.low - price) / price * 100


def plan_for(direction: str, zones: list[ZoneLevel], price: float) -> Optional[dict]:
    """Het plan voor de dichtstbijzijnde eigen zone, of None. Alleen die ene zone telt: valt hij af op het doel of de 2R, dan wordt er niet
    naar een verdere zone gezocht die wel past, anders kiest de code net zo lang tot er een kaart uitkomt."""
    own_kind = "bull" if direction == "long" else "bear"
    own = [z for z in zones if z.kind == own_kind and 0 < _distance_pct(direction, z, price) <= MAX_DISTANCE_PCT]
    if not own:
        return None
    zone = min(own, key=lambda z: (_distance_pct(direction, z, price), TFS.index(z.tf)))
    if direction == "long":
        limit, raw_stop = zone.high, zone.low - STOP_ATR * zone.atr
    else:
        limit, raw_stop = zone.low, zone.high + STOP_ATR * zone.atr
    target = target_for(direction, zones, price)
    if target is None:
        return None
    take = target_edge(direction, target)
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


def target_for(direction: str, zones: list[ZoneLevel], price: float) -> Optional[ZoneLevel]:
    """De eerstvolgende tegenovergestelde zone voorbij `price`: de laagste aanbodzone boven de koers (long), de hoogste vraagzone eronder (short)."""
    if direction == "long":
        targets = [z for z in zones if z.kind == "bear" and z.low > price]
        return min(targets, key=lambda z: z.low) if targets else None
    targets = [z for z in zones if z.kind == "bull" and z.high < price]
    return max(targets, key=lambda z: z.high) if targets else None


def target_edge(direction: str, target: ZoneLevel) -> float:
    """Het doel is de rand die de koers als eerste raakt."""
    return target.low if direction == "long" else target.high


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


def zone_origin(zone_key: str, tfs: tuple[str, ...] = TFS) -> Optional[tuple[str, str, int]]:
    """(tf, soort, openmoment in unix-seconden) uit de sleutel van ZoneLevel, of None als hij niet zo te lezen is. `tfs`: de timeframes die de
    aanroeper kent (de zone-sweep heeft ook 2u)."""
    parts = str(zone_key or "").split(":", 2)
    if len(parts) != 3 or parts[0] not in tfs or parts[1] not in ("bull", "bear"):
        return None
    try:
        ts = pd.Timestamp(parts[2])
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    # ZoneLevel schrijft de tijd van de beurs-candles, en die zijn UTC; een sleutel zonder tijdzone is dus ook UTC.
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
    return parts[0], parts[1], int(ts.timestamp())


# Wat de schermvullende grafiek als keuze heeft (web/static/levelchart.js, FULL_TFS). Een zone op een ander tijdframe (2u) opent op 1u.
CHART_TFS = ("15m", "1h", "4h")


def chart_zone(row: dict, tfs: tuple[str, ...] = TFS) -> Optional[dict]:
    """Wat de schermvullende grafiek over deze zone tekent en zegt: het tijdframe waarop hij ontstond, het openmoment van de order block-candle
    (None als de sleutel dat niet geeft), de doelzone en de uitleg in gewone taal. De uitleg zegt alleen wat find_zones eist."""
    origin = zone_origin(row.get("zone_key", ""), tfs)
    tf = origin[0] if origin else row.get("tf")
    if tf not in tfs:
        return None
    direction = row["direction"]
    tf_text = TF_TEXT[tf]
    if direction == "long":
        note = (f"De zone ontstond hier: na deze dalende {tf_text}-candle ging de koers sterk omhoog, binnen {rs.DISP_BARS} candles een slot "
                f"minstens {rs.DISP_ATR:g} ATR boven de top ervan. Het vlak is het bereik van die candle.")
    else:
        note = (f"De zone ontstond hier: na deze stijgende {tf_text}-candle ging de koers sterk omlaag, binnen {rs.DISP_BARS} candles een slot "
                f"minstens {rs.DISP_ATR:g} ATR onder de bodem ervan. Het vlak is het bereik van die candle.")
    has_target = row.get("target_low") is not None and row.get("target_high") is not None and row.get("target_tf") in tfs
    other_tf = (f"De markering staat op de plek van de {tf_text}-candle waar de zone ontstond. Kies {tf_text} om die candle zelf te zien."
                if tf in CHART_TFS else f"De markering staat op de plek van de {tf_text}-candle waar de zone ontstond; {tf_text} staat niet in de keuze.")
    return {
        "tf": tf, "kind": "bull" if direction == "long" else "bear", "label": zone_text(direction, tf),
        "origin": origin[2] if origin else None,
        "note": note if origin else None,
        "note_other_tf": other_tf,
        "note_outside": "De zone ontstond voor de eerste candle van deze grafiek. Kies een hoger tijdframe om te zien waar.",
        "target_low": row["target_low"] if has_target else None, "target_high": row["target_high"] if has_target else None,
        "target_label": f"Doelzone {TF_TEXT[row['target_tf']]}" if has_target else None,
    }


def radar_setup(row: dict) -> dict:
    """Een rij uit zone_radar_setups in de vorm die radar.setup_card leest (zoals web.main._with_preview voor SMC), met source zodat de kaart
    een eigen sleutel en tekst krijgt."""
    return {**row, "source": TRADE_TYPE, "preview_stop_loss": row["stop_loss"], "preview_take_profit": row["take_profit"],
            "chart_zone": chart_zone(row)}
