"""Automatische missers: grote omkeringen op gesloten 1u-candles die de markt liet zien, en of een live motor er rond het begin een kaart of
signaal voor had. Zuivere functies; ophalen en opslaan doet scripts/auto_misser.py.

Een beweging is een omkeer vanaf een bevestigd swing-punt (pivot) van minstens MIN_MOVE_ATR keer de ATR (1u) binnen MAX_MOVE_HOURS uur. Dit is
meting achteraf, geen detector voor een motor: het telt wat er te halen was, zodat de wekelijkse verbetersessie ziet welke regel weigerde.

Alle drempels liggen vooraf vast (2026-11-01) en worden niet op data afgesteld:
  - PIVOT_BARS 3: een swing-punt is het laagste (hoogste) punt van zichzelf en drie candles ervoor en erna, en telt pas als die drie candles erna
    gesloten zijn. Drie op 1u is gangbaar en gelijk aan de pivot van de andere detectoren in app/replay.
  - MIN_MOVE_ATR 3: drie keer de gewone uurbeweging; een zone-radar- of structuurtrade met een stop van ongeveer een ATR haalt dan minstens 2R.
  - MAX_MOVE_HOURS 24: een daytrade; wat er langer over doet is een swing.
  - SEEN_WINDOW 12 uur: een kaart of signaal tot twaalf uur voor of na het begin telt als gezien (zelfde venster als scripts/misser_check.py).
Een beweging die eerst voorbij het swing-punt terugging, begint daar niet: de meting stopt bij de eerste candle die het swing-punt doorbreekt."""
from datetime import timedelta
from typing import Iterable, Optional

import pandas as pd

from app.replay.lab import add_indicators

TF = "1h"
BAR = pd.Timedelta(hours=1)
PIVOT_BARS = 3
MIN_MOVE_ATR = 3.0
MAX_MOVE_HOURS = 24
SEEN_WINDOW = timedelta(hours=12)
LOOKBACK_HOURS = 24
# De motoren die de misser-controle per beweging langsloopt: de focus-soorten. structuur_c is dezelfde motor als structuur.
ENGINES = ("structuur", "zone_radar", "zone_sweep", "poc_radar", "hespulse_model")
# Zone-radar en POC-radar hebben geen diagnose in scripts/misser_check.py; hier alleen de vraag of hun niveau bij het beginpunt lag.
ZONE_NEAR_ATR = 0.25          # dezelfde buffer als de stop van de zone-radar (zone_radar.STOP_ATR): een prik net door de rand telt nog als in de zone


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t


def find_moves(bars: pd.DataFrame, now, lookback_hours: float = LOOKBACK_HOURS) -> list[dict]:
    """Bewegingen waarvan de eindcandle sloot binnen de laatste `lookback_hours` vóór `now`. Alleen gesloten candles (open + 1u <= now)."""
    now = _ts(now)
    closed = bars[bars["timestamp"] + BAR <= now].reset_index(drop=True)
    n = len(closed)
    if n < 2 * PIVOT_BARS + 15:
        return []
    b = add_indicators(closed)
    lows, highs, atrs, stamps = b["low"].to_numpy(), b["high"].to_numpy(), b["atr"].to_numpy(), b["timestamp"]
    since = now - pd.Timedelta(hours=lookback_hours)
    found = []
    for i in range(PIVOT_BARS, n - PIVOT_BARS):
        atr = atrs[i]
        if not atr > 0:
            continue
        lo_win, hi_win = lows[i - PIVOT_BARS:i + PIVOT_BARS + 1], highs[i - PIVOT_BARS:i + PIVOT_BARS + 1]
        for direction in ("long", "short"):
            if direction == "long":
                if lows[i] > lo_win.min() or (lows[i - PIVOT_BARS:i] == lows[i]).any():
                    continue
            elif highs[i] < hi_win.max() or (highs[i - PIVOT_BARS:i] == highs[i]).any():
                continue
            move = _measure(direction, i, lows, highs, n)
            if move is None:
                continue
            end, extreme = move
            begin = lows[i] if direction == "long" else highs[i]
            size = abs(extreme - begin)
            if size / atr < MIN_MOVE_ATR:
                continue
            end_close = _ts(stamps.iloc[end]) + BAR
            if not since < end_close <= now:
                continue
            found.append({"direction": direction, "begin_at": _ts(stamps.iloc[i]).isoformat(), "end_at": _ts(stamps.iloc[end]).isoformat(),
                          "begin_price": float(begin), "end_price": float(extreme), "atr": float(atr), "size_atr": float(size / atr),
                          "size_pct": float((extreme - begin) / begin * 100) if direction == "long" else float((begin - extreme) / begin * 100)})
    return _dedupe(found)


def _measure(direction: str, i: int, lows, highs, n: int) -> Optional[tuple[int, float]]:
    """(index van de extreme candle, extreme) binnen MAX_MOVE_HOURS na het swing-punt, tot de eerste candle die het swing-punt doorbreekt."""
    best, best_j = None, None
    for j in range(i + 1, min(n, i + 1 + MAX_MOVE_HOURS)):
        if (lows[j] < lows[i]) if direction == "long" else (highs[j] > highs[i]):
            break
        value = highs[j] if direction == "long" else lows[j]
        if best is None or (value > best if direction == "long" else value < best):
            best, best_j = value, j
    return None if best_j is None else (best_j, float(best))


def _dedupe(moves: list[dict]) -> list[dict]:
    """Twee swing-punten in dezelfde beweging zijn één beweging: de grootste blijft, een begin binnen een al gehouden beweging valt af."""
    kept: list[dict] = []
    for m in sorted(moves, key=lambda m: -m["size_atr"]):
        if any(k["direction"] == m["direction"] and k["begin_at"] <= m["begin_at"] <= k["end_at"] for k in kept):
            continue
        kept.append(m)
    return sorted(kept, key=lambda m: m["begin_at"])


def seen_by(move: dict, rows: Iterable[dict]) -> list[str]:
    """De bronnen (motor of signaal) met een kaart of signaal voor deze richting binnen SEEN_WINDOW van het begin. rows: source, direction, at."""
    begin = _ts(move["begin_at"])
    return sorted({r["source"] for r in rows if r["direction"] == move["direction"] and abs(_ts(r["at"]) - begin) <= SEEN_WINDOW})


def zone_reason(direction: str, zones, begin_price: float) -> str:
    """Zone-radar: lag er bij het beginpunt een actieve eigen zone (vraag voor long, aanbod voor short)? zones: zone_radar.ZoneLevel van vóór het begin."""
    kind, word = ("bull", "vraagzone") if direction == "long" else ("bear", "aanbodzone")
    own = [z for z in zones if z.kind == kind]
    if any(z.low - ZONE_NEAR_ATR * z.atr <= begin_price <= z.high + ZONE_NEAR_ATR * z.atr for z in own):
        return f"zone_radar: actieve {word} bij het beginpunt, maar geen kaart (al eerder een kaart voor die zone, dagcap of een wachtende kaart)"
    if not own:
        return f"zone_radar: geen actieve {word} op 1u of 4u"
    dist = min(min(abs(begin_price - z.low), abs(begin_price - z.high)) / begin_price * 100 for z in own)
    return f"zone_radar: geen actieve {word} bij het beginpunt (dichtstbij {dist:.1f}% ervandaan)".replace(".", ",", 1)


def poc_reason(direction: str, levels, begin_price: float, begin_at) -> str:
    """POC-radar: lag er een naakte POC, bekend vóór het begin, binnen poc.NEAR_PCT van het beginpunt? Naakt bij het begin: nog niet geraakt, of pas
    geraakt in het uur van het begin zelf (dat is de aanraking die de beweging startte)."""
    from app import poc
    begin = _ts(begin_at)
    known = [lv for lv in levels if lv.end <= begin and (lv.touched_at is None or _ts(lv.touched_at) >= begin - BAR)]
    if any(abs(begin_price - lv.price) / lv.price * 100 <= poc.NEAR_PCT for lv in known):
        return "poc_radar: naakte POC bij het beginpunt, maar geen kaart (dagcap, al een kaart voor dat niveau of verder dan 6% bij de scan)"
    return "poc_radar: geen naakte POC bij het beginpunt"


STATUS_WORDS = {"wacht_sweep": "wachtte op een sweep van de pool", "prik": "zag een prik maar nog geen slot terug", "wacht_shift": "wachtte op de breuk",
                "wacht_fvg": "wachtte op displacement met een gap", "context_weg": "verloor zijn 4u-context", "geen_pool": "had geen pool meer",
                "afgerond": "had een plan"}


def model_reason(direction: str, day: Optional[str], scs: list[dict], counter: list[dict], begin_at) -> str:
    """M4 (B-2026-11-03-12): waarom het HesPulse-model een beweging niet zag, uit een herberekening op de candles tot SEEN_WINDOW na het begin.
    day: de dagrichting bij het begin (model.DailyBias). scs/counter: model.scenarios zonder en met counter=True."""
    begin = _ts(begin_at)
    near = lambda rows: [s for s in rows if s["direction"] == direction and abs(_ts(s["discovered_at"]) - begin) <= SEEN_WINDOW]
    own, tegen = near(scs), near(counter)
    if any(s.get("entry") for s in own):
        return "hespulse_model: de herberekening vindt een plan, live kwam er geen (te laat opgeslagen of een storing)"
    if own:
        return f"hespulse_model: scenario in deze richting, maar het {STATUS_WORDS.get(own[-1]['status'], own[-1]['status'])}"
    if day is None:
        return "hespulse_model: nog geen dagbreuk, dus geen richting"
    if day != direction:
        word = "alleen in de stille arm tegen de dagtrend" if tegen else "ook niet in de stille arm tegen de dagtrend"
        return f"hespulse_model: de dag wees {day}; het model zocht {direction} {word}"
    return "hespulse_model: geen 4u-range met een onaangeraakte pool binnen 6% in deze richting"


def unseen(rows: list[dict]) -> list[dict]:
    """De echte missers: bewegingen die geen enkele motor zag."""
    return [r for r in rows if not r.get("seen_by")]
