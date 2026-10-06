"""Toetst scalp-ideeën op 1m (BTC-voorsprong, uitputtingsminuten, taker-flow) met kosten, train en test en een controle op willekeurige
minuten. Zie app/replay/scalp.py. Draai: python3 scripts/scalp_scan.py [--coins BTC,ETH,...] [--no-flow]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import flow as flow_cache  # noqa: E402
from app.replay import scalp  # noqa: E402


def fmt(v) -> str:
    return f"{v:+.1f}" if v is not None else "-"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    p.add_argument("--no-flow", action="store_true", help="sla de taker-flow over (die haalt tot een uur aan data op)")
    a = p.parse_args()
    coins = a.coins.split(",")
    if "BTC" not in coins:
        coins = ["BTC"] + coins
    raw = {c: candle_cache.load_candles(c, "1m") for c in coins}
    frames = scalp.align(raw)
    index = next(iter(frames.values())).index
    cut = index[int(len(index) * 0.7)]
    flows = None
    if not a.no_flow:
        flows = {}
        for c in coins:
            print(f"{c}: taker-flow ophalen...", flush=True)
            flows[c] = flow_cache.ensure_flow(c, index[0], index[-1] + pd.Timedelta(minutes=1))
    parts = []
    for c in coins:
        t = scalp.run_coin(c, frames, cut, flows)
        if not t.empty:
            parts.append(t)
            print(f"{c}: {len(t) // (len(scalp.HORIZONS))} gebeurtenissen over alle varianten", flush=True)
    trades = pd.concat(parts, ignore_index=True)
    plac = scalp.placebo(frames, trades)
    rows = scalp.summarize(trades, plac, cut)
    print(f"\n{index[0]:%Y-%m-%d} tot {index[-1]:%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}. Kosten {scalp.COST_TAKER_BP:g} bp (marktorders) en {scalp.COST_MAKER_BP:g} bp (limietorders).")
    print("Slaagt = netto positief (6 bp) in train en test, minstens 30 per helft, brutorendement boven placebo, t per dag boven 2\n")
    print(f"{'test':<26}{'min':>4}{'n':>7}{'bruto bp':>10}{'netto6':>8}{'netto4':>8}{'train':>8}{'test':>8}{'t/dag':>7}{'placebo':>9}  slaagt")
    for r in sorted(rows, key=lambda r: (r.test, r.h)):
        print(f"{r.test:<26}{r.h:>4}{r.n:>7}{r.gross:>+10.1f}{r.net_taker:>+8.1f}{r.net_maker:>+8.1f}{fmt(r.train_net):>8}{fmt(r.test_net):>8}"
              f"{fmt(r.t_days):>7}{r.placebo_gross:>+9.1f}  {'JA' if scalp.passes(r) else ''}")
    print(f"\n{sum(scalp.passes(r) for r in rows)} van {len(rows)} combinaties slagen. Bij zoveel combinaties zijn een paar toevallige treffers normaal.")


if __name__ == "__main__":
    main()
