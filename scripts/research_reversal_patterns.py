"""Onderzoek: hoe vaak volgen omkeerpatronen (double/triple top/bottom,
head & shoulders, inverse head & shoulders) op de daily of 4u grafiek
daadwerkelijk de richting die het patroon impliceert, tegen jaren echte
Binance-data. Detectielogica zelf staat in app/patterns.py (hergebruikt
door live signalering, zie app/market_scanner.py), dit script voegt alleen
de outcome-classificatie en het jaren-lange-historie-onderzoek toe.

Drie uitkomsten per patroon, niet twee: naast "target gehaald" en
"ongeldig geworden" telt ook "zijwaarts, geen van beide" apart mee.

Kost tijd: haalt jaren daily, of maanden 4u-candles op bij de exchange.

Draai met: python3 scripts/research_reversal_patterns.py --coin BTC --timeframe 1d --years 4
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app import exchange
from app.patterns import PatternMatch, find_double_triple, find_head_and_shoulders

# Hoeveel candles na de nek-doorbraak de uitkomst afgewacht wordt voor het
# patroon als "voltooid" geldt, target of niet.
LOOKFORWARD_CANDLES = 20

# Blijft de prijs binnen dit veelvoud van de ATR rond de nek hangen zonder
# het target te raken of duidelijk terug te draaien, dan telt dat als
# zijwaarts: geen van beide kanten heeft het gewonnen.
SIDEWAYS_ATR_MULT = 1.0


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def all_reversal_matches(df: pd.DataFrame) -> list[PatternMatch]:
    """Zelfde zes detectoren als patterns.find_reversal_patterns, maar over
    de VOLLEDIGE meegegeven historie. find_reversal_patterns zelf windowt op
    de laatste SR_ZONE_LOOKBACK candles (dat is wat live signalering nodig
    heeft, en het houdt confirmed_index vergelijkbaar met de andere
    detectoren) — hier is juist de hele historie het onderzoeksobject, en
    classify_outcome hieronder indexeert ook op diezelfde volledige df."""
    matches: list[PatternMatch] = []
    for n in (2, 3):
        matches += find_double_triple(df, "high", n)
        matches += find_double_triple(df, "low", n)
    matches += find_head_and_shoulders(df, "high")
    matches += find_head_and_shoulders(df, "low")
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

    all_matches = all_reversal_matches(df)

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
