import unittest
from unittest import mock

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs
from app.replay import zonesweep as zs

START = pd.Timestamp("2025-03-03 00:00", tz="UTC")
FLAT = (100.0, 100.5, 99.5, 100.0)
# Rode candle k (vraagzone 99,7 tot 100,3), daarna een stijging van meer dan 1 ATR: de zone is bekend op de candle erna.
ZONE = [(100.2, 100.3, 99.7, 99.8), (99.8, 102.0, 99.8, 101.8)]
DRIFT = [(101.8, 102.0, 101.5, 101.6), (101.6, 101.7, 101.2, 101.3), (101.3, 101.4, 100.9, 101.0), (101.0, 101.1, 100.6, 100.8)]
# Hamer: laag 0,5 onder de zone, slot boven de zone.
PRIK_HERSTEL = (100.8, 100.9, 99.2, 100.6)
UP = [(100.6, 101.5, 100.5, 101.4), (101.4, 102.0, 101.3, 101.9), (101.9, 102.1, 101.5, 101.7), (101.7, 101.8, 101.0, 101.2),
      (101.2, 101.3, 100.7, 100.9)]


def mirror(rows, pivot=200.0):
    return [(pivot - o, pivot - lo, pivot - hi, pivot - c) for o, hi, lo, c in rows]


def make_frames(rows):
    b1h = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    b1h.insert(0, "timestamp", pd.date_range(START, periods=len(b1h), freq="1h"))
    b1h["volume"] = 1.0
    b15 = b1h.loc[b1h.index.repeat(4)].reset_index(drop=True)
    b15["timestamp"] = pd.date_range(START, periods=len(b15), freq="15min")
    return rs.build_frames(b15, b1h, rs.resample(b1h, "4h"))


def base(after, n_flat=30):
    return [FLAT] * n_flat + ZONE + DRIFT + after


def find(rows, entry="zone", use_htf=False, tf="1h"):
    return zs.find_setups(make_frames(rows), tf, entry, use_htf)


def htf(trend, hh=102.0, ll=90.0):
    def fake(b, b4h):
        n = len(b)
        return np.full(n, trend), np.full(n, hh), np.full(n, ll)
    return mock.patch.object(rs, "htf_context", fake)


class SetupTest(unittest.TestCase):
    def test_long_prik_and_herstel_gives_one_setup(self):
        setups, refused = find(base([PRIK_HERSTEL] + UP))
        self.assertEqual(len(setups), 1, refused)
        s = setups[0]
        self.assertEqual((s["direction"], s["family"], s["tf"]), ("long", "zonesweep", "1h"))
        self.assertAlmostEqual(s["zone_low"], 99.7)
        self.assertAlmostEqual(s["zone_high"], 100.3)
        self.assertEqual(s["legs"], [(1.0, 100.3)])
        self.assertAlmostEqual(s["extreme"], 99.2)
        self.assertAlmostEqual(s["ref_price"], 100.6)
        self.assertAlmostEqual(s["range_low"], 99.2)
        self.assertAlmostEqual(s["range_high"], 102.0)
        t = START + pd.Timedelta(hours=30 + len(ZONE) + len(DRIFT))
        self.assertEqual(s["sweep_at"], t)
        self.assertEqual(s["return_at"], t + pd.Timedelta(hours=1))
        self.assertEqual(s["placed_at"], s["return_at"])
        self.assertAlmostEqual(zs.raw_stops(s)["wick_025"], 99.2 - 0.25 * s["atr_t"])
        self.assertAlmostEqual(zs.final_stop(s, "wick_05"), 99.2 - 0.5 * s["atr_t"])
        self.assertEqual(s["features"]["herstel_bars"], 1)
        self.assertAlmostEqual(s["features"]["prik_atr"], 0.5 / s["atr_t"], delta=0.2)

    def test_midden_entry_uses_the_middle_of_the_zone(self):
        setups, _ = find(base([PRIK_HERSTEL] + UP), entry="midden")
        self.assertAlmostEqual(setups[0]["legs"][0][1], 100.0)

    def test_breakout_deeper_than_2_5_atr_is_refused(self):
        deep = (100.8, 100.9, 96.0, 100.6)
        setups, refused = find(base([deep] + UP))
        self.assertEqual(setups, [])
        self.assertTrue(any(r["reason"].startswith("uitbraak") for r in refused), refused)

    def test_no_recovery_within_six_candles_is_refused(self):
        down = [(100.8, 100.9, 99.2, 99.4)] + [(99.4, 99.5, 99.0, 99.2)] * 6
        setups, refused = find(base(down + UP))
        self.assertEqual(setups, [])
        self.assertTrue(any(r["reason"] == "geen herstel binnen 6 candles" for r in refused), refused)

    def test_cooldown_after_a_breakout_hides_the_next_prik(self):
        rows = base([(100.8, 100.9, 96.0, 100.6)] + UP + [PRIK_HERSTEL] + UP)
        setups, refused = find(rows)
        self.assertEqual(setups, [])
        with mock.patch.object(zs, "COOLDOWN_BARS", 0):
            self.assertEqual(len(find(rows)[0]), 1)

    def test_short_is_the_mirror(self):
        setups, refused = find(mirror(base([PRIK_HERSTEL] + UP)))
        self.assertEqual(len(setups), 1, refused)
        s = setups[0]
        self.assertEqual(s["direction"], "short")
        self.assertAlmostEqual(s["extreme"], 200 - 99.2)
        self.assertAlmostEqual(s["legs"][0][1], 200 - 100.3)
        self.assertAlmostEqual(s["range_high"], 200 - 99.2)
        self.assertAlmostEqual(s["range_low"], 200 - 102.0)
        self.assertAlmostEqual(zs.raw_stops(s)["wick_025"], 200 - 99.2 + 0.25 * s["atr_t"])

    def test_second_prik_of_the_same_zone_is_refused(self):
        setups, refused = find(base([PRIK_HERSTEL] + UP + [PRIK_HERSTEL] + UP))
        self.assertEqual(len(setups), 1)
        self.assertTrue(any(r["reason"] == "zone had al een setup" for r in refused), refused)

    def test_limit_on_the_wrong_side_becomes_a_market_entry(self):
        low_close = (100.8, 100.9, 99.2, 100.1)
        setups, _ = find(base([low_close] + UP))
        self.assertEqual(len(setups), 1)
        self.assertAlmostEqual(setups[0]["legs"][0][1], 100.1)

    def test_htf_filter_refuses_a_prik_against_the_trend(self):
        rows = base([PRIK_HERSTEL] + UP)
        with htf(-1):
            setups, refused = find(rows, use_htf=True)
            self.assertEqual(setups, [])
            self.assertTrue(any(r["reason"].startswith("HTF-filter") for r in refused), refused)
            free, _ = find(rows, use_htf=False)
        self.assertEqual(len(free), 1)
        self.assertFalse(free[0]["htf_ok"])
        self.assertEqual(free[0]["htf_trend"], -1)
        self.assertFalse(free[0]["features"]["with_trend"])
        with htf(1):
            with_trend, _ = find(rows, use_htf=True)
        self.assertEqual(len(with_trend), 1)
        self.assertTrue(with_trend[0]["features"]["with_trend"])

    def test_htf_ok_zone_rule(self):
        self.assertTrue(zs.htf_ok_zone("long", 1, 102, 90, 100))
        self.assertFalse(zs.htf_ok_zone("long", -1, 102, 90, 100))
        self.assertTrue(zs.htf_ok_zone("long", -1, 102, 90, 93))
        self.assertTrue(zs.htf_ok_zone("short", -1, 102, 90, 93))
        self.assertFalse(zs.htf_ok_zone("short", 1, 102, 90, 93))
        self.assertTrue(zs.htf_ok_zone("short", 1, 102, 90, 100))
        self.assertTrue(zs.htf_ok_zone("long", 1, float("nan"), float("nan"), 100))
        self.assertFalse(zs.htf_ok_zone("long", 0, float("nan"), float("nan"), 100))

    def test_2h_zones_use_1h_triggers(self):
        setups, _ = find(base([PRIK_HERSTEL] + UP), tf="2h")
        for s in setups:
            self.assertEqual(s["tf"], "2h")


class StopTest(unittest.TestCase):
    def test_final_stop_keeps_the_minimum_distance(self):
        s = {"direction": "long", "extreme": 100.0, "atr_t": 0.1, "legs": [(1.0, 100.3)]}
        self.assertAlmostEqual(zs.final_stop(s, "wick_025"), 100.3 * (1 - rs.MIN_STOP_PCT / 100))
        short = {**s, "direction": "short", "extreme": 100.5, "legs": [(1.0, 100.3)]}
        self.assertAlmostEqual(zs.final_stop(short, "wick_025"), 100.3 * (1 + rs.MIN_STOP_PCT / 100))

    def test_wide_stop_is_untouched(self):
        s = {"direction": "long", "extreme": 98.0, "atr_t": 1.0, "legs": [(1.0, 100.3)]}
        self.assertAlmostEqual(zs.final_stop(s, "wick_05"), 97.5)

    def test_tested_stops(self):
        self.assertEqual(zs.TESTED_STOPS, ("wick_025", "wick_05"))


class ContractTest(unittest.TestCase):
    def test_setup_has_every_key_the_lab_and_stopquality_read(self):
        # rangesweep_lab.run_coin: placed_at, direction, zone_low, zone_high, sweep_at, return_at, features, range_high, range_low, legs, place_idx15;
        # raw_stops/final_stop: extreme, atr_t, legs; stopquality.measure krijgt range_high en range_low; rs._setup levert daarnaast de rest.
        read = {"placed_at", "direction", "zone_low", "zone_high", "sweep_at", "return_at", "features", "range_high", "range_low", "legs",
                "place_idx15", "extreme", "atr_t", "range_first_at", "family", "tf", "zone_at", "ref_price", "htf_trend", "htf_pos", "htf_ok"}
        setups, _ = find(base([PRIK_HERSTEL] + UP))
        self.assertTrue(read <= set(setups[0]), read - set(setups[0]))
        self.assertTrue(read <= set(rs._setup("long", "sweep", "1h", rs.Range("1h", START, 1, 0, 3, 3, 0, 0, START, 1), 0, 0, START, START, 0,
                                              START, START, 0, 1.0, [], 1.0, 0, 1.0, 0.0, True, {})))


class DiagnoseTest(unittest.TestCase):
    def test_seen_and_reasons(self):
        f = make_frames(base([PRIK_HERSTEL] + UP))
        at = START + pd.Timedelta(hours=30 + len(ZONE) + len(DRIFT) + 1)
        d = zs.diagnose(f, at, "long", "1h", "zone", False)
        self.assertTrue(d["seen"])
        self.assertFalse(zs.diagnose(f, at, "long", "1h", "zone", False, price=120.0)["seen"])
        self.assertEqual(zs.diagnose(f, at, "short", "1h", "zone", False)["reason"], "geen actieve aanbodzone op 1h")
        quiet = zs.diagnose(make_frames(base(UP)), at, "long", "1h", "zone", False)
        self.assertEqual(quiet["reason"], "wel een zone, maar geen prik eronder")

    def test_refusal_reason_is_reported(self):
        f = make_frames(base(UP))
        at = START + pd.Timedelta(hours=30 + len(ZONE) + len(DRIFT) + 1)
        self.assertTrue(zs.diagnose(f, at, "long", "1h", "zone", False)["reason"].startswith("wel een zone"))
