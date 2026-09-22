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


def _win_rate(rows_with_outcome: list[str]) -> tuple[int, int, float]:
    """rows_with_outcome is een lijst auto_outcome-waarden ('take_profit',
    'stop_loss', 'vervallen', of None voor nog open) — 'vervallen' en nog
    open tellen niet mee, die hebben geen echte win/verlies-uitkomst.
    Geeft (wins, beslist_totaal, winrate%) terug."""
    decided = [o for o in rows_with_outcome if o in ("take_profit", "stop_loss")]
    wins = sum(1 for o in decided if o == "take_profit")
    pct = (wins / len(decided) * 100) if decided else 0.0
    return wins, len(decided), pct


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

    # Winrate van de HELE historische set, ongeacht of een factor al dan
    # niet berekend kon worden — dit is de baseline om de gefilterde
    # groepen hieronder tegen af te zetten.
    baseline_wins, baseline_decided, baseline_pct = _win_rate([s["auto_outcome"] for s in signals])
    still_open = sum(1 for s in signals if s["auto_outcome"] is None)
    expired = sum(1 for s in signals if s["auto_outcome"] == "vervallen")

    combined_pass = combined_total = 0
    # Per meetbare eis apart bijhouden welke signalen hem haalden/misten,
    # zodat de winrate PER EIS te vergelijken is — dat laat zien welke eis
    # daadwerkelijk winnaars van verliezers scheidt, en welke vooral
    # signalen wegfiltert zonder dat de winrate van de doorgelaten groep
    # merkbaar beter wordt.
    per_gate_pass: dict[str, list[str]] = {}
    per_gate_fail: dict[str, list[str]] = {}
    combined_pass_outcomes: list[str] = []
    combined_fail_outcomes: list[str] = []

    for row, results in zip(signals, results_list):
        outcome = row["auto_outcome"]
        for gate, ok in results.items():
            if ok is None:
                continue
            (per_gate_pass if ok else per_gate_fail).setdefault(gate, []).append(outcome)

        values = list(results.values())
        if any(v is None for v in values):
            continue  # niet volledig te berekenen, telt niet mee in de gecombineerde groep
        combined_total += 1
        if all(values):
            combined_pass += 1
            combined_pass_outcomes.append(outcome)
        else:
            combined_fail_outcomes.append(outcome)

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
    print(f"Gemiddeld {old_signals_per_day:.1f} signalen per dag onder de OUDE regels.")
    print(
        f"Winrate van ALLE {len(signals)} historische signalen samen: "
        f"{baseline_wins}/{baseline_decided} beslist ({baseline_pct:.1f}%), "
        f"{still_open} nog open, {expired} vervallen zonder uitkomst.\n"
    )

    print("=== Winrate per eis: haalt hij hem, of niet? ===")
    print("(laat zien of een eis daadwerkelijk winnaars van verliezers scheidt)\n")
    for gate in sorted(set(per_gate_pass) | set(per_gate_fail)):
        p_wins, p_decided, p_pct = _win_rate(per_gate_pass.get(gate, []))
        f_wins, f_decided, f_pct = _win_rate(per_gate_fail.get(gate, []))
        print(f"  {gate}")
        print(f"    haalt hem:  {p_wins}/{p_decided} gewonnen ({p_pct:.1f}%)")
        print(f"    haalt hem NIET: {f_wins}/{f_decided} gewonnen ({f_pct:.1f}%)")
        diff = p_pct - f_pct if p_decided and f_decided else None
        if diff is not None:
            oordeel = "onderscheidt duidelijk" if abs(diff) >= 10 else "maakt weinig verschil"
            print(f"    verschil: {diff:+.1f} procentpunt — {oordeel}\n")
        else:
            print("    (een van beide groepen te klein voor een zinvolle vergelijking)\n")

    if combined_total == 0:
        print("Geen enkel signaal had genoeg historische data om alle twee de meetbare eisen te herberekenen.")
        return

    combined_pct = combined_pass / combined_total * 100
    estimated_new_per_day = old_signals_per_day * (combined_pass / combined_total)
    pass_wins, pass_decided, pass_pct = _win_rate(combined_pass_outcomes)
    fail_wins, fail_decided, fail_pct = _win_rate(combined_fail_outcomes)

    print("=== Gecombineerd: allebei de meetbare eisen tegelijk ===")
    print(f"Van {combined_total} volledig herberekenbare signalen haalden er {combined_pass} ")
    print(f"ALLEBEI de meetbare nieuwe eisen (risico/rendement EN dagtrend/BTC-trend): {combined_pct:.1f}%.")
    print(f"Winrate van die doorgelaten groep: {pass_wins}/{pass_decided} ({pass_pct:.1f}%).")
    print(f"Winrate van de afgewezen groep:    {fail_wins}/{fail_decided} ({fail_pct:.1f}%).\n")
    print(f"Bovengrens voor het nieuwe aantal: ~{estimated_new_per_day:.1f} signalen per dag.")
    print(
        "\nDit aantal-per-dag is een BOVENGRENS, geen voorspelling: de zone-cooldown\n"
        "en de whiplash-rem in de marktscan zitten hier niet in (niet terug te\n"
        "rekenen op oude data, zie de uitleg bovenaan dit script) en kunnen het\n"
        "echte aantal alleen nog verder verlagen. De winrate-vergelijking hierboven\n"
        "is wel het echte antwoord op 'waar kan ik op verbeteren': een eis die\n"
        "weinig verschil maakt filtert vooral kansen weg zonder kwaliteit toe te\n"
        "voegen, dat is een kandidaat om te versoepelen. Draai dit script over een\n"
        "paar weken nog eens met verse signalen voor een preciezer beeld."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="hoeveel recente signalen meenemen")
    args = parser.parse_args()
    main(args.limit)
