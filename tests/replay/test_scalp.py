import unittest

import numpy as np
import pandas as pd

from app.replay import scalp


def frames(minutes=60 * 24 * 40, seed=3, lag=3, follow=True):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-02", periods=minutes, freq="1min", tz="UTC")
    r = rng.normal(0, 0.0004, minutes)
    jumps = rng.random(minutes) < 1 / 400
    r[jumps] += rng.choice([-0.008, 0.008], jumps.sum())
    btc_close = 100 * np.exp(np.cumsum(r))
    alt_r = rng.normal(0, 0.0003, minutes)
    if follow:
        alt_r[lag:] += 1.2 * r[:-lag]
    alt_close = 50 * np.exp(np.cumsum(alt_r))

    def ohlc(c):
        o = np.concatenate([[c[0]], c[:-1]])
        return pd.DataFrame({"timestamp": idx, "open": o, "high": np.maximum(o, c) * 1.0002, "low": np.minimum(o, c) * 0.9998,
                             "close": c, "volume": rng.gamma(2.0, 1.0, minutes)})
    return {"BTC": ohlc(btc_close), "ETH": ohlc(alt_close)}


class ScalpTest(unittest.TestCase):
    def test_lag_to_btc_is_found_with_positive_gross_and_placebo_is_flat(self):
        f = scalp.align(frames())
        cut = f["BTC"].index[int(len(f["BTC"]) * 0.7)]
        t = scalp.run_coin("ETH", f, cut)
        lead = t[t["test"] == "LEAD k=1 achterstand"]
        self.assertGreater(len(lead), 50)
        self.assertGreater(lead[lead["h"] == 5]["gross_bp"].mean(), 10)
        plac = scalp.placebo(f, t)
        self.assertLess(abs(plac["gross_bp"].mean()), 3)
        rows = scalp.summarize(t, plac, cut)
        self.assertTrue(any(scalp.passes(r) for r in rows if r.test.startswith("LEAD")))

    def test_independent_alt_shows_no_lead_edge(self):
        f = scalp.align(frames(follow=False))
        cut = f["BTC"].index[int(len(f["BTC"]) * 0.7)]
        t = scalp.run_coin("ETH", f, cut)
        rows = scalp.summarize(t, scalp.placebo(f, t), cut)
        self.assertFalse([r for r in rows if r.test.startswith("LEAD") and scalp.passes(r)])

    def test_events_do_not_depend_on_the_future(self):
        f = scalp.align(frames())
        cut = f["BTC"].index[int(len(f["BTC"]) * 0.7)]
        full_idx, _ = scalp.lead_events(f["BTC"], f["ETH"], 3, cut, True)
        keep = len(f["BTC"]) - 5000
        short = {c: v.iloc[:keep] for c, v in f.items()}
        short_idx, _ = scalp.lead_events(short["BTC"], short["ETH"], 3, cut, True)
        self.assertEqual(list(full_idx[full_idx < keep - 20]), list(short_idx[short_idx < keep - 20]))

    def test_flow_variants_run_when_flow_is_given(self):
        f = scalp.align(frames())
        cut = f["BTC"].index[int(len(f["BTC"]) * 0.7)]
        idx = f["ETH"].index
        rng = np.random.default_rng(1)
        vol = rng.gamma(2.0, 1.0, len(idx))
        flow = pd.DataFrame({"timestamp": idx, "volume": vol, "buy_volume": vol * rng.uniform(0.3, 0.7, len(idx)), "trades": 10})
        t = scalp.run_coin("ETH", f, cut, {"ETH": flow})
        self.assertTrue({"FLOW k=1 mee", "FLOW k=3 tegen"} <= set(t["test"]))

    def test_exhaustion_minute_is_found_and_faded(self):
        rng = np.random.default_rng(2)
        n = 6000
        idx = pd.date_range("2026-03-02", periods=n, freq="1min", tz="UTC")
        c = 100 + np.cumsum(rng.normal(0, 0.02, n))
        df = pd.DataFrame({"open": np.concatenate([[c[0]], c[:-1]]), "close": c, "volume": rng.gamma(2.0, 1.0, n)}, index=idx)
        df["high"] = np.maximum(df["open"], df["close"]) + 0.01
        df["low"] = np.minimum(df["open"], df["close"]) - 0.01
        i = 5000                                              # omhoog-minuut met enorme range, enorm volume en een lange bovenlont
        df.iloc[i, df.columns.get_loc("close")] = df["open"].iloc[i] + 0.3
        df.iloc[i, df.columns.get_loc("high")] = df["open"].iloc[i] + 3.0
        df.iloc[i, df.columns.get_loc("volume")] = 400.0
        cut = idx[4000]
        fade_idx, fade_dir = scalp.spike_events(df, cut, fade=True)
        follow_idx, follow_dir = scalp.spike_events(df, cut, fade=False)
        self.assertIn(i, list(fade_idx))
        self.assertEqual(fade_dir[list(fade_idx).index(i)], -1.0)
        self.assertEqual(follow_dir[list(follow_idx).index(i)], 1.0)

    def test_decluster_keeps_events_apart(self):
        self.assertEqual(list(scalp._decluster(np.array([1, 3, 12, 14, 30]))), [1, 12, 30])


class UniverseTest(unittest.TestCase):
    def test_screen_sees_lag_for_follower_and_not_for_independent_alt(self):
        from app.replay import scalp_universe as su
        lagged = frames(follow=True)
        indep = frames(follow=False)
        a = su.screen(lagged["BTC"], lagged["ETH"])
        b = su.screen(indep["BTC"], indep["ETH"])
        self.assertGreater(a["achterstand_bp"], 20)
        self.assertGreater(a["t_lag"], 10)
        self.assertLess(abs(b["achterstand_bp"]), 5)
        self.assertLess(abs(b["t_lag"]), 4)


if __name__ == "__main__":
    unittest.main()
