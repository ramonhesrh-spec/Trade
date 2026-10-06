import unittest

import numpy as np
import pandas as pd

from app.replay import breakretest as br
from app.replay.lab import make_bars


def frame(minutes=60 * 24 * 6, seed=1, plant=False):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-02", periods=minutes, freq="1min", tz="UTC")
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.0003, len(idx))))
    if plant:       # stijgend kanaal, breuk naar beneden, terugkeer naar de lijn, daarna een val
        t = np.arange(len(idx))
        base = 100 + 0.0004 * t
        saw = 1.0 * np.sin(t / 60 * 2 * np.pi / 6)        # golf met periode 6 uur: zwaaipunten
        p = base + saw
        cut = 2400
        p[cut:cut + 120] = p[cut - 1] - np.linspace(0, 2.5, 120)           # breuk
        p[cut + 120:cut + 240] = p[cut + 119] + np.linspace(0, 2.2, 120)    # terugkeer
        p[cut + 240:] = p[cut + 239] - np.linspace(0, 6, len(p) - cut - 240)  # val
    df = pd.DataFrame({"timestamp": idx, "open": p, "high": p * 1.0003, "low": p * 0.9997, "close": p, "volume": 1.0})
    return df


class BreakRetestTest(unittest.TestCase):
    def test_simulate_stop_first_and_break_even(self):
        h = np.array([100.0, 100.5, 100.0]); l = np.array([99.9, 99.9, 99.0]); c = np.array([100.0, 100.2, 99.5])
        # long entry 100 stop 99, ladder 0.5R en 3R: eerste doel raakt (high 100.5), stop naar 100, dan terug naar BE
        gross, net, out = br.simulate("long", 100.0, 99.0, (0.5, 3.0), (0.5, 0.5), True, h, l, c, 0.0)
        self.assertEqual(out, "be")
        self.assertAlmostEqual(gross, 0.25)
        gross, _, out = br.simulate("long", 100.0, 99.0, (2.0,), (1.0,), False, np.array([102.0]), np.array([98.0]), np.array([100.0]), 0.0)
        self.assertEqual(out, "stop")                       # stop en doel in dezelfde candle: stop eerst
        self.assertAlmostEqual(gross, -1.0)

    def test_cost_is_charged_in_r(self):
        _, net, _ = br.simulate("short", 100.0, 101.0, (1.0,), (1.0,), False, np.array([100.0]), np.array([98.0]), np.array([99.0]), 0.1)
        self.assertAlmostEqual(net, 1.0 - 0.1)

    def test_finds_break_and_retest_on_planted_channel(self):
        f = frame(plant=True)
        ev = br.find_breaks(make_bars(f, 30))
        self.assertFalse(ev.empty)
        self.assertIn("short", set(ev["direction"]))

    def test_no_lookahead_in_breaks(self):
        f = frame(plant=True)
        full = br.find_breaks(make_bars(f, 30))
        cut = 3000
        part = br.find_breaks(make_bars(f.iloc[:cut], 30))
        last = len(make_bars(f.iloc[:cut], 30)) - 1
        a = full[full["bar"] <= last].drop(columns=["touches"]).reset_index(drop=True)
        b = part.drop(columns=["touches"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)

    def test_run_gives_rows_with_sane_columns(self):
        t = br.run(frame(plant=True))
        self.assertFalse(t.empty)
        self.assertTrue({"mode", "ladder", "r_net", "risk_pct"} <= set(t.columns))
        self.assertTrue((t["risk_pct"] >= br.MIN_STOP_PCT).all())
        self.assertIn("RETEST", set(t["mode"]))     # eerder ontbrak elke retest door een omgekeerd teken bij de reclaim-controle

    def test_random_walk_does_not_pass(self):
        trades, plac = [], []
        for seed in range(4):
            f = frame(minutes=60 * 24 * 40, seed=seed)
            t = br.run(f)
            if not t.empty:
                trades.append(t); plac.append(br.placebo(f, t, 0.06))
        if not trades:
            return
        trades, plac = pd.concat(trades, ignore_index=True), pd.concat(plac, ignore_index=True)
        rows = br.summarize(trades, plac, trades["at"].quantile(0.7))
        self.assertFalse([r for r in rows if r.kind == "ALLES" and br.passes(r)])


if __name__ == "__main__":
    unittest.main()
