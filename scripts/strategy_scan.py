"""Draait app/replay/strategy_scan.py op de 1m-candles in data/candles (zelfde cache als de andere replay-scripts).
Draai: python3 scripts/strategy_scan.py [--cost-bps 6] [--coins BTC,ETH,...]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import strategy_scan as ss  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=6.0, help="rondreis in basispunten (6 = 0,06%)")
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    a = p.parse_args()
    frames = {c: candle_cache.load_candles(c, "1m") for c in a.coins.split(",")}
    closes = ss.closes_5m(frames)
    rows = ss.evaluate(closes, a.cost_bps)
    print(f"{len(closes)} candles van 5m, {closes.index[0]:%Y-%m-%d} tot {closes.index[-1]:%Y-%m-%d}, kosten {a.cost_bps:.0f} bp per rondreis")
    print("Slaagt = netto positief in train en test, minstens 30 trades per helft, t > 2\n")
    print(f"{'idee':<20}{'uit':<5}{'kant':<14}{'n':>6}{'bruto bp':>10}{'netto bp':>10}{'t':>6}{'train':>9}{'test':>9}{'placebo':>9}  slaagt")
    for r in sorted(rows, key=lambda r: (r.idee, r.horizon, r.kant)):
        tr = f"{r.train_net:+.1f}" if r.train_net is not None else "-"
        te = f"{r.test_net:+.1f}" if r.test_net is not None else "-"
        print(f"{r.idee:<20}{r.horizon:<5}{r.kant:<14}{r.n:>6}{r.gross:>+10.1f}{r.net:>+10.1f}{r.t:>6.1f}{tr:>9}{te:>9}{r.placebo_net:>+9.1f}  {'JA' if ss.passes(r) else ''}")
    winners = [r for r in rows if ss.passes(r)]
    print(f"\n{len(winners)} van {len(rows)} combinaties slagen. Bij zoveel combinaties zijn een paar toevallige treffers normaal.")


if __name__ == "__main__":
    main()
