"""Backtest: hoeveel van je eigen historische day trading signalen zouden
elke nieuwe factor (ADX, volatiliteit, BTC-trend, 1u bevestiging,
divergentie, liquiditeit) gehaald hebben, als die toen al hadden
meegeteld.

Draai dit VOOR je ENABLE_ADVANCED_FACTORS=true zet in .env. De drempels
(ADX 20, ATR moet stijgen, 2 miljoen volume) zijn leerboek-standaarden,
nog niet getoetst aan jouw eigen signaalgeschiedenis. Dit script laat zien
hoe streng ze in de praktijk uitpakken voor precies de coins en momenten
waar jij al signalen op kreeg, voor je het systeem live zo streng zet.

Draai met: python3 scripts/backtest_factors.py [--limit 50]

Kost tijd: voor elk signaal wordt de historische candle-reeks van de coin
zelf (4u en 1u) en van BTC (4u) opnieuw opgehaald bij de exchange, reken
op een paar seconden per signaal.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app import config, db, exchange, indicators, repo


def _historical_df(coin: str, timeframe: str, before: datetime, candles_needed: int = 220) -> pd.DataFrame:
    """Candles die eindigen net voor `before`. ccxt haalt vooruit vanaf een
    startpunt (`since`), dus terugrekenen hoeveel historie nodig is en
    achteraf alles na `before` wegknippen."""
    exch = exchange.get_exchange()
    symbol = exchange.to_symbol(coin)
    tf_hours = {"1h": 1, "4h": 4}[timeframe]
    since = before - timedelta(hours=tf_hours * (candles_needed + 5))
    since_ms = int(since.timestamp() * 1000)
    raw = exch.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=candles_needed + 10)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[df["timestamp"] <= before]
    return df.tail(candles_needed).reset_index(drop=True)


def evaluate_signal(row: dict) -> dict:
    """Herberekent voor één historisch signaal of elke nieuwe factor
    geslaagd zou zijn. Waarde is True/False, of None als hij niet te
    berekenen was (bijvoorbeeld te weinig historie op dat moment)."""
    coin = row["coin"]
    direction = row["direction"]
    created_at = datetime.fromisoformat(row["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    results: dict = {}

    try:
        df = _historical_df(coin, "4h", created_at)
        if len(df) < 30:
            results["4u data"] = None
            return results
        ind = indicators.compute_indicators(df)
        results["ADX >= 20"] = ind.adx >= indicators.ADX_MIN
        results["ATR stijgend"] = ind.atr >= ind.atr_avg20
        _, div_ok, _ = indicators.check_divergence(df, direction)
        results["Geen divergentie"] = div_ok
    except Exception as exc:
        results["4u data"] = None
        print(f"    (4u data mislukt: {exc})")
        return results

    try:
        df_1h = _historical_df(coin, "1h", created_at)
        ind_1h = indicators.compute_indicators(df_1h)
        _, ok_1h, _ = indicators.check_1h_trend(direction, ind_1h)
        results["1u bevestiging"] = ok_1h
    except Exception as exc:
        results["1u bevestiging"] = None
        print(f"    (1u data mislukt: {exc})")

    if coin.upper() != "BTC":
        try:
            btc_df = _historical_df("BTC", "4h", created_at)
            btc_ind = indicators.compute_indicators(btc_df)
            _, btc_ok, _ = indicators.check_btc_trend(direction, btc_ind)
            results["BTC-trend"] = btc_ok
        except Exception as exc:
            results["BTC-trend"] = None
            print(f"    (BTC data mislukt: {exc})")

    # Liquiditeit: benadering. De exchange-ticker geeft alleen het HUIDIGE
    # 24u volume terug, geen historisch volume op een willekeurig moment
    # in het verleden. Benadert met candle-volume x slotkoers, opgeteld
    # over de laatste 6 4u-candles (=24u) uit de al opgehaalde reeks. Dat
    # is geen exacte quote-volume zoals de ticker geeft, maar een
    # redelijke indicatie van hoe liquide de coin op dat moment was.
    try:
        last6 = df.tail(6)
        approx_quote_volume = float((last6["volume"] * last6["close"]).sum())
        _, liq_ok, _ = indicators.check_liquidity(approx_quote_volume)
        results["Liquiditeit (benadering)"] = liq_ok
    except Exception as exc:
        results["Liquiditeit (benadering)"] = None
        print(f"    (liquiditeit mislukt: {exc})")

    return results


def main(limit: int) -> None:
    db.init_db()
    signals = repo.list_day_trading_signals_for_backtest(limit=limit)
    print(f"{len(signals)} historische day trading signalen gevonden, backtest start...\n")

    totals: dict[str, list[int]] = {}
    for i, row in enumerate(signals, 1):
        print(f"[{i}/{len(signals)}] {row['coin']} {row['direction']} ({row['created_at'][:16]})...")
        results = evaluate_signal(row)
        for factor, ok in results.items():
            if ok is None:
                continue
            totals.setdefault(factor, [0, 0])
            totals[factor][1] += 1
            if ok:
                totals[factor][0] += 1

    print("\n=== Resultaat ===")
    if not signals:
        print("Nog geen historische day trading signalen om op te toetsen.")
        return

    print(f"Van {len(signals)} historische signalen zou elke factor apart zijn doorgelaten:\n")
    for factor, (passed, total) in totals.items():
        pct = passed / total * 100 if total else 0
        print(f"  {factor:26s} {passed:>4}/{total:<4}  ({pct:5.1f}%)")

    print(
        "\nDit zijn de factoren los van elkaar. Trend/Momentum/1u bevestiging/BTC-trend\n"
        "tellen straks als groep (3 van 4 mag), de rest blijft allemaal apart hard vereist.\n"
        "Is een percentage hier al laag op zichzelf, dan wordt de combinatie van alles nog\n"
        "strenger. Zet ENABLE_ADVANCED_FACTORS=true in .env pas als deze cijfers je een\n"
        "redelijk beeld geven, niet een systeem dat vrijwel alles wegfiltert."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="hoeveel recente signalen meenemen")
    args = parser.parse_args()
    main(args.limit)
