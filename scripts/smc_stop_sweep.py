"""Meet hoeveel speling de stop van een SMC-kans moet hebben (zie app/replay/smc_stops.py). Eén replay zonder stopafstand-toets en zonder
R:R-eis levert de ruwe signalen, daarna spelen we elke stopvariant uit op de 1m-candles, met train en test.
Draai: nohup python3 -u scripts/smc_stop_sweep.py --coins SOL,ETH,BNB --months 6 > /tmp/smcstop.txt 2>&1 &
Reken op ruim een uur per coin (dezelfde replay als scripts/replay_smc_report.py). Alleen lezen: raakt de database niet aan."""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, smc_eval  # noqa: E402
from app.replay import candles, smc_engine, smc_report, smc_stops  # noqa: E402


def _run_one(args):
    coin, frame, start, end, step, max_age = args
    # Zonder stopafstand-toets en zonder R:R-eis: elke setup die de afwijzing haalt wordt een ruw signaal, de varianten filteren daarna zelf.
    with mock.patch.object(config, "SMC_MIN_STOP_PCT", 0.0), mock.patch.object(smc_eval, "MIN_RISK_REWARD_RATIO", 0.0):
        signals = smc_engine.replay_smc(coin, {coin: frame}, frame, start, end, step, max_age, 0.03, 0.01)
    return coin, signals


def fmt(v) -> str:
    return f"{v:+.2f}" if v is not None else "-"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default="SOL,ETH,BNB")
    p.add_argument("--months", type=float, default=6)
    p.add_argument("--step-minutes", type=int, default=5)
    p.add_argument("--offset-minutes", type=int, default=3)
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    frames = {c: candles.load_candles(c, "1m") for c in coins}
    end = min(df["timestamp"].iloc[-1] for df in frames.values()) - pd.Timedelta(days=1)
    start = smc_report.first_step(end - pd.Timedelta(days=30 * a.months), a.step_minutes, a.offset_minutes)
    jobs = [(c, frames[c], start, end, pd.Timedelta(minutes=a.step_minutes), pd.Timedelta(hours=48)) for c in coins]
    signals = []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for coin, sigs in pool.map(_run_one, jobs):
            print(f"{coin}: {len(sigs)} ruwe signalen", flush=True)
            signals += sigs
    cut = start + (end - start) * 0.7
    print(f"\n{start:%Y-%m-%d} tot {end:%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}, kosten 0,08% per rondreis. R:R-eis van live blijft gelden.\n")
    print(f"{'stop minstens':<15}{'n':>6}{'winst':>7}{'verlies':>9}{'verlopen':>10}{'netto R':>9}{'train':>8}{'test':>8}")
    for r in smc_stops.sweep(signals, frames, cut):
        print(f"{r.floor:>12.1f}% {r.n:>6}{r.wins:>7}{r.losses:>9}{r.expired:>10}{fmt(r.avg_net):>9}{fmt(r.train):>8}{fmt(r.test):>8}   (n train {r.n_train}, test {r.n_test})")


if __name__ == "__main__":
    main()
