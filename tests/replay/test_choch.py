"""Hogere bodem met breuk van de laatste top (CHOCH): de derde soort breuk van Structuur, naast LINE en RANGE (app/replay/breakretest.py)."""
import unittest

import numpy as np
import pandas as pd

from app.replay import breakretest as br

# Dalende aanloop tot L1 (bar 100), top H (bar 110), hogere bodem L2 (bar 120), daarna stijgend door H.
LONG_KNOTS = [(0, 133.0), (100, 100.0), (110, 106.0), (120, 103.0), (149, 117.0)]


def bars_from(knots, n=150, half=0.1):
    """30m-candles met open = slot = de lijn door de knooppunten en een lont van `half` aan elke kant: zwaaipunten liggen precies op de knopen."""
    xs, ys = zip(*knots)
    mid = np.interp(np.arange(n), xs, ys)
    ts = pd.date_range("2026-03-02", periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": mid, "high": mid + half, "low": mid - half, "close": mid, "volume": 1.0,
                         "close_time": ts + pd.Timedelta(minutes=30)})


def mirror(knots):
    return [(x, 220.0 - y) for x, y in knots]


class FindChochTest(unittest.TestCase):
    def test_long_higher_low_and_break_of_the_last_top(self):
        b = bars_from(LONG_KNOTS)
        ev = br.find_choch(b)
        self.assertEqual(len(ev), 1)
        e = ev.iloc[0]
        self.assertEqual((e["kind"], e["direction"], e["p1"], e["p2"]), ("CHOCH", "long", 100, 120))
        self.assertAlmostEqual(e["a"], b.at[110, "high"])
        self.assertEqual(e["slope"], 0.0)
        self.assertGreaterEqual(e["bar"], 120 + br.PIVOT_K)                     # pas na de bevestiging van L2
        self.assertGreater(b.at[e["bar"], "close"], e["a"])
        self.assertLessEqual(b.at[e["bar"] - 1, "close"], e["a"] + br.BREAK_ATR * e["atr"])     # het eerste slot erboven
        self.assertEqual(list(ev.columns), list(br.find_breaks(b).columns))

    def test_short_is_the_mirror(self):
        b = bars_from(mirror(LONG_KNOTS))
        ev = br.find_choch(b)
        self.assertEqual(len(ev), 1)
        e = ev.iloc[0]
        self.assertEqual((e["kind"], e["direction"], e["p1"], e["p2"]), ("CHOCH", "short", 100, 120))
        self.assertAlmostEqual(e["a"], b.at[110, "low"])
        self.assertLess(b.at[e["bar"], "close"], e["a"])

    def test_no_falling_context_no_setup(self):
        # L1 is niet de laagste low van de 40 candles ervoor: dit is een dip in een stijging, geen bodem na een daling.
        b = bars_from([(0, 80.0), (90, 104.0), (100, 100.0), (110, 106.0), (120, 103.0), (149, 117.0)])
        self.assertTrue(br.find_choch(b).empty)

    def test_too_small_higher_low_no_setup(self):
        b = bars_from([(0, 133.0), (100, 100.0), (110, 106.0), (120, 100.05), (149, 117.0)])
        p_high, p_low = br._pivots(b)
        self.assertTrue(p_low[100] and p_low[120])
        self.assertTrue(br.find_choch(b).empty)

    def test_no_swing_high_between_the_lows_no_setup(self):
        b = bars_from([(0, 133.0), (99, 101.5), (100, 100.0), (102, 100.8), (110, 100.4), (149, 115.0)])
        p_high, p_low = br._pivots(b)
        self.assertTrue(p_low[100] and p_low[110])
        self.assertFalse(p_high[101:110].any())
        self.assertTrue(br.find_choch(b).empty)

    def test_close_above_the_top_before_the_low_is_confirmed_is_no_setup(self):
        # Slot boven H op bar 121, terwijl L2 (bar 120) pas na bar 123 bekend is: wie dat volgt kocht te laat in, en later is het geen eerste slot meer.
        b = bars_from([(0, 133.0), (100, 100.0), (110, 106.0), (120, 103.0), (121, 107.5), (149, 115.0)])
        self.assertTrue(br._pivots(b)[1][120])
        self.assertTrue(br.find_choch(b).empty)

    def test_no_lookahead(self):
        b = bars_from(LONG_KNOTS)
        full = br.find_choch(b)
        bar = int(full.iloc[0]["bar"])
        self.assertTrue(br.find_choch(b.iloc[:bar].reset_index(drop=True)).empty)
        part = br.find_choch(b.iloc[:bar + 1].reset_index(drop=True))
        pd.testing.assert_frame_equal(part.drop(columns=["touches"]), full.drop(columns=["touches"]))


class StructureBreaksTest(unittest.TestCase):
    def ev(self, **kw):
        row = {"bar": 127, "direction": "long", "kind": "CHOCH", "p1": 100, "p2": 120, "a": 106.0, "slope": 0.0, "atr": 0.5,
               "vol_ratio": 1.0, "span": 20, "touches": 1, "with_trend": False}
        return {**row, **kw}

    def test_a_line_break_on_the_same_candle_and_level_wins(self):
        breaks = pd.DataFrame([self.ev(kind="LINE", p1=90, p2=115, a=110.0, slope=-(110.0 - 106.1) / 37)])      # op bar 127: 106,1
        choch = pd.DataFrame([self.ev()])
        self.assertTrue(br.drop_duplicate_choch(breaks, choch).empty)

    def test_other_level_direction_or_candle_is_kept(self):
        choch = pd.DataFrame([self.ev()])
        for other in (self.ev(kind="RANGE", a=107.0), self.ev(kind="RANGE", direction="short"), self.ev(kind="RANGE", bar=126)):
            self.assertEqual(len(br.drop_duplicate_choch(pd.DataFrame([other]), choch)), 1, other)

    def test_structure_breaks_add_choch_and_keep_find_breaks_unchanged(self):
        b = bars_from(LONG_KNOTS)
        plain = br.find_breaks(b)
        both = br.find_structure_breaks(b)
        self.assertEqual(list(both.columns), list(plain.columns))
        self.assertEqual(len(both), len(plain) + 1)
        self.assertIn("CHOCH", set(both["kind"]))
        pd.testing.assert_frame_equal(both[both["kind"] != "CHOCH"].reset_index(drop=True), plain.reset_index(drop=True), check_dtype=False)


if __name__ == "__main__":
    unittest.main()
