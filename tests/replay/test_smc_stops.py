import unittest
from types import SimpleNamespace

import pandas as pd

from app.replay import smc_stops

T0 = pd.Timestamp("2026-03-02 00:00", tz="UTC")


def frame(rows):
    return pd.DataFrame([{"timestamp": T0 + pd.Timedelta(minutes=i), "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
                         for i, (o, h, l, c) in enumerate(rows)])


def signal(stop, take=102.0):
    return SimpleNamespace(coin="SOL", direction="long", at=T0, entry=100.0, stop=stop, take=take)


class SmcStopsTests(unittest.TestCase):
    def test_wider_stop_survives_a_wick_that_stops_out_the_tight_one(self):
        # wick naar 99.7 (0,3% onder de instap), daarna omhoog naar het doel op 102
        f = frame([(100, 100.1, 99.7, 99.9), (99.9, 102.5, 99.9, 102.4)])
        s = signal(stop=99.9)                                                        # 0,1% stop
        tight = smc_stops.play(s, f, 0.0, pd.Timedelta(hours=1), 0.0, 0.0, min_rr=0.0)
        wide = smc_stops.play(s, f, 0.5, pd.Timedelta(hours=1), 0.0, 0.0, min_rr=0.0)
        self.assertEqual(tight.result, "stop_loss")
        self.assertEqual(wide.result, "take_profit")                                 # stop 99.5, het doel volgt
        self.assertAlmostEqual(wide.r_gross, 4.0)                                    # doel 2% ver, stop 0,5%: de R:R is 4

    def test_rr_gate_drops_a_chance_when_the_floor_makes_the_stop_too_wide(self):
        f = frame([(100, 100.1, 99.95, 100.0)] * 3)
        self.assertIsNotNone(smc_stops.play(signal(stop=99.0), f, 0.2, pd.Timedelta(hours=1), 0.0, 0.0, min_rr=2.0))   # stop 1%, doel 2%: R:R 2
        self.assertIsNone(smc_stops.play(signal(stop=99.0), f, 1.5, pd.Timedelta(hours=1), 0.0, 0.0, min_rr=2.0))      # stop 1,5%: R:R 1,33

    def test_sweep_reports_each_floor_with_train_and_test(self):
        f = frame([(100, 100.1, 99.7, 99.9), (99.9, 102.5, 99.9, 102.4)])
        rows = smc_stops.sweep([signal(stop=99.9)], {"SOL": f}, T0 + pd.Timedelta(days=1), floors=(0.1, 0.5), fee_pct=0.0, slip_pct=0.0)
        self.assertEqual([r.floor for r in rows], [0.1, 0.5])
        self.assertEqual((rows[0].wins, rows[0].losses), (0, 1))
        self.assertEqual((rows[1].wins, rows[1].losses), (1, 0))
        self.assertEqual(rows[1].n_train, 1)


if __name__ == "__main__":
    unittest.main()
