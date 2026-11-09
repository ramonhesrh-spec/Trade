"""Tests van app/market_state.py op met de hand gebouwde candles."""
import unittest

import pandas as pd

from app import market_state as ms


def frame(rows, start="2026-01-01"):
    ts = pd.date_range(start, periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame([
        {"timestamp": t, "open": r[0], "high": r[1], "low": r[2], "close": r[3], "volume": r[4]}
        for t, r in zip(ts, rows)
    ])


def profile(vols):
    """Candle i beslaat exact prijs i..i+1, dus bij bins=len(vols) valt het volume in precies een emmer."""
    return frame([(i + 0.5, i + 1, i, i + 0.5, v) for i, v in enumerate(vols)])


def ranging(n=68, last_closes=(100, 100, 100, 100)):
    rows = [(100, 101, 99, 100, 10)] * n
    rows += [(100, 101, 99, c, 10) for c in last_closes]
    return frame(rows)


class ValueAreaTests(unittest.TestCase):
    def test_nearly_all_volume_in_one_bucket(self):
        rows = [(5.5, 5.5, 5.5, 5.5, 10)] * 9 + [(5, 10, 0, 5, 10)]
        va = ms.value_area(frame(rows), bins=10)
        self.assertAlmostEqual(va["poc"], 5.5)
        self.assertAlmostEqual(va["val"], 5.0)
        self.assertAlmostEqual(va["vah"], 6.0)
        self.assertAlmostEqual(va["total_volume"], 100)

    def test_adds_bigger_neighbour_until_68_percent(self):
        va = ms.value_area(profile([1, 1, 1, 1, 1, 40, 30, 1, 1, 1]), bins=10)
        self.assertAlmostEqual(va["poc"], 5.5)
        self.assertAlmostEqual(va["val"], 5.0)
        self.assertAlmostEqual(va["vah"], 7.0)

    def test_tie_goes_to_bucket_above(self):
        va = ms.value_area(profile([1, 1, 1, 1, 20, 40, 20, 1, 1, 1]), bins=10)
        self.assertAlmostEqual(va["val"], 5.0)
        self.assertAlmostEqual(va["vah"], 7.0)

    def test_extends_downwards_when_lower_is_bigger(self):
        va = ms.value_area(profile([1, 1, 1, 1, 30, 40, 5, 1, 1, 1]), bins=10)
        self.assertAlmostEqual(va["val"], 4.0)
        self.assertAlmostEqual(va["vah"], 6.0)

    def test_stops_as_soon_as_68_percent_reached(self):
        # 40/82 is onder 68%, 40+30=70 van 82 is 85%: twee emmers, niet meer
        va = ms.value_area(profile([1, 1, 1, 1, 1, 40, 30, 1, 1, 5]), bins=10)
        self.assertAlmostEqual(va["vah"] - va["val"], 2.0)

    def test_volume_split_proportionally_over_overlap(self):
        # candle 0..2 met volume 16 geeft 8 aan emmer 0 en 8 aan emmer 1; emmer 9 krijgt 9
        rows = [(1, 2, 0, 1, 16)] + [(9.5, 10, 9, 9.5, 1)] * 9
        va = ms.value_area(frame(rows), bins=10)
        self.assertAlmostEqual(va["total_volume"], 25)
        self.assertAlmostEqual(va["poc"], 9.5)
        self.assertAlmostEqual(va["val"], 1.0)

    def test_fewer_than_ten_candles_is_none(self):
        self.assertIsNone(ms.value_area(profile([1] * 9), bins=9))

    def test_zero_volume_is_none(self):
        self.assertIsNone(ms.value_area(profile([0] * 10), bins=10))

    def test_flat_price_is_none(self):
        self.assertIsNone(ms.value_area(frame([(5, 5, 5, 5, 10)] * 12)))

    def test_zero_range_candle_at_top_edge_lands_in_last_bucket(self):
        rows = [(0, 10, 0, 5, 1)] + [(0, 1, 0, 0.5, 1)] * 8 + [(10, 10, 10, 10, 100)]
        va = ms.value_area(frame(rows), bins=10)
        self.assertAlmostEqual(va["poc"], 9.5)
        self.assertAlmostEqual(va["vah"], 10.0)


class ClassifyTests(unittest.TestCase):
    def test_balans(self):
        r = ms.classify(ranging(), "long")
        self.assertEqual(r["state"], "balans")
        self.assertIsNone(r["relatie"])

    def test_onbalans_op_three_of_four(self):
        r = ms.classify(ranging(last_closes=(100, 110, 110, 110)), "long")
        self.assertEqual(r["state"], "onbalans_op")
        self.assertEqual(r["relatie"], "met")

    def test_two_of_four_is_balans(self):
        self.assertEqual(ms.classify(ranging(last_closes=(100, 100, 110, 110)), "long")["state"], "balans")

    def test_onbalans_neer_mirrored(self):
        r = ms.classify(ranging(last_closes=(90, 90, 100, 90)), "short")
        self.assertEqual(r["state"], "onbalans_neer")
        self.assertEqual(r["relatie"], "met")

    def test_relatie_tegen(self):
        self.assertEqual(ms.classify(ranging(last_closes=(110,) * 4), "short")["relatie"], "tegen")
        self.assertEqual(ms.classify(ranging(last_closes=(90,) * 4), "long")["relatie"], "tegen")

    def test_positie(self):
        base = ms.classify(ranging(), "long")
        val, vah = base["val"], base["vah"]
        span = vah - val

        def pos(close):
            return ms.classify(ranging(last_closes=(100, 100, 100, close)), "long")["positie"]

        self.assertEqual(pos(vah - 0.05 * span), "premium")
        self.assertEqual(pos(val + 0.05 * span), "discount")
        self.assertEqual(pos(val + 0.5 * span), "midden")
        self.assertEqual(pos(vah + 0.001), "buiten")
        self.assertEqual(pos(val - 0.001), "buiten")

    def test_uses_only_last_72(self):
        old = frame([(500, 501, 499, 500, 1000)] * 30)
        recent = frame([(100, 101, 99, 100, 10)] * 72, start="2026-02-01")
        r = ms.classify(pd.concat([old, recent], ignore_index=True), "long")
        self.assertLess(r["vah"], 102)

    def test_too_little_data_is_none(self):
        self.assertIsNone(ms.classify(ranging(n=3, last_closes=(100,) * 4), "long"))


class ClosedBeforeTests(unittest.TestCase):
    def test_excludes_candle_still_forming(self):
        c = frame([(1, 2, 0, 1, 1)] * 5, start="2026-01-01 00:00")
        out = ms.closed_before(c, pd.Timestamp("2026-01-01 03:30", tz="UTC"))
        self.assertEqual(list(out["timestamp"]), list(c["timestamp"][:3]))

    def test_candle_closing_exactly_at_signal_is_included(self):
        c = frame([(1, 2, 0, 1, 1)] * 5, start="2026-01-01 00:00")
        self.assertEqual(len(ms.closed_before(c, pd.Timestamp("2026-01-01 03:00", tz="UTC"))), 3)

    def test_parse_time(self):
        self.assertEqual(ms.parse_time("2026-01-01T03:00:00"), pd.Timestamp("2026-01-01 03:00", tz="UTC"))
        self.assertEqual(ms.parse_time("2026-01-01T05:00:00+02:00"), pd.Timestamp("2026-01-01 03:00", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
