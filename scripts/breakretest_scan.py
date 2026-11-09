"""Toetst het break-en-retest recept (breuk van een lijn of range op 30m, terugkeer, ladder van doelen) op de 1m-candles in
data/candles, met kosten, train en test, een controle op willekeurige momenten en een t-waarde per dag.
Zie app/replay/breakretest.py. Draai: python3 scripts/breakretest_scan.py [--coins BTC,ETH,...]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import breakretest as br  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402


def fmt(v) -> str:
    return f"{v:+.2f}" if v is not None else "-"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    p.add_argument("--cost-pct", type=float, default=0.06, help="kosten per rondreis in procent")
    a = p.parse_args()
    all_trades, all_plac = [], []
    for coin in a.coins.split(","):
        frame = candle_cache.load_candles(coin, "1m")
        t = br.run(frame, a.cost_pct)
        if t.empty:
            continue
        t["coin"] = coin
        all_trades.append(t)
        all_plac.append(br.placebo(frame, t, a.cost_pct))
        print(f"{coin}: {len(t[(t['mode'] == 'RETEST') & (t['ladder'] == 'enkel 2R')])} retest-trades", flush=True)
    trades, plac = pd.concat(all_trades, ignore_index=True), pd.concat(all_plac, ignore_index=True)
    cut = trades["at"].quantile(0.7)
    print(f"\n{trades['at'].min():%Y-%m-%d} tot {trades['at'].max():%Y-%m-%d}, kosten {a.cost_pct:.2f}% per rondreis, splitsing op {cut:%Y-%m-%d}")
    print(f"Mediaan stopafstand {trades['risk_pct'].median():.2f}%. Slaagt = netto positief in train en test, minstens 30 trades per helft, beter dan placebo\n")
    print(f"{'soort':<7}{'instap':<8}{'uitgang':<15}{'n':>6}{'bruto R':>9}{'netto R':>9}{'train':>8}{'test':>8}{'t/dag':>7}{'placebo':>9}  slaagt")
    rows = sorted(br.summarize(trades, plac, cut), key=lambda r: (r.kind == "ALLES", r.kind, r.mode, r.ladder))
    for r in rows:
        print(f"{r.kind:<7}{r.mode:<8}{r.ladder:<15}{r.n:>6}{r.gross:>+9.2f}{r.net:>+9.2f}{fmt(r.train_net):>8}{fmt(r.test_net):>8}"
              f"{fmt(r.t_days_test):>7}{r.placebo_net:>+9.2f}  {'JA' if br.passes(r) else ''}")
    print(f"\n{sum(br.passes(r) for r in rows)} van {len(rows)} combinaties slagen. Bij zoveel combinaties zijn een paar toevallige treffers normaal.")
    print("\nKenmerken (RETEST, ladder 1-2-3R): n en netto R met kenmerk, dan zonder")
    for f in br.feature_table(trades, cut):
        tr, te = f["train"], f["test"]
        print(f"{f['kenmerk']:<24} train: ja {tr[0]:>4} {fmt(tr[1]):>6} | nee {tr[2]:>4} {fmt(tr[3]):>6}   test: ja {te[0]:>4} {fmt(te[1]):>6} | nee {te[2]:>4} {fmt(te[3]):>6}")


if __name__ == "__main__":
    main()
