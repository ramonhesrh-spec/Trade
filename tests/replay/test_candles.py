import unittest

import pandas as pd

from app.replay import candles
from tests.replay.fixtures import make_base


class DownloadTest(unittest.TestCase):
    def test_paginates_dedups_and_drops_forming_candle(self):
        base = make_base(days=30)
        now = base["timestamp"].iloc[-1] + pd.Timedelta(minutes=5)  # laatste candle is nog niet gesloten

        def fake_fetch(coin, timeframe, limit, since):
            start = pd.Timestamp(since, unit="ms", tz="UTC")
            return base[base["timestamp"] >= start].head(limit).reset_index(drop=True)

        df = candles.download_candles("BTC", years=30 / 365, fetch=fake_fetch, now=now)
        self.assertTrue(df["timestamp"].is_unique)
        self.assertTrue(df["timestamp"].is_monotonic_increasing)
        self.assertEqual(df["timestamp"].iloc[-1], base["timestamp"].iloc[-2])
        self.assertGreater(len(df), 2800)


if __name__ == "__main__":
    unittest.main()
