"""Hogere tijdframes als kenmerk van een plan (B-2026-11-03-09, plan van aanpak punt 2.4). Alleen meting: geen motor, filter of melding leest
dit. Aanleiding: de analisten van de CEO zetten hun instap in een 12u- of dagzone (BTC 1u vPOC-short aan de onderkant van de H12 FVG van
mainachad, goud short vanaf premium van de dagrange, BTC-doel op een open prijs). Het model kijkt alleen naar 4u en lager.

Per plan, op het moment dat de app hem vastlegt, met alleen gesloten 12u- en dagcandles (de lopende dag- en weekopen zijn al bekend):
  zone_12u / zone_dag: de limiet ligt in een open FVG of in het order block van de laatste breuk in de richting van het plan
                       (app/structure_levels.py, dezelfde regels als Groot);
  premium_dag:         short boven het evenwicht van de dagrange, long eronder;
  open:                de limiet ligt binnen OPEN_PCT van de open van de lopende UTC-dag of ISO-week.
Een kenmerk zonder candles is None (onbekend), nooit False."""
from datetime import datetime, timezone
from typing import Optional

from app import structure_levels as sl

OPEN_PCT = 0.3              # vooraf vast, B-2026-11-03-09; nooit afstellen
NAMES = {"zone": "In een 12u- of dagzone (FVG of OB)", "premium_dag": "Premium van de dagrange", "open": "Bij de dag- of weekopen"}


def _in_zone(rows: Optional[list[list]], tf: str, now_s: float, direction: str, limit: float) -> Optional[bool]:
    if not rows:
        return None
    fr = sl._frame(rows, tf, now_s)
    if fr is None:
        return None
    if any(g["low"] <= limit <= g["high"] for g in sl.open_fvgs(fr)):
        return True
    obs = [z for z in sl.levels(rows, tf, now_s, bias=direction)["zones"] if z["kind"] == "ob"]
    return any(z["low"] <= limit <= z["high"] for z in obs)


def _premium(rows: Optional[list[list]], now_s: float, direction: str, limit: float) -> Optional[bool]:
    if not rows:
        return None
    eq = [l["value"] for l in sl.levels(rows, "1d", now_s)["lines"] if l["kind"] == "eq50"]
    if not eq:
        return None
    return limit > eq[0] if direction == "short" else limit < eq[0]


def _open(rows: Optional[list[list]], now_s: float, limit: float) -> Optional[bool]:
    """Dagopen en weekopen uit de dagcandles: de candle van vandaag (UTC) en die van de maandag van deze ISO-week."""
    if not rows:
        return None
    now = datetime.fromtimestamp(now_s, tz=timezone.utc)
    day0 = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())
    week0 = day0 - now.weekday() * 86400
    opens = {int(r[0]): float(r[1]) for r in rows}
    levels = [opens[t] for t in (day0, week0) if t in opens]
    if not levels:
        return None
    return any(abs(limit - o) / o * 100 <= OPEN_PCT for o in levels)


def features(direction: str, limit: float, rows_12h: Optional[list[list]], rows_1d: Optional[list[list]], now_s: float) -> dict:
    z12, zd = _in_zone(rows_12h, "12h", now_s, direction, limit), _in_zone(rows_1d, "1d", now_s, direction, limit)
    zone = True if (z12 or zd) else (None if z12 is None or zd is None else False)
    return {"zone_12u": z12, "zone_dag": zd, "zone": zone, "premium_dag": _premium(rows_1d, now_s, direction, limit),
            "open": _open(rows_1d, now_s, limit)}
