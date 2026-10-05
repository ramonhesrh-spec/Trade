import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import derivs

T0 = pd.Timestamp("2026-10-01", tz="UTC")


def fake_get(calls=None):
    def get(path, params):
        if calls is not None:
            calls.append((path, params["startTime"]))
        start = pd.Timestamp(params["startTime"], unit="ms", tz="UTC")
        if path == "/fapi/v1/fundingRate":
            return [{"fundingTime": int(T0.timestamp() * 1000), "fundingRate": "0.0001"}]
        times = [T0 + pd.Timedelta(minutes=5 * i) for i in range(3)]
        times = [t for t in times if t >= start]
        key = {"/futures/data/openInterestHist": "sumOpenInterestValue",
               "/futures/data/takerlongshortRatio": "buySellRatio"}.get(path, "longShortRatio")
        return [{"timestamp": int(t.timestamp() * 1000), key: "2.0"} for t in times]
    return get


class DerivsTest(unittest.TestCase):
    def test_collect_writes_and_appends_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(derivs, "DERIVS_DIR", Path(tmp)):
            df = derivs.collect("BTC", now=T0 + pd.Timedelta(days=1), get=fake_get())
            self.assertEqual(len(df), 3)
            self.assertEqual(list(df.columns), derivs.COLUMNS[1:])
            self.assertTrue((df["funding"] == 0.0001).all())
            df2 = derivs.collect("BTC", now=T0 + pd.Timedelta(days=2), get=fake_get())
            self.assertEqual(len(df2), 3)

    def test_second_run_only_asks_since_last_row(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(derivs, "DERIVS_DIR", Path(tmp)):
            derivs.collect("BTC", now=T0 + pd.Timedelta(days=1), get=fake_get())
            calls = []
            derivs.collect("BTC", now=T0 + pd.Timedelta(days=2), get=fake_get(calls))
            last = T0 + pd.Timedelta(minutes=10) - pd.Timedelta(hours=1)
            self.assertTrue(all(c[1] >= int(last.timestamp() * 1000) for c in calls if "futures/data" in c[0]))


if __name__ == "__main__":
    unittest.main()
