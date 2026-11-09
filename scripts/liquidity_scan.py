"""Toetst sweeps op echte liquiditeitsniveaus (gisteren, vorige week, Azië-range) op de 1m-candles in data/candles,
met kosten, train en test en een controle op willekeurige momenten. Zie app/replay/liquidity_levels.py.
Draai: python3 scripts/liquidity_scan.py [--coins BTC,ETH,...]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import liquidity_levels as ll  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    p.add_argument("--fee-pct", type=float, default=0.02)
    p.add_argument("--slippage-pct", type=float, default=0.01)
    a = p.parse_args()
    all_trades, all_plac = [], []
    for coin in a.coins.split(","):
        frame = candle_cache.load_candles(coin, "1m")
        t = ll.run(frame, a.fee_pct, a.slippage_pct)
        if t.empty:
            continue
        t["coin"] = coin
        all_trades.append(t)
        all_plac.append(ll.placebo(frame, t, a.fee_pct, a.slippage_pct))
        print(f"{coin}: {len(t) // len(ll.RR_LIST)} sweeps", flush=True)
    trades, plac = pd.concat(all_trades, ignore_index=True), pd.concat(all_plac, ignore_index=True)
    cut = trades["at"].quantile(0.7)
    rows = ll.summarize(trades, plac, cut)
    print(f"\n{trades['at'].min():%Y-%m-%d} tot {trades['at'].max():%Y-%m-%d}, kosten {2 * (a.fee_pct + a.slippage_pct):.2f}% per rondreis, splitsing op {cut:%Y-%m-%d}")
    print(f"Mediaan stopafstand {trades['risk_pct'].median():.2f}%. Slaagt = netto positief in train en test, minstens 30 trades per helft\n")
    print(f"{'niveau':<8}{'take':>5}{'n':>6}{'winrate':>9}{'bruto R':>9}{'netto R':>9}{'train':>8}{'test':>8}{'placebo':>9}  slaagt")
    for r in sorted(rows, key=lambda r: (r.kind == "ALLES", r.kind, r.rr)):
        tr = f"{r.train_net:+.2f}" if r.train_net is not None else "-"
        te = f"{r.test_net:+.2f}" if r.test_net is not None else "-"
        print(f"{r.kind:<8}{r.rr:>5.1f}{r.n:>6}{r.winrate * 100:>8.0f}%{r.gross:>+9.2f}{r.net:>+9.2f}{tr:>8}{te:>8}{r.placebo_net:>+9.2f}  {'JA' if ll.passes(r) else ''}")
    print(f"\n{sum(ll.passes(r) for r in rows)} van {len(rows)} combinaties slagen. Bij zoveel combinaties zijn een paar toevallige treffers normaal.")


if __name__ == "__main__":
    main()
