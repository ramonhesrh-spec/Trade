import unittest

import pandas as pd

from app.replay import outcome

T0 = pd.Timestamp("2026-01-01", tz="UTC")
DAY = pd.Timedelta(days=1)


def frame(rows):
    ts = pd.date_range("2026-01-01", periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": [1.0] * len(rows),
    })


def resolve(direction, rows, **kw):
    entry, stop, take = (100.0, 99.0, 102.0) if direction == "long" else (100.0, 101.0, 98.0)
    return outcome.resolve(direction, entry, stop, take, frame(rows), T0, DAY, fee_pct=0, slippage_pct=0, **kw)


class OutcomeTest(unittest.TestCase):
    def test_long_take_profit(self):
        o = resolve("long", [(100, 100.5, 99.5, 100), (100, 102.1, 99.5, 102)])
        self.assertEqual((o.result, o.r_gross), ("take_profit", 2.0))

    def test_long_stop_loss(self):
        o = resolve("long", [(100, 100.5, 98.9, 99)])
        self.assertEqual((o.result, o.r_net), ("stop_loss", -1.0))

    def test_both_in_one_candle_counts_stop(self):
        o = resolve("long", [(100, 102.5, 98.5, 100)])
        self.assertEqual(o.result, "stop_loss")

    def test_short_take_profit(self):
        o = resolve("short", [(100, 100.5, 97.9, 98)])
        self.assertEqual((o.result, o.r_gross), ("take_profit", 2.0))

    def test_expired_is_marked_to_market(self):
        o = resolve("long", [(100, 100.4, 99.6, 100.5)])
        self.assertEqual(o.result, "expired")
        self.assertAlmostEqual(o.r_gross, 0.5)

    def test_costs_reduce_r(self):
        o = outcome.resolve("long", 100.0, 99.0, 102.0, frame([(100, 102.1, 99.5, 102)]), T0, DAY,
                            fee_pct=0.1, slippage_pct=0.05)
        self.assertAlmostEqual(o.r_net, 2.0 - 2 * 0.15 / 100 * 100 / 1.0)

    def test_candles_before_signal_are_ignored(self):
        o = outcome.resolve("long", 100.0, 99.0, 102.0, frame([(100, 105, 90, 100)] * 3),
                            T0 + pd.Timedelta(hours=2), DAY)
        self.assertIsNone(o)


if __name__ == "__main__":
    unittest.main()
