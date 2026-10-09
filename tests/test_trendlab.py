import unittest

import numpy as np
import pandas as pd

from app.replay import trendlab as tl


def bars(n=500, minutes=240, seed=1, drift=0.0, noise=0.004):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq=f"{minutes}min", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(drift, noise, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, n))
    return pd.DataFrame({"timestamp": idx, "open": open_, "high": high, "low": low, "close": close, "volume": 1.0})


def trending(n=500, start=300, slope=0.01):
    """Vlak, dan een steile stijging: een breuk omhoog met doorlopende trend."""
    b = bars(n, noise=0.001)
    close = b["close"].to_numpy().copy()
    close[start:] = close[start - 1] * np.exp(np.cumsum(np.full(n - start, slope)))
    b["close"] = close
    b["open"] = np.concatenate([[close[0]], close[:-1]])
    b["high"] = np.maximum(b["open"], b["close"]) * 1.001
    b["low"] = np.minimum(b["open"], b["close"]) * 0.999
    return b


class ExitTest(unittest.TestCase):
    def prepared(self, rows):
        df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
        df["timestamp"] = pd.date_range("2025-01-01", periods=len(df), freq="4h", tz="UTC")
        df["atr"] = 1.0
        return df

    def test_trail_follows_the_extreme_and_exits_on_the_ratcheted_stop(self):
        b = self.prepared([(100, 101, 99.5, 100.5), (100.5, 106, 100, 105.5), (105.5, 110, 105, 109.5), (109.5, 109.8, 105.9, 106.0)])
        r, j, out = tl.exit_trail(b, 0, 1, 100.0, 98.0, 3.0)         # risico 2, extreem 110, stop op 107 na bar 2
        self.assertEqual((j, out), (3, "stop"))
        self.assertAlmostEqual(r, (107.0 - 100.0) / 2.0)

    def test_gap_through_the_stop_fills_at_the_open_and_never_better_than_the_stop(self):
        b = self.prepared([(100, 100.5, 99.8, 100.2), (96.0, 97.0, 95.0, 96.0)])
        r, j, out = tl.exit_trail(b, 0, 1, 100.0, 98.0, 3.0)
        self.assertEqual(out, "stop")
        self.assertAlmostEqual(r, (96.0 - 100.0) / 2.0)               # open van het gat, slechter dan -1R

    def test_short_trail_mirrors_long(self):
        b = self.prepared([(100, 100.5, 99, 99.2), (99.2, 99.4, 94, 94.5), (94.5, 98.0, 94.2, 97.5)])
        r, _, out = tl.exit_trail(b, 0, -1, 100.0, 102.0, 3.0)         # laagste 94, stop 97 na bar 1
        self.assertEqual(out, "stop")
        self.assertAlmostEqual(r, (100.0 - 97.0) / 2.0)

    def test_target_exit_stop_first_and_time_exit(self):
        b = self.prepared([(100, 103, 98, 101), (101, 102, 100, 101)])
        self.assertEqual(tl.exit_target(b, 0, 1, 100.0, 98.5, 2.0, 5)[2], "stop")        # stop en doel in één candle: stop
        b2 = self.prepared([(100, 100.5, 99.8, 100.2)] * 4)
        r, j, out = tl.exit_target(b2, 0, 1, 100.0, 99.0, 2.0, 3)
        self.assertEqual((out, j), ("tijd", 2))


class SignalTest(unittest.TestCase):
    def test_donchian_finds_the_breakout_and_trend_filter_removes_counter_trend_shorts(self):
        b = tl.prepare(trending())
        sig = tl.donchian_signals(b, 20, False)
        self.assertTrue(any(s == 1 and i >= 300 for i, s in sig))                    # breuk omhoog
        filtered = tl.donchian_signals(b, 20, True)
        self.assertTrue(all(s == 1 for i, s in filtered if i >= 300))

    def test_sweep_through_previous_day_high_and_close_back_is_a_short_once(self):
        b = bars(400, minutes=60, noise=0.0005)
        ts = b["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
        day_before = (ts.dt.floor("D") == ts.dt.floor("D").iloc[300] - pd.Timedelta(days=1))
        level = float(b.loc[day_before, "high"].max())
        i = 300 + 3
        b.loc[i, "high"] = level * 1.01
        b.loc[i, "close"] = level * 0.998
        b.loc[i, "open"] = level * 0.999
        sig = tl.sweep_signals(tl.prepare(b), "D")
        self.assertIn((i, -1), sig)
        self.assertEqual(sum(1 for k, s in sig if s == -1 and abs(k - i) < tl.SWEEP_COOLDOWN), 1)


class RunTest(unittest.TestCase):
    def test_trend_variant_wins_on_a_real_trend_and_costs_follow_the_stop(self):
        v = [x for x in tl.VARIANTS if x.name == "DON20"][0]
        t = tl.run_variant(v, trending(), cost_pct=0.06)
        self.assertFalse(t.empty)
        long_trade = t[t["direction"] == "long"].iloc[0]
        self.assertGreater(long_trade["gross"], 1.0)
        self.assertLess(long_trade["net"], long_trade["gross"])
        zero = tl.run_variant(v, trending(), cost_pct=0.0)
        self.assertAlmostEqual(float(zero["net"].iloc[0]), float(zero["gross"].iloc[0]))

    def test_one_position_at_a_time_for_trailing_rules(self):
        v = [x for x in tl.VARIANTS if x.name == "DON20"][0]
        t = tl.run_variant(v, trending())
        starts = t["i"].tolist()
        ends = [s + int(n) for s, n in zip(starts, t["bars"])]
        self.assertTrue(all(starts[k + 1] > ends[k] for k in range(len(starts) - 1)))

    def test_placebo_is_reproducible_and_matches_the_trade_count(self):
        v = [x for x in tl.VARIANTS if x.name == "DON20"][0]
        real = tl.run_variant(v, trending())
        a, b2 = tl.placebo_variant(v, trending(), real), tl.placebo_variant(v, trending(), real)
        self.assertEqual(len(a), len(real))
        pd.testing.assert_frame_equal(a, b2)


class EvaluateTest(unittest.TestCase):
    def frame(self, nets, risk=2.0):
        n = len(nets)
        return pd.DataFrame({"at": pd.date_range("2025-01-01", periods=n, freq="1D", tz="UTC"), "net": nets, "gross": nets, "risk_pct": risk})

    def test_passes_only_when_both_halves_margin_and_placebo_agree(self):
        good = self.frame([1.0, -0.5] * 300)                                     # gemiddeld +0,25R, beide helften positief
        verdict = tl.evaluate(good, pd.DataFrame({"net": [-0.1] * 50, "gross": [-0.1] * 50}))
        self.assertTrue(verdict["passes"], verdict["reason"])

    def test_fails_when_the_second_half_turns_negative_or_it_does_not_beat_random(self):
        bad_second = self.frame([2.0, -0.5] * 150 + [-1.0, 0.5] * 150)
        self.assertFalse(tl.evaluate(bad_second, pd.DataFrame({"net": [0.0] * 50, "gross": [0.0] * 50})) ["passes"])
        good = self.frame([1.0, -0.5] * 300)
        v = tl.evaluate(good, pd.DataFrame({"net": [0.5] * 50, "gross": [0.5] * 50}))
        self.assertFalse(v["passes"])
        self.assertIn("beter dan willekeurig", v["reason"])

    def test_small_samples_never_pass(self):
        v = tl.evaluate(self.frame([1.0] * 20), pd.DataFrame({"net": [0.0] * 5, "gross": [0.0] * 5}))
        self.assertFalse(v["passes"])
        self.assertIn("genoeg trades", v["reason"])


class EvaluateStrictTest(unittest.TestCase):
    def frame(self, nets, start="2024-01-01", step_hours=4):
        at = pd.date_range(start, periods=len(nets), freq=f"{step_hours}h", tz="UTC")
        return pd.DataFrame({"at": at, "net": nets, "gross": nets, "risk_pct": 5.0})

    def test_too_few_trades_never_pass(self):
        t = self.frame([0.5] * 100)
        out = tl.evaluate(t, self.frame([0.0] * 100))
        self.assertFalse(out["passes"])
        self.assertIn("genoeg trades", out["reason"])

    def test_edge_must_beat_placebo_by_margin(self):
        nets = [0.3, -0.1] * 300
        out = tl.evaluate(self.frame(nets), self.frame([0.29, -0.1] * 300))
        self.assertFalse(out["passes"])
        self.assertIn("duidelijk beter dan willekeurig", out["reason"])

    def test_clear_edge_passes(self):
        nets = [0.3, -0.1] * 300
        out = tl.evaluate(self.frame(nets), self.frame([0.0, -0.1] * 300))
        self.assertTrue(out["passes"], out["reason"])
        self.assertIn("week_ci", out)


if __name__ == "__main__":
    unittest.main()
