"""Toetst trend plus pullback (4u en 1u trend, impuls op 15m, zone, bevestiging op 5m) op de 1m-candles in data/candles, met kosten, train en test en een spiegel als
controle. Zie app/replay/trendpullback.py. Draai: python3 scripts/trendpullback_scan.py [--coins BTC,ETH,...]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import trendpullback as tp  # noqa: E402


def fmt(v) -> str:
    return f"{v:+.2f}" if v is not None else "-"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    a = p.parse_args()
    parts = []
    for c in a.coins.split(","):
        t = tp.run(c, candle_cache.load_candles(c, "1m"))
        if not t.empty:
            parts.append(t)
        print(f"{c}: {len(t[(t['kind'] == 'mee') & (t['exit'] == '2R')])} instappen", flush=True)
    trades = pd.concat(parts, ignore_index=True)
    cut = trades["at"].quantile(0.7)
    print(f"\n{trades['at'].min():%Y-%m-%d} tot {trades['at'].max():%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}, kosten 0,06% per rondreis. Mediaan stopafstand {trades['risk_pct'].median():.2f}%.")
    print("Slaagt = mee, netto positief in train en test, minstens 30 per helft, t per dag boven 2. De spiegel is de controle.\n")
    print(f"{'kant':<10}{'uitgang':<9}{'n':>6}{'winrate':>9}{'bruto R':>9}{'netto R':>9}{'train':>8}{'test':>8}{'t/dag':>7}  slaagt")
    rows = tp.summarize(trades, cut)
    for r in sorted(rows, key=lambda r: (r.kind, r.exit)):
        print(f"{r.kind:<10}{r.exit:<9}{r.n:>6}{r.winrate * 100:>8.0f}%{r.gross:>+9.2f}{r.net:>+9.2f}{fmt(r.train):>8}{fmt(r.test):>8}{fmt(r.t_days):>7}  {'JA' if tp.passes(r) else ''}")
    mee = trades[(trades["kind"] == "mee") & (trades["exit"] == "2R")]
    print("\nMee, doel 2R, per coin:", ", ".join(f"{c} {g['r_net'].mean():+.2f}R (n {len(g)})" for c, g in mee.groupby("coin")))
    print("Mee, doel 2R, per kant:", ", ".join(f"{d} {g['r_net'].mean():+.2f}R (n {len(g)})" for d, g in mee.groupby("direction")))
    q = mee.groupby(mee["at"].dt.tz_localize(None).dt.to_period("Q"))["r_net"].agg(["mean", "count"])
    print("Mee, doel 2R, per kwartaal:", ", ".join(f"{k} {v['mean']:+.2f}R (n {int(v['count'])})" for k, v in q.iterrows()))


if __name__ == "__main__":
    main()
