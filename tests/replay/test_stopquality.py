import unittest

import numpy as np
import pandas as pd

from app.replay import stopquality as sq


def frame(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "timestamp", pd.date_range("2025-01-06", periods=len(df), freq="15min", tz="UTC"))
    return df


def mirror(df, pivot=200.0):
    """Spiegelt de koers rond pivot: een long wordt een short met dezelfde R-uitkomsten."""
    out = df.copy()
    out["open"], out["close"] = pivot - df["open"], pivot - df["close"]
    out["high"], out["low"] = pivot - df["low"], pivot - df["high"]
    return out


class FillTest(unittest.TestCase):
    def test_short_limit_fills_when_the_high_reaches_it(self):
        b = frame([(104, 104.5, 103.8, 104.2), (104.2, 105.1, 104.0, 104.9)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0), {"filled": [(1.0, 105.0, 1)], "first": 1, "cancel": ""})

    def test_open_beyond_the_stop_cancels(self):
        b = frame([(106.3, 106.5, 106.1, 106.2)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["cancel"], "stop voor vulling")

    def test_mid_before_fill_cancels(self):
        b = frame([(104, 104.2, 99.9, 100.1)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["cancel"], "weggelopen")

    def test_ttl(self):
        b = frame([(104, 104.1, 103.9, 104)] * (sq.TTL_15M + 5))
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["cancel"], "verlopen")

    def test_split_fills_both_legs(self):
        b = frame([(104, 105.1, 104, 105), (105, 105.6, 104.9, 105.2)])
        self.assertEqual(sq.simulate_fills("short", [(0.4, 105.0), (0.6, 105.5)], 106.0, 100.0, b, 0)["filled"], [(0.4, 105.0, 0), (0.6, 105.5, 1)])

    def test_long_mirror(self):
        b = frame([(96, 96.2, 94.9, 95.1)])
        self.assertEqual(sq.simulate_fills("long", [(1.0, 95.0)], 94.0, 100.0, b, 0)["first"], 0)

    def test_expiry_boundary_is_exactly_24_hours(self):
        quiet = (104, 104.1, 103.9, 104)
        last_ok = frame([quiet] * (sq.TTL_15M - 1) + [(104, 105.1, 104, 105)])
        too_late = frame([quiet] * sq.TTL_15M + [(104, 105.1, 104, 105)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, last_ok, 0)["first"], sq.TTL_15M - 1)
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, too_late, 0)["cancel"], "verlopen")

    def test_ttl_counts_from_start_not_from_the_frame(self):
        quiet = (104, 104.1, 103.9, 104)
        b = frame([(90, 91, 89, 90)] * 10 + [quiet] * sq.TTL_15M + [(104, 105.1, 104, 105)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 10)["cancel"], "verlopen")

    def test_candle_before_start_is_ignored(self):
        b = frame([(104, 105.5, 103, 105), (104, 104.2, 103.9, 104)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 1)["cancel"], "verlopen")

    def test_fill_and_mid_on_the_same_candle_counts_as_filled(self):
        b = frame([(104, 105.2, 99.9, 100.5)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["first"], 0)

    def test_fill_and_stop_on_the_same_candle_is_a_fill(self):
        b = frame([(104, 106.5, 103.9, 104.5)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["first"], 0)

    def test_second_leg_not_filled_after_the_stop_is_touched(self):
        b = frame([(104, 105.1, 104, 105), (105, 106.2, 104.9, 106.1), (106.1, 106.2, 104.9, 105.6)])
        r = sq.simulate_fills("short", [(0.4, 105.0), (0.6, 105.5)], 106.0, 100.0, b, 0)
        self.assertEqual(r["filled"], [(0.4, 105.0, 0), (0.6, 105.5, 1)])
        b2 = frame([(104, 105.1, 104, 105), (105, 105.4, 104.9, 105.1), (105.1, 106.2, 105.0, 106.1), (106.1, 106.2, 104.9, 105.6)])
        r2 = sq.simulate_fills("short", [(0.4, 105.0), (0.6, 105.5)], 106.0, 100.0, b2, 0)
        self.assertEqual(r2["filled"], [(0.4, 105.0, 0), (0.6, 105.5, 2)])

    def test_empty_frame_and_start_past_the_end(self):
        empty = pd.DataFrame({"timestamp": [], "open": [], "high": [], "low": [], "close": []})
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, empty, 0)["cancel"], "verlopen")
        b = frame([(104, 105.1, 104, 105)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 5)["cancel"], "verlopen")

    def test_long_mirror_of_every_outcome(self):
        cases = [[(104, 105.1, 104.0, 104.9)], [(106.3, 106.5, 106.1, 106.2)], [(104, 104.2, 99.9, 100.1)], [(104, 104.1, 103.9, 104)] * (sq.TTL_15M + 1),
                 [(104, 105.1, 104, 105), (105, 105.6, 104.9, 105.2)]]
        legs_short = [(0.4, 105.0), (0.6, 105.5)]
        for rows in cases:
            b = frame(rows)
            s = sq.simulate_fills("short", legs_short, 106.0, 100.0, b, 0)
            m = sq.simulate_fills("long", [(w, 200 - p) for w, p in legs_short], 94.0, 100.0, mirror(b), 0)
            self.assertEqual((s["cancel"], s["first"]), (m["cancel"], m["first"]))
            self.assertEqual([(w, i) for w, _, i in s["filled"]], [(w, i) for w, _, i in m["filled"]])


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.b = frame([(104.5, 105.2, 104.4, 104.8), (104.8, 104.9, 103.9, 104.0), (104.0, 104.1, 102.8, 103.0),
                        (103.0, 106.1, 102.9, 105.9), (105.9, 105.95, 105.0, 105.2), (105.2, 105.3, 103.9, 104.1)])
        self.atr = np.full(len(self.b), 1.0)

    def test_short_reaches_two_r_then_stops(self):
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        self.assertTrue(m["stop_hit"])
        self.assertAlmostEqual(m["stop_r"], -1.0)
        self.assertAlmostEqual(m["mfe_r"], 2.2)
        self.assertAlmostEqual(m["mae_r"], 1.0)
        self.assertEqual([m[f"reach_{k}r"] for k in sq.R_LEVELS], [True, True, False, False, False, False])
        self.assertAlmostEqual(m["hours_to_stop"], 0.75)
        self.assertAlmostEqual(m["cost_r"], 0.12 / 100 * 105.0)
        self.assertTrue(m["back_in_range"] and m["win_after_stop"] and m["tight"])

    def test_fill_candle_counts_only_against_you(self):
        b = frame([(104.5, 105.2, 103.0, 104.8), (104.8, 104.9, 104.5, 104.6)])
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)
        self.assertFalse(m["reach_1r"])
        self.assertAlmostEqual(m["mfe_r"], 0.5)

    def test_gap_through_stop_fills_on_the_open(self):
        b = frame([(104.5, 105.1, 104.4, 104.8), (106.5, 106.8, 106.3, 106.6)])
        self.assertAlmostEqual(sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)["stop_r"], -1.5)

    def test_mid_reference_takes_the_midpoint(self):
        b = frame([(104.5, 105.1, 104.4, 104.8), (104.8, 104.9, 102.6, 102.7)])
        self.assertAlmostEqual(sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)["ref_mid"], 105.0 - 102.75)

    def test_r_unit_is_the_risk_actually_taken(self):
        m = sq.measure("short", [(0.4, 105.0, 0), (0.6, 105.5, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        self.assertAlmostEqual(m["entry"], 105.3)
        self.assertAlmostEqual(m["stop_r"], -1.0)
        self.assertAlmostEqual(m["weight"], 1.0)

    def test_stop_and_target_in_one_candle_counts_as_stop(self):
        b = frame([(104.5, 105.1, 104.4, 104.8), (104.8, 106.2, 102.0, 104.0)])
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)
        self.assertTrue(m["stop_hit"])
        self.assertFalse(m["reach_1r"] or m["reach_2r"])
        self.assertAlmostEqual(m["mfe_r"], 0.0)

    def test_same_candle_stop_with_fill(self):
        b = frame([(104.5, 106.2, 103.0, 104.8), (104.8, 104.9, 102.0, 102.1)])
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)
        self.assertTrue(m["stop_hit"])
        self.assertAlmostEqual(m["stop_r"], -1.0)
        self.assertEqual(m["hours_to_stop"], 0.0)
        self.assertAlmostEqual(m["ref_trail"], -1.0)
        self.assertAlmostEqual(m["ref_mid"], -1.0)
        self.assertAlmostEqual(m["ref_opp"], -1.0)

    def test_no_stop_runs_to_the_horizon_without_flags(self):
        n = sq.HORIZON_15M + 20
        b = frame([(104.5, 105.1, 104.4, 104.8)] + [(104.5, 104.9, 104.1, 104.4)] * n)
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(n + 1), 105.5, 100.0, 0.12)
        self.assertFalse(m["stop_hit"])
        self.assertIsNone(m["stop_r"])
        self.assertIsNone(m["hours_to_stop"])
        self.assertFalse(m["back_in_range"] or m["win_after_stop"] or m["tight"])
        self.assertAlmostEqual(m["ref_trail"], 0.6)

    def test_stop_after_the_horizon_does_not_count(self):
        n = sq.HORIZON_15M
        rows = [(104.5, 105.1, 104.4, 104.8)] + [(104.5, 104.9, 104.1, 104.4)] * (n - 1) + [(104.5, 107.0, 104.1, 106.5)]
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, frame(rows), np.ones(n + 1), 105.5, 100.0, 0.12)
        self.assertFalse(m["stop_hit"])

    def test_results_do_not_depend_on_candles_after_the_stop(self):
        short = sq.measure("short", [(1.0, 105.0, 0)], 106.0, self.b.iloc[:4].reset_index(drop=True), self.atr[:4], 105.5, 100.0, 0.12)
        full = sq.measure("short", [(1.0, 105.0, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        for k in ("stop_r", "mae_r", "mfe_r", "hours_to_stop", "reach_1r", "reach_2r", "reach_3r", "ref_mid", "ref_opp", "ref_trail"):
            self.assertEqual(short[k], full[k], k)

    def test_tight_needs_both_back_in_range_and_a_win(self):
        b = frame([(104.5, 105.1, 104.4, 104.8), (104.8, 106.1, 104.6, 106.0)] + [(106.0, 106.2, 105.9, 106.1)] * 10)
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(12), 105.5, 100.0, 0.12)
        self.assertFalse(m["back_in_range"])
        self.assertFalse(m["tight"])
        b = frame([(104.5, 105.1, 104.4, 104.8), (104.8, 106.1, 104.6, 106.0), (106.0, 106.0, 105.0, 105.3)])
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(3), 105.5, 100.0, 0.12)
        self.assertTrue(m["back_in_range"])
        self.assertFalse(m["win_after_stop"])
        self.assertFalse(m["tight"])

    def test_back_in_range_window_is_12_hours(self):
        pad = [(106.0, 106.2, 105.9, 106.1)] * (sq.TIGHT_BACK_15M - 1)
        inside = [(106.0, 106.1, 105.0, 105.3)]
        head = [(104.5, 105.1, 104.4, 104.8), (104.8, 106.1, 104.6, 106.0)]
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, frame(head + pad + inside), np.ones(len(head + pad + inside)), 105.5, 100.0, 0.12)
        self.assertTrue(m["back_in_range"])
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, frame(head + pad + [(106.0, 106.2, 105.9, 106.1)] + inside), np.ones(len(head + pad) + 2), 105.5, 100.0, 0.12)
        self.assertFalse(m["back_in_range"])

    def test_stop_pct_and_stop_atr_units(self):
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, self.b, np.full(6, 0.5), 105.5, 100.0, 0.12)
        self.assertAlmostEqual(m["stop_pct"], 100 / 105.0)
        self.assertAlmostEqual(m["stop_atr"], 2.0)

    def test_nan_atr_gives_nan_stop_atr_and_still_measures(self):
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, self.b, np.full(6, np.nan), 105.5, 100.0, 0.12)
        self.assertTrue(np.isnan(m["stop_atr"]))
        self.assertAlmostEqual(m["stop_r"], -1.0)
        self.assertTrue(np.isfinite(m["ref_trail"]))

    def test_degenerate_input_is_refused(self):
        with self.assertRaises(ValueError):
            sq.measure("short", [], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        with self.assertRaises(ValueError):
            sq.measure("short", [(1.0, 106.0, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        with self.assertRaises(ValueError):
            sq.measure("short", [(1.0, 107.0, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)

    def test_long_is_the_exact_mirror_of_short(self):
        cases = [
            self.b,
            frame([(104.5, 105.1, 104.4, 104.8), (106.5, 106.8, 106.3, 106.6)]),
            frame([(104.5, 105.2, 103.0, 104.8), (104.8, 104.9, 104.5, 104.6)]),
            frame([(104.5, 105.1, 104.4, 104.8), (104.8, 104.9, 102.6, 102.7)]),
            frame([(104.5, 106.2, 103.0, 104.8), (104.8, 104.9, 102.0, 102.1)]),
        ]
        for b in cases:
            atr = np.linspace(0.8, 1.2, len(b))
            s = sq.measure("short", [(0.4, 105.0, 0), (0.6, 105.5, 0)], 106.0, b, atr, 105.5, 100.0, 0.12)
            lg = sq.measure("long", [(0.4, 95.0, 0), (0.6, 94.5, 0)], 94.0, mirror(b), atr, 100.0, 94.5, 0.12)
            for k, v in s.items():
                if k in ("entry", "stop", "stop_pct", "cost_r"):  # prijsafhankelijk, niet spiegelinvariant
                    continue
                if isinstance(v, float):
                    self.assertAlmostEqual(v, lg[k], places=9, msg=k)
                elif v is None:
                    self.assertIsNone(lg[k], k)
                else:
                    self.assertEqual(v, lg[k], k)
            self.assertAlmostEqual(lg["entry"], 200 - s["entry"])


class AtrOn15mTest(unittest.TestCase):
    def test_uses_only_closed_hours(self):
        b1 = pd.DataFrame({"timestamp": pd.date_range("2025-01-06", periods=2, freq="1h", tz="UTC"), "atr": [1.0, 2.0]})
        b15 = pd.DataFrame({"timestamp": pd.date_range("2025-01-06 00:45", periods=6, freq="15min", tz="UTC")})
        a = sq.atr_on_15m(b15, b1)
        self.assertTrue(np.isnan(a[0]))
        self.assertEqual(list(a[1:5]), [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(a[5], 2.0)


if __name__ == "__main__":
    unittest.main()
