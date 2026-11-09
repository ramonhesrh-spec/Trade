import unittest

import pandas as pd

from app.replay import candles, view
from tests.replay.fixtures import make_smc_prone_1m

ONE_MINUTE = pd.Timedelta(minutes=1)


class OneMinuteBaseTest(unittest.TestCase):
    def setUp(self):
        self.base = make_smc_prone_1m(days=5)

    def data_at(self, at):
        return view.ReplayData({"ETH": self.base}, pd.Timestamp(at, tz="UTC"), base_delta=ONE_MINUTE)

    def test_cache_path_per_timeframe(self):
        self.assertTrue(str(candles.cache_path("eth", "1m")).endswith("ETH_1m.csv"))
        self.assertTrue(str(candles.cache_path("eth")).endswith("ETH_15m.csv"))

    def test_no_lookahead_and_forming_15m_is_partial(self):
        data = self.data_at("2026-01-03 10:07")
        df = data.fetch_ohlcv("ETH", "15m", limit=20)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-03 10:00", tz="UTC"))
        part = self.base[(self.base["timestamp"] >= "2026-01-03 10:00") & (self.base["timestamp"] < "2026-01-03 10:07")]
        self.assertAlmostEqual(df["volume"].iloc[-1], part["volume"].sum())
        self.assertAlmostEqual(df["close"].iloc[-1], part["close"].iloc[-1])
        self.assertTrue((df["timestamp"] < pd.Timestamp("2026-01-03 10:07", tz="UTC")).all())

    def test_30m_candle_is_aggregate_of_1m(self):
        df = self.data_at("2026-01-03 10:45").fetch_ohlcv("ETH", "30m", limit=5)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-03 10:30", tz="UTC"))
        part = self.base[(self.base["timestamp"] >= "2026-01-03 10:30") & (self.base["timestamp"] < "2026-01-03 10:45")]
        self.assertAlmostEqual(df["high"].iloc[-1], part["high"].max())
        self.assertAlmostEqual(df["low"].iloc[-1], part["low"].min())

    def test_1m_returns_only_closed_candles(self):
        df = self.data_at("2026-01-03 10:07").fetch_ohlcv("ETH", "1m", limit=10)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-03 10:06", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
