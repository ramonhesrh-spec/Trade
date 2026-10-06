import unittest

import numpy as np
import pandas as pd

from app.replay import strategy_scan as ss


def make_closes(lead_lag: bool, n=6000, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    btc_r = rng.normal(0, 0.001, n)
    btc_r[rng.random(n) < 0.01] *= 8                      # uitschieters
    if lead_lag:
        alt_r = np.roll(btc_r, 3) * 1.0 + rng.normal(0, 0.0003, n)   # alt volgt BTC drie candles later
    else:
        alt_r = rng.normal(0, 0.001, n)
    return pd.DataFrame({"BTC": 100 * np.exp(np.cumsum(btc_r)), "ETH": 100 * np.exp(np.cumsum(alt_r)),
                         "SOL": 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))}, index=idx)


def row(rows, idee, horizon, kant):
    return next(r for r in rows if r.idee == idee and r.horizon == horizon and r.kant == kant)


class StrategyScanTest(unittest.TestCase):
    def test_finds_planted_lead_lag(self):
        r = row(ss.evaluate(make_closes(True), cost_bps=6), "A voorloop", "15m", "volgen")
        self.assertGreater(r.net, 5)
        self.assertGreater(r.t, 2)

    def test_random_walk_has_no_lead_lag_edge(self):
        rows = ss.evaluate(make_closes(False), cost_bps=6)
        r = row(rows, "A voorloop", "15m", "volgen")
        self.assertLess(r.net, 1)
        self.assertFalse(any(ss.passes(x) for x in rows if x.idee == "A voorloop"))

    def test_no_lookahead_signal_uses_only_past(self):
        a = make_closes(True)
        ev1 = ss.events(a)
        b = a.copy()
        b.iloc[-100:] = b.iloc[-100:] * 3          # alleen de toekomst verandert
        ev2 = ss.events(b)
        cutoff = a.index[-101]
        pd.testing.assert_frame_equal(ev1[ev1["at"] < cutoff].reset_index(drop=True),
                                      ev2[ev2["at"] < cutoff].reset_index(drop=True))

    def test_decluster_skips_overlap(self):
        t = pd.Timestamp("2026-01-01", tz="UTC")
        ev = pd.DataFrame({"at": [t, t + pd.Timedelta(minutes=5), t + pd.Timedelta(minutes=20)],
                           "coin": "ETH", "idee": "A voorloop", "richting": 1})
        self.assertEqual(len(ss.decluster(ev, 3)), 2)

    def test_forward_return_uses_entry_delay(self):
        s = pd.Series([100.0, 100.0, 110.0, 121.0], index=pd.date_range("2026-01-01", periods=4, freq="5min"))
        self.assertAlmostEqual(ss.forward_bps(s, 1).iloc[0], 1000.0)   # instap op candle 1 (100), uit op candle 2 (110)


if __name__ == "__main__":
    unittest.main()
