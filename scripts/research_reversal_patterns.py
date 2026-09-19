"""Onderzoek: hoe vaak volgen omkeerpatronen (double/triple top/bottom,
head & shoulders, inverse head & shoulders) op de daily of 4u grafiek
daadwerkelijk de richting die het patroon impliceert, tegen jaren echte
Binance-data. Bouwt op dezelfde pivot-detectie als detect_sr_zones
(indicators._find_pivots), en dezelfde bewijslast-aanpak als
backtest_factors.py: geen factor wordt vertrouwd op een tekstboek-claim
(het "70/30" uit signalengroep-materiaal), alleen op wat HesPulse's eigen
historische data laat zien.

Drie uitkomsten per patroon, niet twee: naast "target gehaald" en
"ongeldig geworden" telt ook "zijwaarts, geen van beide" apart mee. Een
patroon dat vaak zijwaarts uitloopt is precies het scenario waarin niet
traden beter is dan wel traden, dus dat moet zichtbaar zijn in het
resultaat, niet wegvallen tussen de andere twee.

Kost tijd: haalt jaren daily, of maanden 4u-candles op bij de exchange.

Draai met: python3 scripts/research_reversal_patterns.py --coin BTC --timeframe 1d --years 4
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app import exchange
from app.indicators import _find_pivots

# Hoe gelijk twee of drie pieken/dalen moeten zijn om als "hetzelfde
# niveau" te tellen. Ruimer dan SR_ZONE_CLUSTER_TOLERANCE_PCT (0.005):
# een double top op de daily grafiek van crypto ligt zelden binnen 0.5%,
# 2% is dichter bij hoe deze patronen er in de praktijk uitzien.
PEAK_TOLERANCE_PCT = 0.02

# Het hoofd moet minstens dit percentage verder uitsteken dan de schouders,
# anders is het gewoon een triple top/bottom met een toevallig randje.
HS_HEAD_MARGIN_PCT = 0.01

# Hoeveel candles na de nek-doorbraak de uitkomst afgewacht wordt voor het
# patroon als "voltooid" geldt, target of niet.
LOOKFORWARD_CANDLES = 20

# Blijft de prijs binnen dit veelvoud van de ATR rond de nek hangen zonder
# het target te raken of duidelijk terug te draaien, dan telt dat als
# zijwaarts: geen van beide kanten heeft het gewonnen.
SIDEWAYS_ATR_MULT = 1.0


@dataclass
class PatternMatch:
    name: str
    direction: str  # "short" (bearish top-patroon) of "long" (bullish bottom-patroon)
    neckline: float
    extreme: float  # hoogste piek / laagste dal van het patroon zelf
    target: float
    confirmed_index: int  # candle-index waarop de nek daadwerkelijk doorbroken werd


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _equal_enough(prices: list[float], tolerance_pct: float) -> bool:
    return (max(prices) - min(prices)) <= tolerance_pct * (sum(prices) / len(prices))


def _find_neckline_break(
    df: pd.DataFrame, after_index: int, neckline: float, kind: str, max_wait: int = 30,
) -> int | None:
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


def find_double_triple(df: pd.DataFrame, kind: str, n: int) -> list[PatternMatch]:
    """kind='high' -> double/triple top (bearish), kind='low' -> double/
    triple bottom (bullish). n=2 of n=3 pieken/dalen op ongeveer gelijke
    hoogte; de nek is de laagste/hoogste candle tussen de buitenste twee."""
    pivots = sorted([p for p in _find_pivots(df) if p.kind == kind], key=lambda p: p.index)
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
                target=target, confirmed_index=confirmed_index,
            ))
    return matches


def find_head_and_shoulders(df: pd.DataFrame, kind: str) -> list[PatternMatch]:
    """kind='high' -> head & shoulders (bearish), kind='low' -> inverse
    head & shoulders (bullish). Vijf afwisselende pivots nodig: schouder,
    dal, hoofd, dal, schouder (of gespiegeld). Het hoofd moet duidelijk
    verder uitsteken dan de twee schouders, de schouders moeten ongeveer
    gelijk zijn."""
    all_pivots = sorted(_find_pivots(df), key=lambda p: p.index)
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
                target=target, confirmed_index=confirmed_index,
            ))
    return matches


def classify_outcome(df: pd.DataFrame, match: PatternMatch, atr: pd.Series) -> str:
    """target_hit / invalidated / zijwaarts, binnen LOOKFORWARD_CANDLES na
    de nek-doorbraak."""
    window = df.iloc[match.confirmed_index + 1:match.confirmed_index + 1 + LOOKFORWARD_CANDLES]
    if window.empty:
        return "onbekend"
    band = SIDEWAYS_ATR_MULT * atr.iloc[match.confirmed_index]
    for _, row in window.iterrows():
        if match.direction == "short":
            if row["low"] <= match.target:
                return "target_hit"
            if row["close"] > match.neckline + band:
                return "invalidated"
        else:
            if row["high"] >= match.target:
                return "target_hit"
            if row["close"] < match.neckline - band:
                return "invalidated"
    return "zijwaarts"


def run(coin: str, timeframe: str, years: float) -> None:
    candles_per_year = {"4h": 6 * 365, "1d": 365}[timeframe]
    limit = int(candles_per_year * years)
    df = exchange.fetch_ohlcv(coin, timeframe=timeframe, limit=limit)
    atr = _atr(df)

    all_matches: list[PatternMatch] = []
    all_matches += find_double_triple(df, "high", 2)
    all_matches += find_double_triple(df, "low", 2)
    all_matches += find_double_triple(df, "high", 3)
    all_matches += find_double_triple(df, "low", 3)
    all_matches += find_head_and_shoulders(df, "high")
    all_matches += find_head_and_shoulders(df, "low")

    print(f"{coin} {timeframe}, {len(df)} candles ({years} jaar), {len(all_matches)} bevestigde patronen\n")

    by_name: dict[str, list[str]] = {}
    for match in all_matches:
        outcome = classify_outcome(df, match, atr)
        by_name.setdefault(match.name, []).append(outcome)

    for name, outcomes in sorted(by_name.items()):
        total = len(outcomes)
        if total == 0:
            continue
        hit = outcomes.count("target_hit")
        invalid = outcomes.count("invalidated")
        sideways = outcomes.count("zijwaarts")
        print(
            f"{name}: {total} keer, target {hit} ({hit / total:.0%}), "
            f"ongeldig {invalid} ({invalid / total:.0%}), zijwaarts {sideways} ({sideways / total:.0%})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--coin", default="BTC")
    parser.add_argument("--timeframe", default="1d", choices=["4h", "1d"])
    parser.add_argument("--years", type=float, default=4)
    args = parser.parse_args()
    run(args.coin, args.timeframe, args.years)
