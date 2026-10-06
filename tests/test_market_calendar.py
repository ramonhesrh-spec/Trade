import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app import market_calendar as mc
from app.replay import strategy_scan as ss

UTC = timezone.utc


class CalendarTest(unittest.TestCase):
    def test_funding_three_times_a_day(self):
        ms = mc.moments(datetime(2026, 10, 7, 0, 0, tzinfo=UTC), datetime(2026, 10, 7, 23, 59, tzinfo=UTC))
        self.assertEqual([m["at"].hour for m in ms if m["kind"] == "funding"], [0, 8, 16])

    def test_us_open_follows_daylight_saving_and_skips_weekend(self):
        summer = [m for m in mc.moments(datetime(2026, 10, 7, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC)) if m["kind"] == "vs_open"]
        winter = [m for m in mc.moments(datetime(2026, 12, 7, tzinfo=UTC), datetime(2026, 12, 8, tzinfo=UTC)) if m["kind"] == "vs_open"]
        self.assertEqual((summer[0]["at"].hour, summer[0]["at"].minute), (13, 30))
        self.assertEqual((winter[0]["at"].hour, winter[0]["at"].minute), (14, 30))
        weekend = mc.moments(datetime(2026, 10, 10, tzinfo=UTC), datetime(2026, 10, 11, 23, tzinfo=UTC))
        self.assertFalse([m for m in weekend if m["kind"] == "vs_open"])

    def test_monthly_expiry_is_last_friday_0800_utc(self):
        ms = [m for m in mc.moments(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 31, 23, tzinfo=UTC)) if m["kind"] == "opties_expiry"]
        self.assertEqual(len(ms), 1)
        self.assertEqual((ms[0]["at"].day, ms[0]["at"].weekday(), ms[0]["at"].hour), (30, 4, 8))

    def test_macro_file_is_read_and_missing_file_is_fine(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "m.csv"
            with mock.patch.object(mc, "MACRO_FILE", f):
                self.assertEqual(mc.macro_moments(), [])
                f.write_text("at,label\n2026-10-14T12:30:00+00:00,CPI\nkapot,x\n")
                got = mc.macro_moments()
        self.assertEqual([(m["label"], m["at"].hour) for m in got], [("CPI", 12)])


class CalendarScanTest(unittest.TestCase):
    def closes(self, planted):
        rng = np.random.default_rng(3)
        idx = pd.date_range("2026-01-01", periods=9000, freq="5min", tz="UTC")
        r = rng.normal(0, 0.001, len(idx))
        if planted:      # na elke funding-reset gaat de koers door in de kant van het halfuur ervoor
            for i, t in enumerate(idx):
                if t.hour in (0, 8, 16) and t.minute == 0 and i > 8:
                    r[i - 5:i + 1] += 0.0005 * np.sign(rng.random() - 0.5)
                    r[i + 1:i + 7] += np.sign(r[i - 5:i + 1].sum()) * 0.0012
        return pd.DataFrame({"BTC": 100 * np.exp(np.cumsum(r)), "ETH": 100 * np.exp(np.cumsum(r + rng.normal(0, 0.0003, len(idx))))}, index=idx)

    def rows(self, planted):
        c = self.closes(planted)
        ms = mc.moments(c.index[0].to_pydatetime(), c.index[-1].to_pydatetime())
        return ss.evaluate(c, 6, ev=ss.calendar_events(c, ms)), c, ms

    def test_planted_drift_after_funding_is_found_and_noise_is_not(self):
        rows, _, _ = self.rows(True)
        hit = next(r for r in rows if r.idee == "funding" and r.horizon == "30m" and r.kant == "volgen")
        self.assertGreater(hit.net, 5)
        rows, _, _ = self.rows(False)
        self.assertFalse(any(ss.passes(r) for r in rows if r.idee == "funding"))

    def test_vol_multiple_sees_bigger_moves_after_planted_moments(self):
        _, c, ms = self.rows(True)
        self.assertGreater(ss.vol_multiple(c, ms)["funding"], 1.2)


if __name__ == "__main__":
    unittest.main()
