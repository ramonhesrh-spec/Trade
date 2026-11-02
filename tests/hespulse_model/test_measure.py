"""De meting van het HesPulse-model (app/model_measure.py, preregistratie §7 en §8): N_eff, verliesreeks, drawdown en herschikking, zonder de
beste 5%, uitvoerbaarheid en trechter, en het interval op 98,75%."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from app import model_measure as mm
from app.replay import stats

T0 = datetime(2026, 11, 2, tzinfo=timezone.utc)


def t(net, start_h, end_h, direction="long"):
    return {"net": net, "direction": direction, "start": T0 + timedelta(hours=start_h), "end": T0 + timedelta(hours=end_h)}


class NeffTest(unittest.TestCase):
    def test_overlapping_trades_in_one_direction_are_one_cluster_also_via_a_chain(self):
        trades = [t(1, 0, 3), t(1, 2, 5), t(1, 4, 6), t(1, 7, 8)]          # 0-3, 2-5 en 4-6 is één keten; 7-8 apart
        self.assertEqual(mm.n_eff(trades), 2)
        self.assertEqual(mm.cluster_ids(trades), [1, 1, 1, 2])

    def test_other_direction_is_its_own_cluster(self):
        self.assertEqual(mm.n_eff([t(1, 0, 3), t(1, 1, 2, "short")]), 2)


class SeriesTest(unittest.TestCase):
    def test_streak_and_drawdown(self):
        rs = [1, -1, -1, -1, 2, -1]
        self.assertEqual(mm.longest_losing_streak(rs), 3)
        self.assertEqual(mm.max_drawdown(rs), 3)

    def test_shuffled_drawdown_is_reproducible(self):
        rs = [1.5, -1, -1, 2, -1, 0.5, -1, 3]
        self.assertEqual(mm.shuffled_drawdown_p95(rs), mm.shuffled_drawdown_p95(rs))
        self.assertGreaterEqual(mm.shuffled_drawdown_p95(rs), 0)

    def test_without_best_five_percent_rounds_up_and_drops_at_least_one(self):
        self.assertEqual(mm.mean_without_best([5.0, 1.0, -1.0]), 0.0)
        rs = [float(i) for i in range(21)]                                  # 5% van 21 = 1,05 → twee eraf
        self.assertEqual(mm.mean_without_best(rs), sum(range(19)) / 19)

    def test_interval_level_parameter(self):
        vals = [(-1.0 if i % 3 else 2.0) for i in range(60)]
        weeks = [f"W{i // 5}" for i in range(60)]
        lo95, hi95 = stats.cluster_bootstrap_mean(vals, weeks)
        lo, hi = stats.cluster_bootstrap_mean(vals, weeks, level=mm.LEVEL)
        self.assertLessEqual(lo, lo95)
        self.assertGreaterEqual(hi, hi95)

    def test_arm_flags_a_drawdown_larger_than_chance(self):
        trades = [t(-1, i, i + 0.5) for i in range(10)] + [t(3, 20 + i, 20.5 + i) for i in range(10)]
        a = mm.arm(trades)
        self.assertEqual((a["n"], a["streak"]), (20, 10))
        self.assertTrue(a["dd_flag"])
        self.assertLess(a["half1"], a["half2"])


class ExecutionTest(unittest.TestCase):
    def rows(self):
        steps = json.dumps({"steps": [{"stap": "sweep"}, {"stap": "shift"}], "attempts": [{"reden": "terugtest_al_geweest", "steps": [{"stap": "sweep"}]}]})
        return [{"discovered_at": "2026-11-02T10:00:00+00:00", "detected_at": "2026-11-02T10:04:00+00:00", "entry_at": "2026-11-02T12:00:00+00:00",
                 "entry_detected_at": "2026-11-02T12:05:00+00:00", "vulbaar": 1, "entry_state": "gevuld", "signal_id": 7, "steps": steps},
                {"discovered_at": "2026-11-02T10:00:00+00:00", "detected_at": "2026-11-02T10:02:00+00:00", "entry_at": "2026-11-02T13:00:00+00:00",
                 "entry_detected_at": "2026-11-02T13:03:00+00:00", "vulbaar": 0, "entry_state": "niet_vulbaar", "signal_id": None, "steps": "{}"},
                {"discovered_at": "2026-11-02T10:00:00+00:00", "detected_at": "2026-11-02T10:01:00+00:00", "steps": "{}"}]

    def test_execution(self):
        e = mm.execution(self.rows())
        self.assertEqual((e["published"], e["vulbaar"], e["gevuld"], e["niet_vulbaar"], e["terugtest_al_geweest"]), (2, 1, 1, 1, 1))
        self.assertEqual(e["vulbaar_pct"], 50.0)
        self.assertEqual(e["delay_b_median"], 4.0)

    def test_funnel(self):
        f = mm.funnel(self.rows(), {7: "take_profit"})
        self.assertEqual(f, {"ontdekt": 3, "sweep": 1, "shift": 1, "entry": 2, "gevuld": 1, "uitkomst": 1})

    def test_report_hides_comparisons_for_students(self):
        rep = mm.report(self.rows(), [], [], 0.06)
        self.assertNotIn("compare", rep)
        self.assertEqual([c["key"] for c in mm.report(self.rows(), [], [], 0.06, ceo=True)["compare"]], ["V1", "V2", "V3"])
        json.dumps(mm.jsonable(rep))
