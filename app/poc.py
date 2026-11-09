"""Point of control (POC): de prijs waar in een periode het meeste volume verhandeld werd, uit gesloten 5m-candles. Pure functies zonder
database of netwerk; de motor (app/poc_radar_live.py), de kaart (app/poc_radar.py) en de tests rekenen met dezelfde code.

Vaste regels, vooraf gekozen en nergens op afgesteld:
  - Bakken: breedte BIN_PCT (0,05%) van de open van de eerste candle van de periode, vanaf nul geteld, zodat dezelfde prijs altijd in dezelfde
    bak valt. Het volume van elke candle gaat gelijk verdeeld over alle bakken tussen zijn low en zijn high (de typische prijs zou een brede
    candle op één punt zetten).
  - POC: het midden van de bak met het meeste volume. Bij gelijke bakken de bak die het dichtst bij het slot van de periode ligt, daarna de laagste.
  - Periodes: elke gesloten UTC-dag en elke gesloten ISO-week (maandag 00:00 UTC) die begon binnen LOOKBACK (14 dagen). Nooit de lopende periode.
    Een periode telt alleen als de eerste en de laatste 5m-candle er zijn.
  - Naakt: geen gesloten 5m-candle na het einde van de periode had de POC tussen zijn low en high. Een lont die hem raakt telt als geraakt.

Eerlijk over wat dit is: een POC beschrijft waar volume lag, hij voorspelt niets. De POC-radar (trade_type 'poc_radar') is ongetest."""
import math
from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd

BIN_PCT = 0.05
BAR = pd.Timedelta(minutes=5)
LOOKBACK = pd.Timedelta(days=14)
PERIODS = ("day", "week")
LENGTH = {"day": pd.Timedelta(days=1), "week": pd.Timedelta(days=7)}
# Samenval met een andere kaart: de limiet ligt binnen deze afstand van een naakte POC. 0,3% vooraf gekozen: ruim binnen de kleinste stop
# (smc_eval.floor_stop), zodat een order op de limiet en een order op de POC voor wie handelt dezelfde order zijn.
NEAR_PCT = 0.3
_EPS = 1e-9          # 101,0 / 0,05 is in floating point 2019,999...; zonder dit valt een prijs op de rand in de bak eronder


@dataclass(frozen=True)
class PocLevel:
    period: str                         # "day" of "week"
    start: pd.Timestamp                 # begin van de periode (UTC)
    price: float                        # de POC
    touched_at: Optional[pd.Timestamp]  # eerste 5m-candle na de periode die hem raakte; None = naakt

    @property
    def end(self) -> pd.Timestamp:
        return self.start + LENGTH[self.period]

    @property
    def key(self) -> str:
        return key_of(self.period, self.start)

    @property
    def naked(self) -> bool:
        return self.touched_at is None


def key_of(period: str, start: pd.Timestamp) -> str:
    return f"{period}:{_utc(start).isoformat()}"


def _utc(ts) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _bin(price: float, width: float) -> int:
    return math.floor(price / width + _EPS)


def volume_profile(candles: pd.DataFrame, width: float) -> dict[int, float]:
    """Bakindex -> volume. Elke candle verdeelt zijn volume gelijk over de bakken van floor(low/w) tot en met floor(high/w)."""
    prof: dict[int, float] = {}
    for c in candles.itertuples():
        lo, hi = _bin(float(c.low), width), _bin(float(c.high), width)
        if hi < lo or not c.volume or c.volume <= 0:
            continue
        share = float(c.volume) / (hi - lo + 1)
        for k in range(lo, hi + 1):
            prof[k] = prof.get(k, 0.0) + share
    return prof


def poc_of(candles: pd.DataFrame) -> Optional[float]:
    """De POC van deze candles (oudste eerst), of None zonder candles of volume."""
    if candles.empty or not float(candles["open"].iloc[0]) > 0:
        return None
    width = float(candles["open"].iloc[0]) * BIN_PCT / 100
    prof = volume_profile(candles, width)
    if not prof:
        return None
    top = max(prof.values())
    close = float(candles["close"].iloc[-1])
    best = min((k for k, v in prof.items() if v == top), key=lambda k: (abs((k + 0.5) * width - close), k))
    return (best + 0.5) * width


def period_start(period: str, ts) -> pd.Timestamp:
    day = _utc(ts).floor("D")
    return day if period == "day" else day - pd.Timedelta(days=day.weekday())


def closed_starts(period: str, now) -> list[pd.Timestamp]:
    """Begin van elke gesloten periode die begon binnen LOOKBACK vóór het begin van vandaag, oudste eerst."""
    now = _utc(now)
    first = now.floor("D") - LOOKBACK
    start = period_start(period, first)
    if start < first:
        start += LENGTH[period]
    out = []
    while start + LENGTH[period] <= now:
        out.append(start)
        start += LENGTH[period]
    return out


def closed_only(candles: pd.DataFrame, now) -> pd.DataFrame:
    return candles[candles["timestamp"] + BAR <= _utc(now)]


def first_touch(level: PocLevel, candles: pd.DataFrame) -> Optional[pd.Timestamp]:
    """De eerste candle na het einde van de periode waarvan low tot high de POC bevat."""
    after = candles[(candles["timestamp"] >= level.end) & (candles["low"] <= level.price) & (candles["high"] >= level.price)]
    return pd.Timestamp(after["timestamp"].iloc[0]) if len(after) else None


def new_levels(candles: pd.DataFrame, now, known: set) -> list[PocLevel]:
    """De POC van elke gesloten periode in het venster die nog niet in `known` (sleutels) staat en volledig in deze candles zit, met zijn eerste
    aanraking daarna op dezelfde candles. Alleen gesloten 5m-candles tellen."""
    closed = closed_only(candles, now)
    out = []
    for period in PERIODS:
        for start in closed_starts(period, now):
            if key_of(period, start) in known:
                continue
            end = start + LENGTH[period]
            part = closed[(closed["timestamp"] >= start) & (closed["timestamp"] < end)]
            if part.empty or part["timestamp"].iloc[0] != start or part["timestamp"].iloc[-1] != end - BAR:
                continue
            price = poc_of(part.reset_index(drop=True))
            if price is None:
                continue
            level = PocLevel(period, start, price, None)
            out.append(PocLevel(period, start, price, first_touch(level, closed)))
    return out


def fetch_from(now, known: set, checked_until: Optional[pd.Timestamp]) -> pd.Timestamp:
    """Vanaf welke 5m-candle de motor moet ophalen: het begin van de oudste ontbrekende periode, en anders de candle na de laatst gecontroleerde.
    Nooit verder terug dan het venster."""
    now = _utc(now)
    floor = now.floor("D") - LOOKBACK
    froms = [s for p in PERIODS for s in closed_starts(p, now) if key_of(p, s) not in known]
    froms.append(_utc(checked_until) + BAR if checked_until is not None else floor)
    return max(floor, min(froms))


def near(price: float, levels: Iterable[PocLevel], pct: float = NEAR_PCT) -> bool:
    """Ligt `price` binnen pct procent van een naakte POC?"""
    return any(lv.naked and abs(price - lv.price) / lv.price * 100 <= pct for lv in levels)


def period_text(period: str, start) -> str:
    """'dag-POC 27 okt' of 'week-POC week 43': hoe een gebruiker het niveau terugvindt."""
    start = _utc(start)
    if period == "week":
        return f"week-POC week {start.isocalendar()[1]}"
    return f"dag-POC {start.day} {MONTHS[start.month - 1]}"


MONTHS = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")
