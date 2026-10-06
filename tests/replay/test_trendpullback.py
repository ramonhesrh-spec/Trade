import unittest

import numpy as np
import pandas as pd

from app.replay import trendpullback as tp


def frame(days=40, direction=1, seed=2, wave=True):
    rng = np.random.default_rng(seed)
    n = days * 1440
    idx = pd.date_range("2026-03-02", periods=n, freq="1min", tz="UTC")
    t = np.arange(n)
    trend = direction * 0.004 * t
    saw = np.zeros(n)
    if wave:                      # 6 uur per golf: 2 uur omhoog (impuls), 4 uur terug naar de helft, dan opnieuw
        phase = t % 360
        saw = np.where(phase < 120, phase / 120.0, 1.0 - 0.5 * (phase - 120) / 240.0) * 4.0 * direction
    p = 200 + trend + saw + rng.normal(0, 0.03, n).cumsum() * 0.2
    o = np.concatenate([[p[0]], p[:-1]])
    return pd.DataFrame({"timestamp": idx, "open": o, "high": np.maximum(o, p) + 0.05, "low": np.minimum(o, p) - 0.05, "close": p, "volume": 1.0})


class TrendPullbackTest(unittest.TestCase):
    def test_uptrend_with_waves_gives_long_entries_only(self):
        b = tp.prepare(frame())
        e = tp.entries(*b)
        self.assertGreater(len(e), 5)
        self.assertEqual(set(e["direction"]), {"long"})
        self.assertTrue((e["stop"] < e["entry"]).all())
        self.assertEqual(e["impulse_id"].duplicated().sum(), 0)           # één instap per impuls

    def test_downtrend_gives_short_entries_only(self):
        e = tp.entries(*tp.prepare(frame(direction=-1)))
        self.assertGreater(len(e), 5)
        self.assertEqual(set(e["direction"]), {"short"})

    def test_no_entries_without_trend_alignment(self):
        rng = np.random.default_rng(5)
        n = 40 * 1440
        idx = pd.date_range("2026-03-02", periods=n, freq="1min", tz="UTC")
        p = 100 + np.sin(np.arange(n) / 600.0) * 3 + rng.normal(0, 0.02, n).cumsum() * 0.1     # zijwaarts: de trend op 4u en 1u wisselt
        o = np.concatenate([[p[0]], p[:-1]])
        f = pd.DataFrame({"timestamp": idx, "open": o, "high": np.maximum(o, p) + 0.02, "low": np.minimum(o, p) - 0.02, "close": p, "volume": 1.0})
        e = tp.entries(*tp.prepare(f))
        self.assertLess(len(e), len(tp.entries(*tp.prepare(frame()))))

    def test_entries_do_not_depend_on_the_future(self):
        f = frame()
        full = tp.entries(*tp.prepare(f))
        keep = len(f) - 3000
        part = tp.entries(*tp.prepare(f.iloc[:keep]))
        cut_at = f["timestamp"].iloc[keep - 600]
        a = full[full["at"] <= cut_at][["at", "direction", "entry", "stop"]].reset_index(drop=True)
        b = part[part["at"] <= cut_at][["at", "direction", "entry", "stop"]].reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)

    def test_run_gives_follow_and_mirror_rows_and_follow_beats_mirror_on_planted_trend(self):
        t = tp.run("BTC", frame())
        self.assertFalse(t.empty)
        self.assertEqual(set(t["kind"]), {"mee", "spiegel"})
        mee = t[(t["kind"] == "mee") & (t["exit"] == "2R")]["r_net"].mean()
        mirror = t[(t["kind"] == "spiegel") & (t["exit"] == "2R")]["r_net"].mean()
        self.assertGreater(mee, mirror)

    def test_targets_include_impulse_top_only_when_far_enough(self):
        near = tp.targets("long", 100.0, 99.0, 100.8)
        far = tp.targets("long", 100.0, 99.0, 102.0)
        self.assertNotIn("impuls", near)
        self.assertEqual(far["impuls"], 102.0)


if __name__ == "__main__":
    unittest.main()
