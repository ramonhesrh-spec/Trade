import unittest

import pandas as pd

from app.replay import view
from tests.replay.fixtures import make_base


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.base = make_base(days=40)

    def data_at(self, at):
        return view.ReplayData({"BTC": self.base}, pd.Timestamp(at, tz="UTC"))

    def test_no_lookahead(self):
        at = pd.Timestamp("2026-01-20 10:20", tz="UTC")
        data = view.ReplayData({"BTC": self.base}, at)
        known = self.base[self.base["timestamp"] < at]
        for tf in ("15m", "1h", "4h", "1d"):
            df = data.fetch_ohlcv("BTC", tf, limit=50)
            self.assertTrue((df["timestamp"] < at).all())
            self.assertLessEqual(df["high"].max(), known["high"].max() + 1e-9)
            self.assertGreaterEqual(df["low"].min(), known["low"].min() - 1e-9)

    def test_forming_4h_candle_is_partial(self):
        df = self.data_at("2026-01-20 10:20").fetch_ohlcv("BTC", "4h", limit=10)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-20 08:00", tz="UTC"))
        part = self.base[(self.base["timestamp"] >= "2026-01-20 08:00") & (self.base["timestamp"] < "2026-01-20 10:15")]
        self.assertAlmostEqual(df["volume"].iloc[-1], part["volume"].sum())
        self.assertAlmostEqual(df["close"].iloc[-1], part["close"].iloc[-1])

    def test_boundary_has_only_complete_candles(self):
        df = self.data_at("2026-01-20 08:00").fetch_ohlcv("BTC", "4h", limit=10)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-20 04:00", tz="UTC"))
        full = self.base[(self.base["timestamp"] >= "2026-01-20 04:00") & (self.base["timestamp"] < "2026-01-20 08:00")]
        self.assertAlmostEqual(df["volume"].iloc[-1], full["volume"].sum())

    def test_quote_volume_is_last_24h(self):
        data = self.data_at("2026-01-20 10:00")
        window = self.base[(self.base["timestamp"] >= "2026-01-19 10:00") & (self.base["timestamp"] < "2026-01-20 10:00")]
        self.assertAlmostEqual(data.fetch_24h_quote_volume("BTC"), float((window["close"] * window["volume"]).sum()))


if __name__ == "__main__":
    unittest.main()
