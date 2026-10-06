import unittest

import numpy as np
import pandas as pd

from app.replay import regime


def btc(minutes=60 * 24 * 70, calm_until=60 * 24 * 40, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=minutes, freq="1min", tz="UTC")
    sigma = np.where(np.arange(minutes) < calm_until, 0.0002, 0.0008)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 1, minutes) * sigma))
    return pd.DataFrame({"timestamp": idx, "open": np.concatenate([[close[0]], close[:-1]]), "high": close, "low": close, "close": close, "volume": 1.0})


class RegimeTest(unittest.TestCase):
    def test_volatility_jump_is_labelled_restless_and_calm_stays_normal(self):
        f = btc()
        ratio = regime.vol_ratio(f)
        calm = ratio.iloc[60 * 24 * 38]
        after_jump = ratio.iloc[60 * 24 * 42]
        self.assertEqual(regime.label(calm), "normaal")
        self.assertEqual(regime.label(after_jump), "onrustig")

    def test_ratio_uses_only_the_past(self):
        f = btc()
        full = regime.vol_ratio(f)
        short = regime.vol_ratio(f.iloc[: 60 * 24 * 45])
        i = 60 * 24 * 44
        self.assertAlmostEqual(float(full.iloc[i]), float(short.iloc[i]))

    def test_tag_is_asof_and_tail_events_are_declustered(self):
        f = btc()
        ratio = regime.vol_ratio(f)
        tags = regime.tag(pd.Series([f["timestamp"].iloc[60 * 24 * 45]]), ratio)
        self.assertEqual(tags.iloc[0], "onrustig")
        g = f.copy()
        g.loc[5000:5059, "close"] = np.linspace(100, 90, 60)         # -10% in een uur
        g.loc[5060:, "close"] = g.loc[5060:, "close"] * 0.9
        ev = regime.tail_events(g)
        self.assertGreaterEqual(len(ev), 1)
        self.assertLess(ev["move_pct"].iloc[0], 0)


if __name__ == "__main__":
    unittest.main()
