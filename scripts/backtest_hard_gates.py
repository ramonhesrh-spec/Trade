"""Backtest: hoeveel van je eigen historische day trading signalen zouden
de VIER nieuwe harde eisen uit de kritischere-signaaltoetsing-ronde
gehaald hebben (risico/rendement, dagtrend, BTC-trend-met-vlakke-
uitzondering), als die toen al hadden gegolden.

Draai met: python3 scripts/backtest_hard_gates.py [--limit 50]

BELANGRIJKE BEPERKING: twee van de vier nieuwe eisen zijn NIET
terug te rekenen op oude signalen en ontbreken hier expres:
- Zone-cooldown (recent gefaalde zelf-gedetecteerde zone blokkeert 3
  dagen): dit leest `sr_zone_failures`, een tabel die pas sinds deze
  ronde gevuld wordt. Voor signalen van vóór deze ronde is er geen
  geschiedenis om op te toetsen.
- Whiplash-rem in de marktscan (richting moet 2 scan-cycli op rij
  aanhouden): dit hangt af van de exacte scan-voor-scan-geschiedenis op
  het moment zelf, die nergens is vastgelegd.

Dit script rekent dus alleen de twee eisen door die wél uit de opgeslagen
signaal-data en historische candles te herleiden zijn: risico/rendement
(rechtstreeks uit het opgeslagen price/stop_loss/take_profit, geen
exchange-aanroep nodig) en de dagtrend-eis (dagtrend van de coin zelf,
met de vlakke-markt-uitzondering via btc_is_flat) en BTC-trend (met
dezelfde vlakke-markt-uitzondering). Het aantal hieronder is dus een
BOVENGRENS: de twee ontbrekende eisen kunnen het echte aantal alleen nog
verder verlagen, nooit verhogen.

Kost tijd: voor elk signaal wordt de historische daily-candle-reeks van de
coin zelf en van BTC opnieuw opgehaald bij de exchange (risico/rendement
zelf kost geen aparte aanroep), reken op een paar seconden per signaal.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app import db, exchange, indicators, repo
from app.signal_processor import MIN_RISK_REWARD_RATIO


def _historical_daily_df(coin: str, before: datetime, candles_needed: int = 60) -> pd.DataFrame:
    """Zelfde aanpak als scripts/backtest_factors.py's _historical_df,
    hier alleen voor de dagcandle nodig: candles die eindigen net vóór
    `before`, ccxt haalt vooruit vanaf `since` dus achteraf wegknippen."""
    exch = exchange.get_exchange()
    symbol = exchange.to_symbol(coin)
    since = before - timedelta(hours=24 * (candles_needed + 5))
    since_ms = int(since.timestamp() * 1000)
    raw = exch.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=candles_needed + 10)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[df["timestamp"] <= before]
    return df.tail(candles_needed).reset_index(drop=True)


def evaluate_signal(row: dict) -> dict:
    """Herberekent voor één historisch signaal of elke meetbare nieuwe
    harde eis geslaagd zou zijn. Waarde is True/False, of None als hij
    niet te berekenen was (te weinig historie op dat moment)."""
    coin = row["coin"]
    direction = row["direction"]
    created_at = datetime.fromisoformat(row["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    results: dict = {}

    # Risico/rendement: rechtstreeks uit de al opgeslagen niveaus, geen
    # exchange-aanroep nodig. Zelfde formule als signal_processor.py.
    if row["price"] is not None and row["stop_loss"] is not None and row["take_profit"] is not None:
        risk_distance = abs(row["price"] - row["stop_loss"])
        reward_distance = abs(row["take_profit"] - row["price"])
        ratio = (reward_distance / risk_distance) if risk_distance else 0.0
        results["Risico/rendement (min 1.5:1)"] = ratio >= MIN_RISK_REWARD_RATIO
    else:
        results["Risico/rendement (min 1.5:1)"] = None

    try:
        daily_df = _historical_daily_df(coin, created_at)
        if len(daily_df) < 20:
            results["Dagtrend"] = None
        else:
            daily_ind = indicators.compute_indicators(daily_df)
            if indicators.btc_is_flat(daily_ind):
                results["Dagtrend"] = True  # vlakke-markt-uitzondering: geen blokkade
            else:
                _, daily_ok, _ = indicators.check_daily_trend(direction, daily_ind)
                results["Dagtrend"] = daily_ok
    except Exception as exc:
        results["Dagtrend"] = None
        print(f"    (dagtrend-data mislukt: {exc})")

    if coin.upper() != "BTC":
        try:
            btc_daily_df = _historical_daily_df("BTC", created_at)
            if len(btc_daily_df) < 20:
                results["BTC-trend"] = None
            else:
                btc_ind = indicators.compute_indicators(btc_daily_df)
                if indicators.btc_is_flat(btc_ind):
                    results["BTC-trend"] = True
                else:
                    _, btc_ok, _ = indicators.check_btc_trend(direction, btc_ind)
                    results["BTC-trend"] = btc_ok
        except Exception as exc:
            results["BTC-trend"] = None
            print(f"    (BTC-data mislukt: {exc})")

    return results


def main(limit: int) -> None:
    db.init_db()
    signals = repo.list_day_trading_signals_for_backtest(limit=limit)
    print(f"{len(signals)} historische day trading signalen gevonden, backtest start...\n")

    if not signals:
        print("Nog geen historische day trading signalen om op te toetsen.")
        return

    results_list = []
    for i, row in enumerate(signals, 1):
        print(f"[{i}/{len(signals)}] {row['coin']} {row['direction']} ({row['created_at'][:16]})...")
        results_list.append(evaluate_signal(row))

    combined_pass = combined_total = 0
    for results in results_list:
        values = list(results.values())
        if any(v is None for v in values):
            continue  # niet volledig te berekenen, telt niet mee
        combined_total += 1
        if all(values):
            combined_pass += 1

    oldest = datetime.fromisoformat(signals[-1]["created_at"])
    newest = datetime.fromisoformat(signals[0]["created_at"])
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    span_days = max((newest - oldest).total_seconds() / 86400, 1.0)
    old_signals_per_day = len(signals) / span_days

    print("\n=== Resultaat ===")
    print(f"Periode: {oldest.date()} t/m {newest.date()} ({span_days:.1f} dagen)")
    print(f"Gemiddeld {old_signals_per_day:.1f} signalen per dag onder de OUDE regels.\n")

    if combined_total == 0:
        print("Geen enkel signaal had genoeg historische data om alle twee de meetbare eisen te herberekenen.")
        return

    combined_pct = combined_pass / combined_total * 100
    estimated_new_per_day = old_signals_per_day * (combined_pass / combined_total)

    print(f"Van {combined_total} volledig herberekenbare signalen haalden er {combined_pass} ")
    print(f"ALLEBEI de meetbare nieuwe eisen (risico/rendement EN dagtrend/BTC-trend): {combined_pct:.1f}%.\n")
    print(f"Bovengrens voor het nieuwe aantal: ~{estimated_new_per_day:.1f} signalen per dag.")
    print(
        "\nDit is een BOVENGRENS, geen voorspelling: de zone-cooldown en de\n"
        "whiplash-rem in de marktscan zitten hier niet in (niet terug te rekenen op\n"
        "oude data, zie de uitleg bovenaan dit script) en kunnen het echte aantal\n"
        "alleen nog verder verlagen. Draai dit script over een paar weken nog eens\n"
        "met verse signalen (die ook echt door de zone-cooldown en whiplash-rem\n"
        "heen zijn gegaan) voor een preciezer beeld."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="hoeveel recente signalen meenemen")
    args = parser.parse_args()
    main(args.limit)
