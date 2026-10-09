import unittest

import pandas as pd

from app.replay import stats


class ClusterBootstrapTest(unittest.TestCase):
    def test_empty_and_single_cluster(self):
        self.assertEqual(stats.cluster_bootstrap_mean([], []), (0.0, 0.0))
        lo, hi = stats.cluster_bootstrap_mean([1.0, 3.0], ["a", "a"])
        self.assertEqual((lo, hi), (2.0, 2.0))

    def test_correlated_trades_widen_the_interval(self):
        values = [1.0] * 10 + [-1.0] * 10
        independent = [str(i) for i in range(20)]
        two_weeks = ["w1"] * 10 + ["w2"] * 10
        lo_i, hi_i = stats.cluster_bootstrap_mean(values, independent)
        lo_c, hi_c = stats.cluster_bootstrap_mean(values, two_weeks)
        self.assertGreater(hi_c - lo_c, hi_i - lo_i)

    def test_same_seed_same_answer(self):
        v, c = [0.5, -0.2, 1.1, -1.0], ["a", "a", "b", "c"]
        self.assertEqual(stats.cluster_bootstrap_mean(v, c), stats.cluster_bootstrap_mean(v, c))

    def test_week_key(self):
        self.assertEqual(stats.week_key(pd.Timestamp("2026-10-09", tz="UTC")), "2026-W41")


if __name__ == "__main__":
    unittest.main()
