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


def rows_for(reach1, weeks, cost=0.05, grade="A"):
    at = [pd.Timestamp("2025-01-06", tz="UTC") + pd.Timedelta(weeks=w) for w in weeks]
    n = len(reach1)
    df = pd.DataFrame({"row_id": [f"X:{k}" for k in range(n)], "at": at, "filled": True, "cancel": "", "reach_1r": reach1,
                       "stop_hit": [not r for r in reach1], "tight": [False] * n, "cost_r": cost, "stop_pct": 2.5, "stop_atr": 1.2,
                       "hours_to_stop": 3.0, "mae_r": 0.5, "mfe_r": 1.0, "ref_mid": 0.5, "ref_opp": 1.0, "ref_trail": 0.2, "grade": grade})
    for k in sq.R_LEVELS[1:]:
        df[f"reach_{k}r"] = False
    return df


def plac_for(real, reach):
    return real.assign(pair_id=real["row_id"], reach_1r=reach)


def big(reach=None, **kw):
    """400 vullingen over 100 weken, om en om een winnaar: alle statische toetsen slagen."""
    reach = reach if reach is not None else [k % 2 == 0 for k in range(400)]
    return rows_for(reach, [k // 4 for k in range(400)], **kw)


class SummaryTest(unittest.TestCase):
    def test_counts_and_shares(self):
        s = sq.summarize(rows_for([True, False, True, True], [0, 0, 1, 1]))
        self.assertEqual((s["n"], s["weeks"]), (4, 2))
        self.assertAlmostEqual(s["reach"][1]["p"], 0.75)
        self.assertAlmostEqual(s["stop_hit"]["p"], 0.25)
        self.assertAlmostEqual(s["ref"]["trail"]["avg_net"], 0.15)
        self.assertEqual(sorted(s["reach"]), list(sq.R_LEVELS))

    def test_unfilled_rows_count_as_setups_only(self):
        extra = pd.DataFrame([{"at": pd.Timestamp("2025-01-06", tz="UTC"), "filled": False, "cancel": "weggelopen"}])
        s = sq.summarize(pd.concat([rows_for([True], [0]), extra], ignore_index=True))
        self.assertEqual((s["setups"], s["n"], s["cancels"]), (2, 1, {"weggelopen": 1}))

    def test_doelkans_table(self):
        t = sq.doelkans_table(sq.summarize(rows_for([True, False, True, True], [0, 0, 1, 1])))
        self.assertEqual([x["r"] for x in t], list(sq.R_LEVELS))
        self.assertEqual(t[0]["p_text"], "75%")

    def test_empty_and_unfilled_only_do_not_crash(self):
        self.assertEqual(sq.summarize(pd.DataFrame())["n"], 0)
        only = pd.DataFrame([{"at": pd.Timestamp("2025-01-06", tz="UTC"), "filled": False, "cancel": "verlopen"}])
        s = sq.summarize(only)
        self.assertEqual((s["setups"], s["n"], s["fill_rate"]), (1, 0, 0.0))
        self.assertEqual(sq.doelkans_table(s), [])

    def test_quantiles_and_costs(self):
        s = sq.summarize(rows_for([True, False, True, True], [0, 0, 1, 1], cost=0.2))
        self.assertEqual(s["mae_q"], [0.5] * 4)
        self.assertAlmostEqual(s["median_cost_r"], 0.2)
        self.assertEqual(s["share_cost_over_01"], 1.0)
        self.assertEqual(s["median_hours_to_stop"], 3.0)

    def test_stop_free_reference_with_missing_value_is_skipped(self):
        r = rows_for([True, True, True, True], [0, 0, 1, 1])
        r["ref_mid"] = [None, 0.5, 0.5, 0.5]
        s = sq.summarize(r)
        self.assertEqual(s["ref"]["mid"]["n"], 3)
        self.assertAlmostEqual(s["ref"]["mid"]["avg_net"], 0.45)

    def test_grades_halves_blocks(self):
        r = rows_for([True, False] * 6, list(range(12)))
        r["grade"] = ["A", "B", "C"] * 4
        s = sq.summarize(r)
        self.assertEqual(sorted(s["by_grade"]), ["A", "B", "C"])
        self.assertEqual(s["halves"], (0.5, 0.5))
        self.assertEqual(len(s["blocks"]), sq.N_BLOCKS)


class AcceptTest(unittest.TestCase):
    def test_all_checks_named_and_small_sample_fails(self):
        real = rows_for([True, False] * 10, list(range(20)))
        out = sq.accept(sq.summarize(real), real, real.assign(pair_id=real["row_id"], reach_1r=False))
        self.assertFalse(out["passes"])
        self.assertFalse(out["checks"]["genoeg vullingen (300)"])
        self.assertTrue(out["checks"]["beter dan willekeurig (+1R vóór de stop minstens 5 procentpunt)"])
        self.assertEqual(len(out["checks"]), 7)

    def test_big_stable_sample_passes(self):
        weeks = [k // 4 for k in range(400)]
        real = rows_for([k % 2 == 0 for k in range(400)], weeks)
        out = sq.accept(sq.summarize(real), real, real.assign(pair_id=real["row_id"], reach_1r=[k % 5 == 0 for k in range(400)]))
        self.assertTrue(out["passes"], out["reason"])
        self.assertEqual(out["verdict"], "PASS")

    def test_expensive_stop_fails(self):
        weeks = [k // 4 for k in range(400)]
        real = rows_for([k % 2 == 0 for k in range(400)], weeks, cost=0.2)
        out = sq.accept(sq.summarize(real), real, real.assign(pair_id=real["row_id"], reach_1r=False))
        self.assertFalse(out["checks"]["kosten mediaan hooguit 0,10R"])

    def test_unstable_halves_fail(self):
        reach = [k % 4 != 0 for k in range(200)] + [k % 4 == 0 for k in range(200)]
        real = big(reach)
        out = sq.accept(sq.summarize(real), real, plac_for(real, False))
        self.assertFalse(out["checks"]["helften stabiel (hooguit 10 procentpunt)"])
        self.assertEqual(out["verdict"], "FAIL")

    def test_one_unstable_block_fails_while_halves_hold(self):
        # Blokken van 67/66 vullingen: blok 1 alles winst, blok 2 niets; de helften middelen het uit.
        reach = [True] * 67 + [False] * 67 + [k % 2 == 0 for k in range(266)]
        real = big(reach)
        s = sq.summarize(real)
        out = sq.accept(s, real, plac_for(real, False))
        self.assertLessEqual(abs(s["halves"][0] - s["halves"][1]), sq.MAX_HALF_DIFF)
        self.assertFalse(out["checks"]["blokken stabiel (hooguit 15 procentpunt)"])

    def test_placebo_equal_fails_even_with_stable_real(self):
        real = big()
        out = sq.accept(sq.summarize(real), real, plac_for(real, real["reach_1r"].tolist()))
        self.assertFalse(out["checks"]["beter dan willekeurig (+1R vóór de stop minstens 5 procentpunt)"])
        self.assertFalse(out["passes"])

    def test_placebo_edge_needs_both_size_and_interval(self):
        real = big()
        # 5 procentpunt verschil gemiddeld, maar het verschil is ruis rond het gemiddelde: ondergrens niet boven 0 mag niet slagen als gemiddelde < drempel
        small = [k % 2 == 0 and k % 40 != 0 for k in range(400)]
        out = sq.accept(sq.summarize(real), real, plac_for(real, small))
        self.assertAlmostEqual(out["placebo_diff"], 0.025, places=6)
        self.assertFalse(out["checks"]["beter dan willekeurig (+1R vóór de stop minstens 5 procentpunt)"])

    def test_too_tight_stops_fail(self):
        real = big()
        real["tight"] = [k % 2 == 1 for k in range(400)]  # alle geraakte stops (de oneven) zijn te krap
        out = sq.accept(sq.summarize(real), real, plac_for(real, False))
        self.assertFalse(out["checks"]["stop niet te krap (hooguit 25%)"])

    def test_empty_or_tiny_is_te_weinig_trades_never_pass(self):
        for real in (pd.DataFrame(), rows_for([True], [0])):
            s = sq.summarize(real)
            out = sq.accept(s, real, pd.DataFrame())
            self.assertFalse(out["passes"])
            self.assertEqual(out["verdict"], "TE WEINIG TRADES")
            self.assertIn("te weinig trades", out["reason"])

    def test_missing_placebo_never_passes(self):
        real = big()
        out = sq.accept(sq.summarize(real), real, pd.DataFrame())
        self.assertFalse(out["passes"])

    def test_boundaries_follow_the_frozen_constants(self):
        real = big(cost=sq.MAX_MEDIAN_COST_R)
        ok = sq.accept(sq.summarize(real), real, plac_for(real, False))
        self.assertTrue(ok["checks"]["kosten mediaan hooguit 0,10R"])
        real = big(cost=sq.MAX_MEDIAN_COST_R + 0.001)
        self.assertFalse(sq.accept(sq.summarize(real), real, plac_for(real, False))["checks"]["kosten mediaan hooguit 0,10R"])
        few = rows_for([k % 2 == 0 for k in range(sq.MIN_FILLS)], [k // 3 for k in range(sq.MIN_FILLS)])
        self.assertTrue(sq.accept(sq.summarize(few), few, plac_for(few, False))["checks"][f"genoeg vullingen ({sq.MIN_FILLS})"])
        fewer = few.iloc[:-1]
        self.assertFalse(sq.accept(sq.summarize(fewer), fewer, plac_for(fewer, False))["checks"][f"genoeg vullingen ({sq.MIN_FILLS})"])
        weeks = [k % sq.MIN_WEEKS for k in range(400)]
        r = rows_for([k % 2 == 0 for k in range(400)], weeks)
        self.assertTrue(sq.accept(sq.summarize(r), r, plac_for(r, False))["checks"][f"genoeg weken ({sq.MIN_WEEKS})"])
        r = rows_for([k % 2 == 0 for k in range(400)], [k % (sq.MIN_WEEKS - 1) for k in range(400)])
        self.assertFalse(sq.accept(sq.summarize(r), r, plac_for(r, False))["checks"][f"genoeg weken ({sq.MIN_WEEKS})"])

    def test_several_placebo_draws_per_pair_are_averaged(self):
        real = big()
        two = pd.concat([plac_for(real, False), plac_for(real, [k % 2 == 0 for k in range(400)])], ignore_index=True)
        out = sq.accept(sq.summarize(real), real, two)
        self.assertAlmostEqual(out["placebo_diff"], 0.25)
        self.assertEqual(out["placebo_pairs"], 400)

    def test_verdict_uses_only_frozen_constants(self):
        import ast
        import inspect
        import re
        import textwrap
        from pathlib import Path
        text = (Path(__file__).resolve().parents[2] / "docs/onderzoek/range-sweep/preregistratie.md").read_text()
        block = re.search(r"```prereg-constants\n(.*?)```", text, re.S).group(1)
        seen = 0
        for line in block.splitlines():
            m = re.match(r"stopquality\.(\w+) = (.+)", line)
            if m:
                self.assertEqual(getattr(sq, m.group(1)), float(m.group(2).replace(",", ".")), m.group(1))
                seen += 1
        self.assertGreaterEqual(seen, 13)
        for fn in (sq.accept, sq.kill_check):
            numbers = {n.value for n in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))) if isinstance(n, ast.Constant)
                       and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
            self.assertLessEqual(numbers, {0, 1, 100}, f"{fn.__name__} bevat een eigen drempel: {numbers}")


class KillTest(unittest.TestCase):
    def result(self, passes, cost):
        return {"summary": {"n": 400, "median_cost_r": cost}, "accept": {"passes": passes}}

    def test_s2_when_no_test_passes(self):
        out = sq.kill_check([self.result(False, 0.05)] * 30)
        self.assertTrue(out["S2"])
        self.assertFalse(out["S3"])

    def test_s3_when_all_costs_too_high(self):
        out = sq.kill_check([self.result(False, 0.2)] * 30)
        self.assertTrue(out["S3"])

    def test_one_pass_clears_s2(self):
        self.assertFalse(sq.kill_check([self.result(True, 0.05)] + [self.result(False, 0.05)] * 29)["S2"])

    def test_incomplete_set_decides_nothing(self):
        out = sq.kill_check([self.result(False, 0.2)] * 10)
        self.assertEqual(out["status"], "onvolledig")
        self.assertFalse(out["S2"] or out["S3"])

    def test_tests_without_fills_have_no_cost_and_block_s3(self):
        res = [self.result(False, 0.2)] * 29 + [{"summary": {"n": 0}, "accept": {"passes": False}}]
        self.assertFalse(sq.kill_check(res)["S3"])


class PlaceboTest(unittest.TestCase):
    def setUp(self):
        from app.replay import rangesweep as rs
        from app.replay.lab import add_indicators
        from tests.replay.rangesweep_fixtures import frames
        b15, b1h, _ = frames()
        self.b15 = b15.reset_index(drop=True)
        self.b1 = add_indicators(b1h).reset_index(drop=True)
        b_tf, ranges = rs.range_series(b1h, "1h")
        self.active = rs.active_for(self.b1, b_tf, ranges, "1h")
        self.atr = sq.atr_on_15m(b15, self.b1)
        self.real = pd.DataFrame([{"row_id": "X:0", "filled": True, "direction": "short", "stop_atr": 1.0, "at": self.b1["timestamp"].iloc[150]}])

    def run_placebo(self, real=None, seed=3, draws=1):
        return sq.placebo_rows(self.real if real is None else real, self.b15, self.b1, self.active, self.atr, 0.12, seed=seed, draws=draws)

    def test_pairs_and_measures(self):
        p = self.run_placebo()
        self.assertEqual(list(p["pair_id"]), ["X:0"])
        self.assertIn("reach_1r", p.columns)

    def test_deterministic_for_a_seed(self):
        a, b = self.run_placebo(draws=8), self.run_placebo(draws=8)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(len(a), 8)

    def test_does_not_read_the_outcome_of_the_real_trade(self):
        a = self.run_placebo(draws=5)
        other = self.real.assign(reach_1r=True, stop_hit=False, mfe_r=99.0, cancel="x")
        pd.testing.assert_frame_equal(a, self.run_placebo(other, draws=5))

    def test_entry_is_inside_an_active_range_on_the_right_side(self):
        p = self.run_placebo(draws=10)
        self.assertGreater(len(p), 0)
        for _, row in p.iterrows():
            j = int(self.b1.index[self.b1["timestamp"] == row["at"]][0])
            r = self.active[j]
            self.assertTrue(r.low < self.b1["close"].iloc[j] < r.high)
            self.assertGreater(row["stop"], row["entry"])

    def test_unfilled_real_rows_get_no_placebo(self):
        extra = pd.concat([self.real, pd.DataFrame([{"row_id": "X:1", "filled": False, "at": self.real["at"].iloc[0]}])], ignore_index=True)
        self.assertEqual(list(self.run_placebo(extra)["pair_id"]), ["X:0"])

    def test_no_active_range_gives_empty_frame(self):
        p = sq.placebo_rows(self.real, self.b15, self.b1, [None] * len(self.b1), self.atr, 0.12)
        self.assertTrue(p.empty)


if __name__ == "__main__":
    unittest.main()
