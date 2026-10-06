"""Toetst de sessie-ideeën (opening range van New York, sweep van de London-range, London-richting, uren van de dag) op de 1m-candles in data/candles.
Zie app/replay/sessions.py. Draai: python3 scripts/sessions_scan.py [--coins BTC,ETH,...]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import sessions  # noqa: E402


def fmt(v) -> str:
    return f"{v:+.2f}" if v is not None else "-"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    a = p.parse_args()
    frames = {c: candle_cache.load_candles(c, "1m") for c in a.coins.split(",")}
    rows, ln = [], []
    for c, f in frames.items():
        rows += sessions.orb_trades(c, f) + sessions.sweep_trades(c, f)
        ln.append(sessions.london_to_ny(c, f))
        print(f"{c}: klaar", flush=True)
    trades = pd.DataFrame(rows)
    cut = trades["at"].quantile(0.7)
    print(f"\n{trades['at'].min():%Y-%m-%d} tot {trades['at'].max():%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}, kosten 0,06% per rondreis.")
    print("Slaagt = netto positief in train en test, minstens 30 per helft, t per dag boven 2. De spiegel (omgekeerde kant) is de controle.\n")
    print(f"{'variant':<16}{'RR':>5}{'n':>6}{'winrate':>9}{'bruto R':>9}{'netto R':>9}{'train':>8}{'test':>8}{'t/dag':>7}  slaagt")
    res = sessions.summarize(trades, cut)
    for r in sorted(res, key=lambda r: (r["variant"], r["rr"])):
        print(f"{r['variant']:<16}{r['rr']:>5.1f}{r['n']:>6}{r['winrate'] * 100:>8.0f}%{r['gross']:>+9.2f}{r['net']:>+9.2f}{fmt(r['train']):>8}{fmt(r['test']):>8}"
              f"{fmt(r['t_days']):>7}  {'JA' if sessions.passes(r) else ''}")
    print(f"\n{sum(sessions.passes(r) for r in res)} van {len(res)} combinaties slagen.")

    lon = pd.concat(ln, ignore_index=True)
    print("\nLondon-richting tegenover New York (bp na 6 bp kosten, over coins en dagen):")
    print(f"{'variant':<20}{'n':>6}{'bruto bp':>10}{'netto bp':>10}{'train':>8}{'test':>8}{'t/dag':>7}")
    for name, g in lon.groupby("variant"):
        daily = g.groupby(g["at"].dt.floor("D"))["net_bp"].mean()
        t = daily.mean() / (daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 5 else float("nan")
        print(f"{name:<20}{len(g):>6}{g['gross_bp'].mean():>+10.1f}{g['net_bp'].mean():>+10.1f}{g[g['at'] < cut]['net_bp'].mean():>+8.1f}{g[g['at'] >= cut]['net_bp'].mean():>+8.1f}{t:>7.1f}")

    print("\nRendement per UTC-uur (bp, gemiddeld over coins), train en test met t-waarde. Bij 24 uren is |t| boven 3 pas opvallend:")
    hm = sessions.hour_map(frames, cut)
    print(f"{'uur':>4}{'train bp':>10}{'t':>7}{'test bp':>10}{'t':>7}  stabiel")
    for r in hm.itertuples():
        stable = r.train_t is not None and r.test_t is not None and np.sign(r.train_bp) == np.sign(r.test_bp) and abs(r.train_t) > 2 and abs(r.test_t) > 2
        print(f"{r.uur:>4}{r.train_bp:>+10.1f}{(r.train_t or 0):>7.1f}{r.test_bp:>+10.1f}{(r.test_t or 0):>7.1f}  {'JA' if stable else ''}")


if __name__ == "__main__":
    main()
