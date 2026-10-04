"""Diagnose: waarom komt een live signaal niet terug in het meetraam? Toont het
live signaal (prijs, stop, take, falende factoren) en daarnaast per stap van 15
minuten rond de aanmaaktijd wat het raam op dat moment beslist: richting,
voorfilter, bevestigd of niet, prijs, stop, take en de falende factoren.
Alleen lezen.

Draai met:
DATABASE_PATH=/opt/crypto-alerts/data/trading.db python3 scripts/replay_debug_signal.py --id 478
Opties: --hours-before 2 --hours-after 1 --step-minutes 15"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db, indicators, setup_eval  # noqa: E402
from app.replay import candles  # noqa: E402
from app.replay.engine import MIN_CANDLES  # noqa: E402
from app.replay.view import ReplayData  # noqa: E402
from app.signal_processor import full_confirmation_sync  # noqa: E402


def failing_factors(reason: str) -> str:
    parts = [p.split(":")[0].replace("✗ ", "") for p in (reason or "").split(" | ") if p.startswith("✗")]
    return ", ".join(parts) if parts else "-"


def evaluate_at(coin: str, base: dict, t: pd.Timestamp) -> dict:
    data = ReplayData(base, t)
    df = data.fetch_ohlcv(coin)
    if len(df) < MIN_CANDLES:
        return {"t": t, "note": "te weinig candles"}
    ind = indicators.compute_indicators(df)
    direction = "long" if ind.ema9 > ind.ema21 else "short"
    prefilter = bool(indicators.confirms_direction(ind, direction)[0])
    zones = indicators.detect_sr_zones(df)
    confirmation = full_confirmation_sync(coin, direction, df, ind, zones, True, data)
    evaluation = setup_eval.evaluate_day_trading_setup(direction, df, ind, zones, confirmation, lambda _price: False, [])
    return {
        "t": t, "direction": direction, "prefilter": prefilter, "confirmed": evaluation.confirmed,
        "price": ind.price, "stop": evaluation.stop_loss, "take": evaluation.take_profit,
        "failing": failing_factors(evaluation.reason),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--hours-before", type=float, default=2)
    p.add_argument("--hours-after", type=float, default=1)
    p.add_argument("--step-minutes", type=int, default=15)
    a = p.parse_args()

    db_file = Path(config.DATABASE_PATH)
    if not db_file.exists():
        sys.exit(f"Database niet gevonden op {db_file}. Zet DATABASE_PATH naar de productiedatabase.")
    with db.session() as conn:
        live = conn.execute(
            """SELECT id, coin, direction, trade_type, created_at, technical_confirmed, price, stop_loss, take_profit, reason
               FROM signals WHERE id = ?""", (a.id,)).fetchone()
    if live is None:
        sys.exit(f"Geen signaal met id {a.id}.")

    created = pd.Timestamp(live["created_at"]).tz_convert("UTC")
    print(f"LIVE #{live['id']} {live['coin']} {live['direction']} type={live['trade_type']} aangemaakt {created:%Y-%m-%d %H:%M}")
    print(f"  bevestigd (laatste stand): {bool(live['technical_confirmed'])}  prijs {live['price']:.4f}  "
          f"stop {live['stop_loss']:.4f}  take {live['take_profit']:.4f}")
    print(f"  falende factoren: {failing_factors(live['reason'])}\n")

    coin = live["coin"]
    base = {c: candles.load_candles(c) for c in sorted({coin, "BTC"})}
    cache_end = min(df["timestamp"].iloc[-1] for df in base.values())
    start = (created - pd.Timedelta(hours=a.hours_before)).floor(f"{a.step_minutes}min")
    end = created + pd.Timedelta(hours=a.hours_after)
    if cache_end < end:
        sys.exit(f"Candle-cache eindigt op {cache_end}, voor {end}. Draai eerst replay_compare_live.py met --refresh.")

    print(f"REPLAY {coin} (config.ENABLE_ADVANCED_FACTORS={config.ENABLE_ADVANCED_FACTORS})")
    print(f"{'tijd':<17}{'richting':<9}{'voorfilter':<11}{'bevestigd':<10}{'prijs':>11}{'stop':>11}{'take':>11}  falende factoren")
    t = start
    step = pd.Timedelta(minutes=a.step_minutes)
    while t <= end:
        r = evaluate_at(coin, base, t)
        if "note" in r:
            print(f"{t:%Y-%m-%d %H:%M}  {r['note']}")
        else:
            mark = "  <== aanmaaktijd live" if abs((t - created).total_seconds()) < a.step_minutes * 60 / 2 else ""
            print(f"{t:%Y-%m-%d %H:%M}  {r['direction']:<9}{str(r['prefilter']):<11}{str(r['confirmed']):<10}"
                  f"{r['price']:>11.4f}{r['stop']:>11.4f}{r['take']:>11.4f}  {r['failing']}{mark}")
        t += step


if __name__ == "__main__":
    main()
