import unittest

import numpy as np
import pandas as pd

from app.replay import aplus, flow
from tests.replay.test_liquidity_levels import frame

T0 = pd.Timestamp("2026-03-02", tz="UTC")


def klines(start_ms, n):
    return [[start_ms + i * 60000, "1", "1", "1", "1", "10", start_ms + i * 60000 + 59999, "10", 5 + i, "7", "7", "0"] for i in range(n)]


class DownloadTest(unittest.TestCase):
    def test_pages_forward_and_reads_taker_columns(self):
        calls = []

        def get(params):
            calls.append(params["startTime"])
            n = min(flow.PAGE, max(0, (params["endTime"] - params["startTime"]) // 60000))
            return klines(params["startTime"], n)

        end = T0 + pd.Timedelta(minutes=2000)
        df = flow.download_flow("BTC", T0, end, get)
        self.assertEqual(len(df), 2000)
        self.assertEqual(len(calls), 2)
        self.assertEqual((df["volume"].iloc[0], df["buy_volume"].iloc[0], df["trades"].iloc[1]), (10.0, 7.0, 6))
        self.assertTrue(df["timestamp"].is_monotonic_increasing and df["timestamp"].is_unique)

    def test_delta_range_and_zero_volume(self):
        d = flow.delta([10, 0, 5, 0], [10, 10, 10, 0])
        np.testing.assert_allclose(d, [1.0, -1.0, 0.0, 0.0])

    def test_ensure_flow_appends_only_new_minutes(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        seen = []

        def get(params):
            seen.append(params["startTime"])
            return klines(params["startTime"], min(50, (params["endTime"] - params["startTime"]) // 60000))

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(flow, "CACHE_DIR", Path(tmp)):
            first = flow.ensure_flow("BTC", T0, T0 + pd.Timedelta(minutes=50), get)
            second = flow.ensure_flow("BTC", T0, T0 + pd.Timedelta(minutes=100), get)
        self.assertEqual((len(first), len(second)), (50, 100))
        self.assertTrue(str(second["timestamp"].dtype).startswith("datetime64") and str(second["timestamp"].dtype).endswith("UTC]"))
        self.assertEqual(seen[1], int((T0 + pd.Timedelta(minutes=50)).timestamp() * 1000))


class NothingNewTest(unittest.TestCase):
    def test_second_call_with_no_new_minutes_keeps_datetime_dtype(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        def get(params):
            return klines(params["startTime"], min(10, (params["endTime"] - params["startTime"]) // 60000))

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(flow, "CACHE_DIR", Path(tmp)):
            flow.ensure_flow("BTC", T0, T0 + pd.Timedelta(minutes=10), get)
            again = flow.ensure_flow("BTC", T0, T0 + pd.Timedelta(minutes=10), get)
        self.assertEqual(len(again), 10)
        self.assertTrue(str(again["timestamp"].dtype).startswith("datetime64") and str(again["timestamp"].dtype).endswith("UTC]"))


class FlowFeaturesTest(unittest.TestCase):
    def make(self, seed=1):
        f = frame(days=25, seed=seed, plant=True)
        rng = np.random.default_rng(seed)
        vol = rng.uniform(5, 15, len(f))
        buy = vol * rng.uniform(0.3, 0.7, len(f))
        return f, pd.DataFrame({"timestamp": f["timestamp"], "volume": vol, "buy_volume": buy, "trades": rng.integers(50, 150, len(f))})

    def test_dataset_gets_flow_columns_normalised_to_trade_direction(self):
        f, fl = self.make()
        data = aplus.build_dataset(f, flow_1m=fl)
        for c in aplus.FLOW_HYPOTHESES:
            self.assertIn(c, data.columns)
        self.assertGreater(data["flow_absorb"].notna().sum(), 20)
        self.assertTrue(data["flow_absorb"].abs().max() <= 1.0)

    def test_flow_absorb_flips_sign_with_direction(self):
        f, fl = self.make()
        d = aplus.build_dataset(f, flow_1m=fl)
        i5 = fl.set_index("timestamp").resample("5min", origin="epoch", label="left", closed="left").sum()
        sweep = d.iloc[0]
        bar_start = sweep["at"] - pd.Timedelta(minutes=5)
        delta = float(flow.delta(i5.at[bar_start, "buy_volume"], i5.at[bar_start, "volume"]))
        expect = -delta if sweep["direction"] == "long" else delta
        self.assertAlmostEqual(sweep["flow_absorb"], expect, places=6)

    def test_flow_features_do_not_look_ahead(self):
        f, fl = self.make()
        full = aplus.build_dataset(f, flow_1m=fl)
        cut = f["timestamp"].iloc[int(len(f) * 0.6)]
        short = aplus.build_dataset(f[f["timestamp"] < cut], flow_1m=fl[fl["timestamp"] < cut])
        a = full[full["at"] < cut - pd.Timedelta(days=1)].reset_index(drop=True)
        b = short[short["at"] < cut - pd.Timedelta(days=1)].reset_index(drop=True)
        self.assertEqual(len(a), len(b))
        pd.testing.assert_frame_equal(a[aplus.FLOW_HYPOTHESES], b[aplus.FLOW_HYPOTHESES], check_dtype=False)


if __name__ == "__main__":
    unittest.main()
