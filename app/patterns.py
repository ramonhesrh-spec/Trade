"""Chart-patroonherkenning op de 4-uurs candle (config.TIMEFRAME): welk
patroon staat er nu, en wat is de bijbehorende entry/stop/target? Bouwt op
dezelfde pivot-detectie als indicators.detect_sr_zones/detect_trendlines
(indicators._find_pivots), zodat er geen tweede, afwijkende pivot-definitie
ontstaat. Zie docs/superpowers/specs/2026-09-22-patroonherkenning-design.md."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import ta

from app import indicators

# Hoe gelijk twee of drie pieken/dalen moeten zijn om als "hetzelfde
# niveau" te tellen. Crypto op de 4u-candle ligt zelden binnen 0.5%
# (SR_ZONE_CLUSTER_TOLERANCE_PCT), 2% is dichter bij hoe deze patronen er
# in de praktijk uitzien.
PEAK_TOLERANCE_PCT = 0.02

# Het hoofd moet minstens dit percentage verder uitsteken dan de
# schouders, anders is het gewoon een triple top/bottom met een
# toevallig randje.
HS_HEAD_MARGIN_PCT = 0.01

# Hoeveel candles na de nek-doorbraak op een geldige terugtest gewacht
# wordt (Task 4, find_entry_options) voordat de kans als vervlogen geldt.
# Zelfde orde-grootte als PENDING_LEVEL_MIN_AGE_MINUTES/4h-candles elders.
NECKLINE_RETEST_MAX_WAIT_CANDLES = 30

# Kleine marge voorbij de extreme van het patroon (top/hoofd/dal) zelf: een
# stop precies OP de extreme zou door een enkele wick al geraakt worden
# terwijl het patroon zelf nog geldig is. Zelfde soort kleine buffer als
# elders in het project (ATR_BUFFER_MULTIPLIER in risk.py), hier als vast
# percentage omdat een patroon-extreme geen eigen ATR-schaal heeft zoals
# een swing-niveau dat wel heeft.
PATTERN_STOP_MARGIN_PCT = 0.005


@dataclass
class PatternMatch:
    name: str
    direction: str  # "long" of "short"
    neckline: float  # of lijnwaarde bij channel_wedge
    extreme: float  # hoogste piek / laagste dal van het patroon zelf
    target: Optional[float]  # None bij divergence (geen gemeten beweging)
    stop_loss: Optional[float]  # None bij divergence
    confirmed_index: int  # candle-index waarop de nek/lijn daadwerkelijk doorbroken werd
    pattern_kind: str  # "top_bottom" | "hs" | "channel_wedge" | "divergence"


def _equal_enough(prices: list[float], tolerance_pct: float) -> bool:
    return (max(prices) - min(prices)) <= tolerance_pct * (sum(prices) / len(prices))


def _find_neckline_break(
    df: pd.DataFrame, after_index: int, neckline: float, kind: str, max_wait: int = 30,
) -> Optional[int]:
    """Eerste candle na het patroon zelf die de nek daadwerkelijk doorbreekt
    (close voorbij de nek, niet alleen een schaduw): zonder deze bevestiging
    is het patroon nooit 'af', slechts een vorm die nog kan mislukken."""
    window = df.iloc[after_index + 1:after_index + 1 + max_wait]
    for idx, row in window.iterrows():
        if kind == "high" and row["close"] < neckline:
            return idx
        if kind == "low" and row["close"] > neckline:
            return idx
    return None


def _pattern_stop_loss(extreme: float, direction: str) -> float:
    return extreme * (1 + PATTERN_STOP_MARGIN_PCT) if direction == "short" \
        else extreme * (1 - PATTERN_STOP_MARGIN_PCT)


def find_double_triple(df: pd.DataFrame, kind: str, n: int) -> list[PatternMatch]:
    """kind='high' -> double/triple top (bearish), kind='low' -> double/
    triple bottom (bullish). n=2 of n=3 pieken/dalen op ongeveer gelijke
    hoogte; de nek is de laagste/hoogste candle tussen de buitenste twee."""
    pivots = sorted([p for p in indicators._find_pivots(df) if p.kind == kind], key=lambda p: p.index)
    direction = "short" if kind == "high" else "long"
    matches = []
    for i in range(len(pivots) - n + 1):
        group = pivots[i:i + n]
        prices = [p.price for p in group]
        if not _equal_enough(prices, PEAK_TOLERANCE_PCT):
            continue
        start, end = group[0].index, group[-1].index
        between = df.iloc[start:end + 1]
        neckline = between["low"].min() if kind == "high" else between["high"].max()
        extreme = max(prices) if kind == "high" else min(prices)
        target = neckline - (extreme - neckline) if kind == "high" else neckline + (neckline - extreme)
        confirmed_index = _find_neckline_break(df, end, neckline, kind)
        if confirmed_index is not None:
            matches.append(PatternMatch(
                name=f"{'triple' if n == 3 else 'double'} {'top' if kind == 'high' else 'bottom'}",
                direction=direction, neckline=neckline, extreme=extreme,
                target=target, stop_loss=_pattern_stop_loss(extreme, direction),
                confirmed_index=confirmed_index, pattern_kind="top_bottom",
            ))
    return matches


def find_head_and_shoulders(df: pd.DataFrame, kind: str) -> list[PatternMatch]:
    """kind='high' -> head & shoulders (bearish), kind='low' -> inverse
    head & shoulders (bullish). Vijf afwisselende pivots nodig: schouder,
    dal, hoofd, dal, schouder (of gespiegeld). Het hoofd moet duidelijk
    verder uitsteken dan de twee schouders, de schouders moeten ongeveer
    gelijk zijn."""
    all_pivots = sorted(indicators._find_pivots(df), key=lambda p: p.index)
    direction = "short" if kind == "high" else "long"
    other = "low" if kind == "high" else "high"
    matches = []
    for i in range(len(all_pivots) - 4):
        window = all_pivots[i:i + 5]
        if [p.kind for p in window] != [kind, other, kind, other, kind]:
            continue
        shoulder1, trough1, head, trough2, shoulder2 = window
        if not _equal_enough([shoulder1.price, shoulder2.price], PEAK_TOLERANCE_PCT):
            continue
        head_beats_shoulders = (
            head.price > max(shoulder1.price, shoulder2.price) * (1 + HS_HEAD_MARGIN_PCT)
            if kind == "high" else
            head.price < min(shoulder1.price, shoulder2.price) * (1 - HS_HEAD_MARGIN_PCT)
        )
        if not head_beats_shoulders:
            continue
        neckline = max(trough1.price, trough2.price) if kind == "high" else min(trough1.price, trough2.price)
        target = neckline - (head.price - neckline) if kind == "high" else neckline + (neckline - head.price)
        confirmed_index = _find_neckline_break(df, shoulder2.index, neckline, kind)
        if confirmed_index is not None:
            matches.append(PatternMatch(
                name="head & shoulders" if kind == "high" else "inverse head & shoulders",
                direction=direction, neckline=neckline, extreme=head.price,
                target=target, stop_loss=_pattern_stop_loss(head.price, direction),
                confirmed_index=confirmed_index, pattern_kind="hs",
            ))
    return matches


def find_reversal_patterns(df: pd.DataFrame) -> list[PatternMatch]:
    """Alle bevestigde double/triple top/bottom- en head & shoulders-
    matches in dit candle-venster, nieuwste eerst niet gegarandeerd (zie
    caller: market_scanner pakt zelf de match met de hoogste
    confirmed_index)."""
    matches: list[PatternMatch] = []
    matches += find_double_triple(df, "high", 2)
    matches += find_double_triple(df, "low", 2)
    matches += find_double_triple(df, "high", 3)
    matches += find_double_triple(df, "low", 3)
    matches += find_head_and_shoulders(df, "high")
    matches += find_head_and_shoulders(df, "low")
    return matches
