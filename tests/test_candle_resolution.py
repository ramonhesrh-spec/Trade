import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from app.replay import candles


class CandleResolutionTest(unittest.TestCase):
    def test_load_candles_geeft_altijd_nanoseconden_zodat_merge_asof_werkt(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.csv")
            pd.DataFrame({"timestamp": ["2026-01-01T00:00:00+00:00"], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]}).to_csv(path, index=False)
            with mock.patch.object(candles, "cache_path", return_value=path):
                df = candles.load_candles("BTC", "1h")
        self.assertEqual(str(df["timestamp"].dtype), "datetime64[ns, UTC]")
        ms = pd.DataFrame({"timestamp": pd.to_datetime([1767225600000], unit="ms", utc=True).astype("datetime64[ns, UTC]"), "x": [1]})
        merged = pd.merge_asof(df[["timestamp"]], ms, on="timestamp")
        self.assertEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main()
