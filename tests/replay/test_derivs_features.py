import unittest

import pandas as pd

from app.replay.derivs_features import features_at


def frame(funding=0.0001, taker=1.2):
    idx = pd.date_range("2026-10-01", periods=200, freq="5min", tz="UTC")
    return pd.DataFrame({"oi_usd": range(1000, 1200), "taker_ratio": taker, "global_ls": 1.5, "top_ls": 0.8,
                         "funding": funding}, index=idx)


class FeaturesTest(unittest.TestCase):
    def test_direction_flips_features(self):
        at = pd.Timestamp("2026-10-01 10:00", tz="UTC")
        long = features_at(frame(), at, "long")
        short = features_at(frame(), at, "short")
        self.assertTrue(long["funding_vol"] and not short["funding_vol"])
        self.assertTrue(long["taker_in_richting"] and not short["taker_in_richting"])
        self.assertTrue(long["publiek_in_richting"])
        self.assertTrue(short["top_in_richting"])
        self.assertGreater(long["oi_4u_pct"], 0)

    def test_no_lookahead(self):
        df = frame()
        at = pd.Timestamp("2026-10-01 10:00", tz="UTC")
        base = features_at(df, at, "long")
        df.loc[df.index > at, ["funding", "taker_ratio", "oi_usd"]] = [-1, 0.1, 1]
        self.assertEqual(features_at(df, at, "long"), base)

    def test_too_little_or_stale_data(self):
        self.assertIsNone(features_at(frame(), pd.Timestamp("2026-10-01 02:00", tz="UTC"), "long"))
        self.assertIsNone(features_at(frame(), pd.Timestamp("2026-10-03 00:00", tz="UTC"), "long"))


if __name__ == "__main__":
    unittest.main()
