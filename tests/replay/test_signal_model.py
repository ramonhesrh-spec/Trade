import unittest

import numpy as np
import pandas as pd

from app.replay import signal_model as sm
from tests.replay.test_liquidity_levels import frame


def synthetic_panel(effect=0.0, n=20000, seed=0):
    rng = np.random.default_rng(seed)
    p = pd.DataFrame({"at": pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(np.arange(n) * 5, unit="min")})
    for f in sm.FEATURES:
        p[f] = rng.normal(size=n)
    for label, h in sm.HORIZONS.items():
        p[f"fwd_{label}"] = rng.normal(0, 40, n) + effect * p["d15"] * 40
    return p


class PanelTest(unittest.TestCase):
    def make(self):
        f = frame(days=12, seed=2)
        rng = np.random.default_rng(2)
        vol = rng.uniform(5, 15, len(f))
        return f, pd.DataFrame({"timestamp": f["timestamp"], "volume": vol, "buy_volume": vol * rng.uniform(0.3, 0.7, len(f)),
                                "trades": rng.integers(50, 150, len(f))})

    def test_panel_has_features_and_forward_returns_with_entry_delay(self):
        f, fl = self.make()
        p = sm.build_panel(f, fl)
        for c in sm.FEATURES + ["fwd_15m", "fwd_30m", "fwd_60m"]:
            self.assertIn(c, p.columns)
        i = 500
        expect = (p["close"].iloc[i + 1 + 3] / p["close"].iloc[i + 1] - 1) * 1e4
        self.assertAlmostEqual(p["fwd_15m"].iloc[i], expect)

    def test_features_do_not_look_ahead(self):
        f, fl = self.make()
        full = sm.build_panel(f, fl)
        cut = f["timestamp"].iloc[int(len(f) * 0.6)]
        short = sm.build_panel(f[f["timestamp"] < cut], fl[fl["timestamp"] < cut])
        n = int(len(short) * 0.9)
        pd.testing.assert_frame_equal(full[sm.FEATURES].iloc[400:n].reset_index(drop=True), short[sm.FEATURES].iloc[400:n].reset_index(drop=True), check_dtype=False)


class IcAndModelTest(unittest.TestCase):
    def test_planted_predictor_is_found_by_ic_and_model_and_noise_is_not(self):
        p = synthetic_panel(effect=0.5)
        cut = p["at"].quantile(0.7)
        d15 = [r for r in sm.information_coefficients(p, cut) if r.feature == "d15" and r.horizon == "15m"][0]
        self.assertGreater(d15.ic_test, 0.1)
        self.assertGreater(d15.t_test, 3)
        res = sm.evaluate_model(p, "15m", cut, cost_bps=6, permutations=40)
        self.assertGreater(res.net_bps, 5)
        self.assertLess(res.p_value, 0.1)
        noise = synthetic_panel(effect=0.0, seed=5)
        res = sm.evaluate_model(noise, "30m", noise["at"].quantile(0.7), cost_bps=6, permutations=40)
        self.assertLess(res.net_bps, 12)                     # zonder voorspeller geen betekenisvol positief resultaat (ruis van ongeveer 40 bp per trade)
        self.assertGreater(res.p_value, 0.1)

    def test_ridge_recovers_known_weights(self):
        rng = np.random.default_rng(1)
        X = rng.normal(size=(5000, 3))
        y = 2 * X[:, 0] - 1 * X[:, 2] + rng.normal(0, 0.1, 5000)
        m = sm.ridge_fit(X, y, lam=1)
        pred = sm.ridge_predict(m, X)
        self.assertGreater(np.corrcoef(pred, y)[0, 1], 0.99)


if __name__ == "__main__":
    unittest.main()
