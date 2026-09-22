"""Onderzoek: hoe vaak volgt de kanaal/wedge- en divergence-detectie uit
app/patterns.py daadwerkelijk de richting die het patroon impliceert,
tegen historische Binance-data. Zelfde bewijslast-aanpak als
scripts/research_reversal_patterns.py: geen patroon wordt vertrouwd op een
tekstboek-claim (het "70/30" van het patronenblad), alleen op wat
HesPulse's eigen historische data laat zien.

In tegenstelling tot research_reversal_patterns.py (dat patronen op de
VOLLEDIGE historische reeks in één keer zoekt) schuift dit script een
venster van SR_ZONE_LOOKBACK candles over de geschiedenis: kanaal/wedge/
divergence-detectie is venster-gebaseerd (indicators.detect_trendlines
werkt altijd op de laatste SR_ZONE_LOOKBACK candles), dus alleen zo'n
schuivend venster geeft een realistische "wat had HesPulse op moment X
gezien"-meting.

Kost tijd: haalt maanden tot jaren candles op bij de exchange, en schuift
daar per candle doorheen.

Draai met: python3 scripts/backtest_pattern_detection.py --coin BTC --timeframe 4h --years 1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import exchange, indicators, patterns

LOOKFORWARD_CANDLES = 20
SIDEWAYS_ATR_MULT = 1.0

# Elke Nde candle een nieuw venster nemen, niet elke candle: detect_trendlines
# is duur (O(pivots^2) kandidaat-lijnen) en een patroon verandert niet
# candle-voor-candle. 5 candles (bij 4u dus elke 20 uur) is vaak genoeg om
# elk patroon te vangen zonder het onderzoek onnodig te vertragen.
STEP_CANDLES = 5


def _atr(df, window: int = 14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    import pandas as pd
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def classify_outcome(df, match, atr_series, start_offset: int) -> str:
    """Zelfde soort target/invalidated/zijwaarts-classificatie als
    research_reversal_patterns.py, hier op de absolute candle-index in de
    volledige (niet-geschoven) df: start_offset + match.confirmed_index."""
    abs_index = start_offset + match.confirmed_index
    window = df.iloc[abs_index + 1:abs_index + 1 + LOOKFORWARD_CANDLES]
    if window.empty or match.target is None or match.stop_loss is None:
        return "onbekend"
    band = SIDEWAYS_ATR_MULT * atr_series.iloc[abs_index] if abs_index < len(atr_series) else 0.0
    invalidate_level = match.neckline
    for _, row in window.iterrows():
        if match.direction == "short":
            if row["low"] <= match.target:
                return "target_hit"
            if row["close"] > invalidate_level + band:
                return "invalidated"
        else:
            if row["high"] >= match.target:
                return "target_hit"
            if row["close"] < invalidate_level - band:
                return "invalidated"
    return "zijwaarts"


def run(coin: str, timeframe: str, years: float) -> None:
    candles_per_year = {"4h": 6 * 365, "1d": 365}[timeframe]
    limit = int(candles_per_year * years)
    full_df = exchange.fetch_ohlcv(coin, timeframe=timeframe, limit=limit)
    atr_series = _atr(full_df)

    by_name: dict[str, list[str]] = {}
    lookback = indicators.SR_ZONE_LOOKBACK
    start = lookback
    while start < len(full_df) - LOOKFORWARD_CANDLES:
        window = full_df.iloc[start - lookback:start].reset_index(drop=True)
        atr_now = atr_series.iloc[start - 1] if start - 1 < len(atr_series) else None
        if atr_now and atr_now == atr_now:  # niet NaN
            trendlines = indicators.detect_trendlines(window, atr_now)
            match = patterns.classify_channel_wedge(trendlines, len(window), atr_now)
            if match:
                outcome = classify_outcome(full_df, match, atr_series, start - lookback)
                by_name.setdefault(match.name, []).append(outcome)

            div_match = patterns.find_divergence(window)
            if div_match:
                # divergence heeft geen target/stop_loss, dus classify_outcome
                # kan hier niet direct op toegepast worden — meet in plaats
                # daarvan of de prijs binnen LOOKFORWARD_CANDLES in de
                # gemelde richting bewoog (eenvoudige richtings-tref-check).
                abs_index = (start - lookback) + div_match.confirmed_index
                fwd = full_df.iloc[abs_index + 1:abs_index + 1 + LOOKFORWARD_CANDLES]
                if not fwd.empty:
                    moved_right_way = (
                        fwd["close"].iloc[-1] > full_df["close"].iloc[abs_index]
                        if div_match.direction == "long" else
                        fwd["close"].iloc[-1] < full_df["close"].iloc[abs_index]
                    )
                    by_name.setdefault(div_match.name, []).append(
                        "target_hit" if moved_right_way else "invalidated"
                    )
        start += STEP_CANDLES

    print(f"{coin} {timeframe}, {len(full_df)} candles ({years} jaar)\n")
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
    parser.add_argument("--timeframe", default="4h", choices=["4h", "1d"])
    parser.add_argument("--years", type=float, default=1)
    args = parser.parse_args()
    run(args.coin, args.timeframe, args.years)
