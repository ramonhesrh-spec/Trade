"""Toetst per voorspelbaar moment (funding, opening VS-beurs, opties-expiry, macro) of er iets te verdienen valt, op de
1m-candles in data/candles. Zelfde regels als scripts/strategy_scan.py: vaste uitstap, kosten, train en test, controle op
willekeurige momenten. Toont ook hoeveel harder de koers rond zo'n moment beweegt dan normaal.
Draai: python3 scripts/calendar_scan.py [--cost-bps 6]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, market_calendar  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import strategy_scan as ss  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cost-bps", type=float, default=6.0)
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    a = p.parse_args()
    closes = ss.closes_5m({c: candle_cache.load_candles(c, "1m") for c in a.coins.split(",")})
    moments = market_calendar.moments(closes.index[0].to_pydatetime(), closes.index[-1].to_pydatetime())
    ev = ss.calendar_events(closes, moments)
    rows = ss.evaluate(closes, a.cost_bps, ev=ev)
    print(f"{len(moments)} momenten, {closes.index[0]:%Y-%m-%d} tot {closes.index[-1]:%Y-%m-%d}, kosten {a.cost_bps:.0f} bp per rondreis")
    print("Beweging in het uur erna, tegenover een gewoon uur:")
    for kind, x in sorted(ss.vol_multiple(closes, moments).items()):
        print(f"   {market_calendar.LABELS.get(kind, kind):<24}{x:.2f}x")
    print("\nSlaagt = netto positief in train en test, minstens 30 trades per helft, t > 2\n")
    print(f"{'moment':<16}{'uit':<5}{'kant':<14}{'n':>6}{'bruto bp':>10}{'netto bp':>10}{'t':>6}{'train':>9}{'test':>9}{'placebo':>9}  slaagt")
    for r in sorted(rows, key=lambda r: (r.idee, r.horizon, r.kant)):
        tr = f"{r.train_net:+.1f}" if r.train_net is not None else "-"
        te = f"{r.test_net:+.1f}" if r.test_net is not None else "-"
        print(f"{r.idee:<16}{r.horizon:<5}{r.kant:<14}{r.n:>6}{r.gross:>+10.1f}{r.net:>+10.1f}{r.t:>6.1f}{tr:>9}{te:>9}{r.placebo_net:>+9.1f}  {'JA' if ss.passes(r) else ''}")
    print(f"\n{sum(ss.passes(r) for r in rows)} van {len(rows)} combinaties slagen. Een paar toevallige treffers zijn bij dit aantal normaal.")


if __name__ == "__main__":
    main()
