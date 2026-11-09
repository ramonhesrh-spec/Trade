import unittest

import numpy as np
import pandas as pd

from app.replay import aplus
from tests.replay.test_liquidity_levels import frame


def planted_df(effect=0.4, n=3000, seed=0):
    rng = np.random.default_rng(seed)
    at = pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(np.arange(n) * 17, unit="min")
    df = pd.DataFrame({"at": at})
    for name in aplus.HYPOTHESES:
        df[name] = rng.random(n) < 0.5 if name in ("killzone", "trend_aligned") else rng.normal(size=n)
    r = rng.normal(-0.15, 1.0, n) + effect * (df["depth_atr"] > 0) + effect * (df["rejection"] > 0) + effect * df["killzone"]
    df["r2.0"] = r
    return df


class PipelineTest(unittest.TestCase):
    def test_finds_planted_features_and_holds_up_on_test_half(self):
        df = planted_df()
        cut = df["at"].quantile(0.7)
        res = aplus.run_pipeline(df, "r2.0", cut)
        self.assertTrue({"depth_atr", "rejection", "killzone"} <= set(res.chosen))
        self.assertGreater(res.test_r, 0.2)
        self.assertLess(aplus.permutation_p(df, "r2.0", cut, res, n=40), 0.1)

    def test_pure_noise_gives_no_edge_and_a_large_p_value(self):
        df = planted_df(effect=0.0, seed=4)
        cut = df["at"].quantile(0.7)
        res = aplus.run_pipeline(df, "r2.0", cut)
        self.assertLess(res.test_r, 0.15)
        if res.min_score:
            self.assertGreater(aplus.permutation_p(df, "r2.0", cut, res, n=40), 0.1)

    def test_thresholds_come_from_train_only(self):
        df = planted_df()
        cut = df["at"].quantile(0.7)
        a = aplus.train_thresholds(df[df["at"] < cut])
        df2 = df.copy()
        df2.loc[df2["at"] >= cut, "depth_atr"] += 100          # verandering in de testhelft
        self.assertEqual(a, aplus.train_thresholds(df2[df2["at"] < cut]))

    def test_feature_table_has_both_halves(self):
        rows = aplus.feature_table(planted_df(), "r2.0", pd.Timestamp("2026-01-20", tz="UTC"))
        self.assertEqual(len(rows), len(aplus.HYPOTHESES))
        self.assertTrue(all("train_good" in r and "test_good" in r for r in rows))


class DatasetTest(unittest.TestCase):
    def test_dataset_has_features_outcomes_and_no_lookahead(self):
        f = frame(days=25, seed=2, plant=True)
        data = aplus.build_dataset(f)
        self.assertGreater(len(data), 20)
        for col in aplus.HYPOTHESES + ["r1.5", "r2.0", "r3.0", "conf_r2.0"]:
            self.assertIn(col, data.columns)
        # alleen de toekomst verandert: kenmerken van eerdere gebeurtenissen blijven gelijk
        cut = f["timestamp"].iloc[int(len(f) * 0.6)]
        short = aplus.build_dataset(f[f["timestamp"] < cut + pd.Timedelta(hours=1)])
        early = data[data["at"] < cut - pd.Timedelta(days=1)].reset_index(drop=True)
        early_short = short[short["at"] < cut - pd.Timedelta(days=1)].reset_index(drop=True)
        self.assertEqual(len(early), len(early_short))
        cols = list(aplus.HYPOTHESES)
        pd.testing.assert_frame_equal(early[cols], early_short[cols], check_dtype=False)


if __name__ == "__main__":
    unittest.main()
