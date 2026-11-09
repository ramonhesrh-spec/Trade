import json
import unittest

import pandas as pd

from app import structure_review as sr


def plan(hits, closed=True, targets_r=(1.0, 2.0, 3.0)):
    return json.dumps({"targets_r": list(targets_r), "fired": {"hits": hits, "closed": closed}})


class LadderTest(unittest.TestCase):
    def test_ladder_result_follows_the_rule_a_third_per_target_and_stop_to_entry_after_t1(self):
        self.assertEqual(sr.ladder_r(plan(0)), -1.0)                           # stop vóór T1
        self.assertAlmostEqual(sr.ladder_r(plan(1)), 1 / 3)                    # T1, daarna stop op de instap
        self.assertAlmostEqual(sr.ladder_r(plan(2)), (1 + 2) / 3)              # T1 en T2, rest op break-even
        self.assertAlmostEqual(sr.ladder_r(plan(3)), (1 + 2 + 3) / 3)          # alle doelen
        self.assertIsNone(sr.ladder_r(plan(1, closed=False)))                  # nog lopend: geen cijfer
        self.assertIsNone(sr.ladder_r(None))
        self.assertAlmostEqual(sr.ladder_r(plan(3), cost_r=0.1), 2.0 - 0.1)


class StatsTest(unittest.TestCase):
    def test_wilson_interval_is_wide_for_small_samples_and_narrow_for_large(self):
        small = sr.wilson(3, 5)
        large = sr.wilson(300, 500)
        self.assertGreater(small[1] - small[0], large[1] - large[0])
        self.assertLessEqual(small[0], 0.6 <= small[1])
        self.assertEqual(sr.wilson(0, 0), (0.0, 1.0))

    def test_bootstrap_is_deterministic_and_brackets_the_mean(self):
        values = [1.0, -1.0, 2.0, -1.0, 1.0, -1.0, 3.0, -1.0]
        lo, hi = sr.bootstrap_mean(values)
        self.assertEqual((lo, hi), sr.bootstrap_mean(values))
        self.assertLess(lo, sum(values) / len(values))
        self.assertGreater(hi, sum(values) / len(values))

    def test_verdict_refuses_conclusions_on_small_groups_and_on_margins_that_include_zero(self):
        self.assertEqual(sr.summarize([2.0] * 5)["verdict"], "te klein")
        self.assertEqual(sr.summarize([1.0, -1.0] * 15)["verdict"], "onbeslist (marge omvat 0)")
        self.assertIn("voordeel", sr.summarize([2.0] * 25 + [-1.0] * 5)["verdict"])
        self.assertIn("verlies", sr.summarize([-1.0] * 25 + [0.5] * 5)["verdict"])

    def test_drawdown_and_losing_streak(self):
        seq = [1.0, -1.0, -1.0, 2.0, -1.0]
        self.assertEqual(sr.max_drawdown(seq), -2.0)
        self.assertEqual(sr.longest_losing_streak(seq), 2)


class FunnelTest(unittest.TestCase):
    def test_funnel_counts_where_breaks_stop(self):
        rows = [{"state": "fired", "signal_id": 1, "auto_outcome": "take_profit"}, {"state": "fired", "signal_id": 2, "auto_outcome": None},
                {"state": "expired", "signal_id": None, "auto_outcome": None}, {"state": "geen_plan", "signal_id": None, "auto_outcome": None}]
        f = sr.funnel(rows)
        self.assertEqual((f["gezien"], f["gevuld"], f["afgerond"]), (4, 2, 1))
        self.assertEqual(f["per_status"]["fired"], 2)

    def test_dimensions_group_by_the_documented_buckets(self):
        row = {"grade": "C", "kind": "RANGE", "direction": "short", "coin": "BTC", "features": json.dumps({"touches": 2, "vol_ratio": 0.66, "with_trend": False, "span": 8}),
               "risk_pct": 0.4, "target2_r": 2.0, "wait_hours": 0.5, "hour_utc": 3}
        got = {name: key(row) for name, key in sr.DIMENSIONS.items()}
        self.assertEqual(got["oordeel"], "zwak (C)")
        self.assertEqual(got["aanrakingen"], "2")
        self.assertEqual(got["volume van de breuk"], "onder 1x")
        self.assertEqual(got["met de trend"], "nee")
        self.assertEqual(got["stopafstand"], "onder 0,5%")
        self.assertEqual(got["sessie bij vulling (UTC)"], "Azië (0-7)")


class AfterBreakTest(unittest.TestCase):
    def frame(self, rows):
        import pandas as pd
        return pd.DataFrame([(pd.Timestamp("2026-10-01", tz="UTC") + pd.Timedelta(minutes=5 * i), h, l) for i, (h, l) in enumerate(rows)], columns=["timestamp", "high", "low"])

    def test_short_that_ran_away_without_returning_is_a_missed_winner(self):
        c = self.frame([(99.5, 98.9), (99.0, 97.8), (98.0, 96.9)])                   # nooit terug naar 100, doel 2 op 97,6 bereikt
        self.assertEqual(sr.after_break("short", lambda t: 100.0, 100.8, [99.2, 97.6, 96.0], c), "doel 2")

    def test_first_event_decides_and_stop_zone_means_waiting_saved_a_loss(self):
        self.assertEqual(sr.after_break("short", lambda t: 100.0, 100.8, [99.2, 97.6, 96.0], self.frame([(99.5, 99.0), (101.0, 99.5)])), "kwam terug")
        self.assertEqual(sr.after_break("long", lambda t: 100.0, 99.2, [100.8, 102.0], self.frame([(100.9, 100.1)])), "doel 1")
        self.assertEqual(sr.after_break("short", lambda t: 100.0, 100.8, [99.2, 97.6], self.frame([(99.9, 99.8)])), "niets")

    def test_a_sloping_line_is_followed_so_a_static_level_does_not_fake_a_return(self):
        c = self.frame([(99.6, 99.0), (99.7, 99.1), (99.7, 98.9), (99.0, 97.0)])
        static = sr.after_break("short", lambda t: 99.5, 100.8, [99.2, 97.6], c)         # een vast niveau van 99,5 lijkt geraakt
        sloping = sr.after_break("short", lambda t: 100.2 - 0.2 * ((t - pd.Timestamp("2026-10-01", tz="UTC")).total_seconds() / 300), 100.8, [99.2, 97.6], c)
        self.assertEqual(static, "kwam terug")
        self.assertEqual(sloping, "doel 2")                                              # de lijn zakt weg onder de highs: nooit teruggekeerd

    def test_funnel_by_grade(self):
        got = sr.funnel_by_grade([{"grade": "C", "signal_id": 1}, {"grade": "C", "signal_id": None}, {"grade": None, "signal_id": None}])
        self.assertEqual(got["zwak (C)"], {"gezien": 2, "gevuld": 1})
        self.assertEqual(got["geen oordeel"], {"gezien": 1, "gevuld": 0})


if __name__ == "__main__":
    unittest.main()
