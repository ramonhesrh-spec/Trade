import unittest

import numpy as np
import pandas as pd

from app.replay import liquidity_levels as ll
from app.replay.lab import add_indicators, make_bars


def frame(days=12, seed=1, plant=False):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-02", periods=days * 1440, freq="1min", tz="UTC")     # begint op een maandag
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.0004, len(idx))))
    df = pd.DataFrame({"timestamp": idx, "open": p, "high": p * 1.0004, "low": p * 0.9996, "close": p, "volume": 1.0})
    if plant:     # elke dag om 09:00: prik 0,4% onder de laagte van gisteren, sluit terug erboven, daarna +1,5%
        for d in range(1, days):
            day = idx[0].normalize() + pd.Timedelta(days=d)
            prev = df[(df["timestamp"] >= day - pd.Timedelta(days=1)) & (df["timestamp"] < day)]
            pdl = prev["low"].min()
            i = df.index[df["timestamp"] == day + pd.Timedelta(hours=9)][0]
            df.loc[i:i + 4, ["open", "high", "low", "close"]] = pdl * 0.9990
            df.loc[i + 4, ["low"]] = pdl * 0.9955
            df.loc[i + 4, ["close"]] = pdl * 1.0008
            ramp = pdl * 1.0008 * (1 + np.linspace(0.0003, 0.02, 120))
            df.loc[i + 5:i + 124, "close"] = ramp
            df.loc[i + 5:i + 124, "open"] = ramp
            df.loc[i + 5:i + 124, "high"] = ramp * 1.0002
            df.loc[i + 5:i + 124, "low"] = ramp * 0.9998
    return df


class LevelsTest(unittest.TestCase):
    def test_previous_day_and_asia_levels_come_from_closed_data_only(self):
        f = frame()
        bars = add_indicators(make_bars(f, 5))
        lv = ll.day_levels(bars)
        day1 = pd.Timestamp("2026-03-03", tz="UTC")
        prev = f[(f["timestamp"] >= "2026-03-02") & (f["timestamp"] < "2026-03-03")]
        self.assertAlmostEqual(lv.at[day1, "PDH"], prev["high"].max())
        self.assertAlmostEqual(lv.at[day1, "PDL"], prev["low"].min())
        asia = f[(f["timestamp"] >= day1) & (f["timestamp"] < day1 + pd.Timedelta(hours=7))]
        self.assertAlmostEqual(lv.at[day1, "ASIA_L"], asia["low"].min())
        self.assertTrue(pd.isna(lv.loc[pd.Timestamp("2026-03-02", tz="UTC")].get("PDH")))      # eerste dag heeft geen gisteren

    def test_sweep_needs_wick_through_and_close_back_and_is_found_once_per_day(self):
        f = frame(plant=True)
        sw = ll.find_sweeps(add_indicators(make_bars(f, 5)))
        pdl = sw[sw["kind"] == "PDL"]
        self.assertGreaterEqual(len(pdl), 8)
        self.assertEqual(set(pdl["direction"]), {"long"})
        self.assertEqual(pdl["at"].dt.floor("D").duplicated().sum(), 0)
        self.assertTrue((pdl["extreme"] < pdl["level"]).all() and (pdl["close"] > pdl["level"]).all())

    def test_min_stop_filter(self):
        self.assertIsNone(ll.plan_trade("long", 100.0, 99.95, 0.01))
        entry, stop = ll.plan_trade("long", 100.0, 99.0, 0.2)
        self.assertEqual((entry, round(stop, 2)), (100.0, 98.9))


class ScanTest(unittest.TestCase):
    def rows(self, plant):
        f = frame(days=30, plant=plant)
        t = ll.run(f, 0.02, 0.01)
        cut = t["at"].quantile(0.7)
        return ll.summarize(t, ll.placebo(f, t, 0.02, 0.01), cut, 5), t

    def test_planted_reversal_is_found_and_costs_are_subtracted(self):
        rows, t = self.rows(True)
        r = next(x for x in rows if x.kind == "PDL" and x.rr == 2.0)
        self.assertGreater(r.net, 0.3)
        self.assertLess(r.net, r.gross)

    def test_random_walk_gives_no_edge_in_total(self):
        f = frame(days=60, seed=3)
        t = ll.run(f, 0.02, 0.01)
        rows = ll.summarize(t, ll.placebo(f, t, 0.02, 0.01), t["at"].quantile(0.7), 10)
        alles = [r for r in rows if r.kind == "ALLES"]
        self.assertTrue(all(r.net < 0.15 for r in alles))        # kosten maken een eerlijke random walk negatief tot nul
        self.assertFalse(any(ll.passes(r, 10) for r in alles))


if __name__ == "__main__":
    unittest.main()
