"""Signaalonderzoek op alle 5-minuten-momenten (zie app/replay/signal_model.py): welke kenmerken voorspellen het rendement van de komende 15, 30
en 60 minuten, en wat levert een model daarvan na kosten op? Haalt waar nodig het taker-volume op (cache in data/candles).
Draai: python3 scripts/signal_research.py [--coins BTC,ETH,...] [--cost-bps 6] [--permutations 200]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import flow, signal_model as sm  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    p.add_argument("--cost-bps", type=float, default=6.0)
    p.add_argument("--top", type=float, default=0.05)
    p.add_argument("--permutations", type=int, default=200)
    a = p.parse_args()
    coins = a.coins.split(",")
    frames, flows = {}, {}
    for c in coins:
        frames[c] = candle_cache.load_candles(c, "1m")
        print(f"{c}: taker-volume ophalen...", flush=True)
        flows[c] = flow.ensure_flow(c, frames[c]["timestamp"].iloc[0], frames[c]["timestamp"].iloc[-1] + pd.Timedelta(minutes=1))
    btc = sm.build_panel(frames["BTC"], flows["BTC"]) if "BTC" in coins else None
    panels = []
    for c in coins:
        panel = sm.build_panel(frames[c], flows[c], btc)
        panel["coin"] = c
        panels.append(panel)
        print(f"{c}: {len(panel)} candles", flush=True)
    panel = pd.concat(panels, ignore_index=True)
    cut = panel["at"].quantile(0.7)
    print(f"\n{len(panel)} 5m-momenten, {panel['at'].min():%Y-%m-%d} tot {panel['at'].max():%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}, kosten {a.cost_bps:.0f} bp per rondreis")

    print("\nStap 1: rang-correlatie (IC) van elk kenmerk met het rendement erna. Een voorspeller telt als train en test dezelfde kant op wijzen en |t| boven 3 is.")
    print(f"{'kenmerk':<10}{'uit':>5}{'IC train':>10}{'IC test':>9}{'t test':>8}{'n test':>9}  gelijk teken  sterk")
    rows = sm.information_coefficients(panel, cut)
    for r in sorted(rows, key=lambda r: -abs(r.t_test) if r.t_test == r.t_test else 0):
        same = r.ic_train * r.ic_test > 0
        print(f"{r.feature:<10}{r.horizon:>5}{r.ic_train:>+10.4f}{r.ic_test:>+9.4f}{r.t_test:>8.1f}{r.n_test:>9}  {'ja' if same else 'nee':<12}  {'JA' if same and abs(r.t_test) > 3 else ''}")

    print(f"\nStap 2: ridge-model op alle kenmerken (train), handelen op de sterkste {a.top * 100:.0f}% voorspellingen (test). p = aandeel van {a.permutations} husselruns met een even goed resultaat.")
    print(f"{'uit':<6}{'IC test':>9}{'trades':>8}{'bruto bp':>10}{'netto bp':>10}{'winrate':>9}{'p':>7}")
    for label in sm.HORIZONS:
        r = sm.evaluate_model(panel.dropna(subset=["btc_r5"]), label, cut, a.cost_bps, a.top, a.permutations)
        print(f"{r.horizon:<6}{r.ic_test:>+9.4f}{r.n_trades:>8}{r.gross_bps:>+10.1f}{r.net_bps:>+10.1f}{r.winrate * 100:>8.0f}%{r.p_value:>7.2f}")
    print("\nLees het zo: een model telt pas als netto positief is, minstens 100 trades en p onder 0,05. Zonder dat is er geen voorspeller.")


if __name__ == "__main__":
    main()
