"""Speelt de SMC-beslislogica (live: market_scanner._run_smc_check) af over
historische 1m-candles en rapporteert de trechter, de uitkomst in R, de
snelheid en de break-even kosten. Alleen lezen: raakt de database niet aan.

Draai met: python3 -u scripts/replay_smc_report.py --coins ETH,SOL --months 12
Opties: --step-minutes 5 --offset-minutes 3 --years-download 1.1 --refresh
        --workers 2 --fee-pct 0.1 --slippage-pct 0.05 --max-age-hours 48

Eerste keer downloadt hij 1m-candles (enkele minuten per coin). Reken op enkele uren
voor 7 coins met --workers 2 (ongeveer 45 tot 60 minuten rekentijd per coin; start met nice -n 10). Bij nohup: de voortgang wordt direct geflusht."""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles, smc_engine, smc_report  # noqa: E402

def _run_one(args):
    coin, frame, start, end, step, max_age, fee_pct, slippage_pct = args
    book = smc_engine.SmcBook()
    events: list = []
    signals = smc_engine.replay_smc(coin, {coin: frame}, frame, start, end, step, max_age, fee_pct, slippage_pct,
                                    events=events, book=book)
    return coin, signals, book.all_setups(), events


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.FIXED_COINS))
    p.add_argument("--months", type=float, default=12)
    p.add_argument("--step-minutes", type=int, default=5)
    p.add_argument("--offset-minutes", type=int, default=3)
    p.add_argument("--years-download", type=float, default=1.1)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--fee-pct", type=float, default=0.1)
    p.add_argument("--slippage-pct", type=float, default=0.05)
    p.add_argument("--max-age-hours", type=float, default=48)
    a = p.parse_args()

    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    base = {}
    for c in coins:
        print(f"{c}: 1m-candles ophalen (kan enkele minuten duren)...", flush=True)
        base[c] = candles.ensure_candles(c, a.years_download, refresh=a.refresh, timeframe="1m")
        df = base[c]
        print(f"{c}: {len(df)} candles, {df['timestamp'].iloc[0]:%Y-%m-%d} tot {df['timestamp'].iloc[-1]:%Y-%m-%d}", flush=True)

    end = min(df["timestamp"].iloc[-1] for df in base.values()) - pd.Timedelta(days=1)
    raw_start = end - pd.Timedelta(days=30 * a.months)
    try:
        start = smc_report.first_step(raw_start, a.step_minutes, a.offset_minutes)
    except ValueError as e:
        sys.exit(str(e))
    print(f"run van {start:%Y-%m-%d %H:%M} tot {end:%Y-%m-%d %H:%M}, stap {a.step_minutes} min\n", flush=True)

    step = pd.Timedelta(minutes=a.step_minutes)
    max_age = pd.Timedelta(hours=a.max_age_hours)
    jobs = [(c, base[c], start, end, step, max_age, a.fee_pct, a.slippage_pct) for c in coins]
    signals, setups, events = [], [], []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for coin, sigs, sets, evs in pool.map(_run_one, jobs):
            signals += sigs
            setups += sets
            events += evs
            print(f"{coin} klaar: {len(sigs)} signalen, {len(sets)} setups", flush=True)

    print(smc_report.format_smc_report(signals, setups, events, notes=smc_report.SMC_NOTES), flush=True)

    out_dir = Path(config.BASE_DIR) / "data" / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"smc_{datetime.now():%Y-%m-%d_%H%M%S}_{len(coins)}coins_{a.months:g}m.csv"
    rows = [{
        "coin": s.coin, "direction": s.direction, "at": s.at, "entry": s.entry, "stop": s.stop, "take": s.take,
        "result": s.outcome.result if s.outcome else None,
        "minutes": (s.outcome.exit_at - s.at).total_seconds() / 60 if s.outcome else None,
        "r_net": s.outcome.r_net if s.outcome else None, "r_gross": s.outcome.r_gross if s.outcome else None,
    } for s in signals]
    pd.DataFrame(rows, columns=["coin", "direction", "at", "entry", "stop", "take", "result", "minutes", "r_net", "r_gross"]).to_csv(out, index=False)
    print(f"\nSignalen opgeslagen in {out}", flush=True)

    setups_out = out.with_name(out.name.replace("smc_", "smc_setups_", 1))
    setup_cols = ["id", "coin", "direction", "zone_low", "zone_high", "structure_level", "sweep_price",
                  "liquidity_target", "atr", "created_at", "updated_at", "signal_id", "invalidated_at", "ended_because"]
    pd.DataFrame(setups, columns=setup_cols).to_csv(setups_out, index=False)
    print(f"Setups opgeslagen in {setups_out}", flush=True)


if __name__ == "__main__":
    main()
