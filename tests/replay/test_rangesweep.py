import json
import os
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs
from app.replay import trendlab as tl
from app.replay.lab import add_indicators
from tests.replay.rangesweep_fixtures import (FIRST_LONG_ZONE_SETUP_HOUR, FIRST_PEAK_HOUR, FIRST_SHORT_ZONE_SETUP_HOUR, SWEEP_HOUR,
                                              frames)


class ResampleTest(unittest.TestCase):
    def test_frames_have_every_timeframe_and_full_buckets_only(self):
        b15, b1h, b4h = frames()
        f = rs.build_frames(b15, b1h, b4h)
        self.assertEqual(set(f), {"15m", "30m", "1h", "2h", "4h"})
        self.assertEqual(len(f["30m"]), len(b15) // 2)
        self.assertEqual(len(f["2h"]), len(b1h) // 2)
        self.assertEqual(f["2h"]["timestamp"].iloc[0].hour % 2, 0)
        self.assertAlmostEqual(f["2h"]["high"].iloc[0], max(b1h["high"].iloc[0], b1h["high"].iloc[1]))

    def test_incomplete_last_bucket_is_dropped(self):
        b15, b1h, _ = frames()
        self.assertEqual(len(rs.resample(b1h.iloc[:-1], "2h")), (len(b1h) - 1) // 2)


class RangeTest(unittest.TestCase):
    def setUp(self):
        self.b15, self.b1h, self.b4h = frames()
        self.b, self.ranges = rs.range_series(self.b1h, "1h")

    def test_range_known_just_before_the_sweep(self):
        r = self.ranges[SWEEP_HOUR - 1]
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.high, 106.025, places=6)
        self.assertAlmostEqual(r.low, 99.975, places=6)
        self.assertEqual((r.high_touches, r.low_touches), (6, 6))
        self.assertAlmostEqual(r.high_spread, 0.0, places=9)
        self.assertEqual(r.first_at, self.b["timestamp"].iloc[FIRST_PEAK_HOUR])
        self.assertEqual(r.known_at, self.b["timestamp"].iloc[SWEEP_HOUR])

    def test_no_range_in_the_flat_start(self):
        hi, lo = self.b["high"].to_numpy(float), self.b["low"].to_numpy(float)
        r, why = rs.range_at(self.b, 30, "1h", tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N))
        self.assertIsNone(r)
        self.assertIn("te weinig aanrakingen", why)

    def test_width_bounds(self):
        hi, lo = self.b["high"].to_numpy(float), self.b["low"].to_numpy(float)
        ph, pl = tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N)
        b = self.b.copy()
        b["atr"] = 3.0
        self.assertEqual(rs.range_at(b, SWEEP_HOUR - 1, "1h", ph, pl), (None, "range te smal"))
        b["atr"] = 0.3
        self.assertEqual(rs.range_at(b, SWEEP_HOUR - 1, "1h", ph, pl), (None, "range te breed"))

    def test_active_for_uses_only_known_ranges(self):
        active = rs.active_for(self.b, self.b, self.ranges, "1h")
        self.assertIs(active[SWEEP_HOUR], self.ranges[SWEEP_HOUR - 1])
        self.assertIsNone(active[0])

    def test_active_for_4h_waits_for_the_close(self):
        b4, r4 = rs.range_series(self.b4h, "4h")
        for j, r in enumerate(rs.active_for(self.b, b4, r4, "4h")):
            if r is not None:
                self.assertLessEqual(r.known_at, self.b["timestamp"].iloc[j])


class ZoneTest(unittest.TestCase):
    def setUp(self):
        _, b1h, _ = frames()
        self.b = add_indicators(b1h).reset_index(drop=True)
        self.zones = rs.find_zones(self.b)

    def test_supply_zone_on_the_first_peak(self):
        bear = [z for z in self.zones if z.kind == "bear"]
        z = bear[0]
        self.assertEqual(z.ob_idx, FIRST_PEAK_HOUR)
        self.assertAlmostEqual(z.low, 105.375)
        self.assertAlmostEqual(z.high, 106.025)
        self.assertAlmostEqual(z.outer, 106.025)
        self.assertAlmostEqual(z.inner("short"), 105.375)
        self.assertLessEqual(z.disp_bars, rs.DISP_BARS)

    def test_overlapping_later_peaks_do_not_make_new_zones(self):
        bear = [z for z in self.zones if z.kind == "bear" and z.ob_idx < SWEEP_HOUR]
        self.assertEqual(len(bear), 1)

    def test_demand_zone_on_the_first_trough(self):
        bull = [z for z in self.zones if z.kind == "bull"]
        self.assertEqual(bull[0].ob_idx, 44)
        self.assertAlmostEqual(bull[0].low, 99.975)
        self.assertAlmostEqual(bull[0].high, 100.625)

    def test_zone_is_active_until_a_close_beyond_the_outer_edge(self):
        z = rs.Zone("bear", 100.0, 101.0, 0, 2, 5, 2, 1.5)
        self.assertTrue(rs.zone_active(z, 4))
        self.assertFalse(rs.zone_active(z, 5))
        self.assertFalse(rs.zone_active(z, 2))
        self.assertFalse(rs.zone_active(rs.Zone("bear", 100.0, 101.0, 0, 2, None, 2, 1.5), 2 + rs.ZONE_MAX_AGE + 1))

    def test_retests_count_entries_into_the_zone(self):
        bear = [z for z in self.zones if z.kind == "bear"][0]
        self.assertEqual(rs.retests_before(bear, self.b, 72), 0)
        self.assertEqual(rs.retests_before(bear, self.b, 90), 1)
        self.assertEqual(rs.retests_before(bear, self.b, 95), 2)


class LookaheadTest(unittest.TestCase):
    """Wat op candle i besloten is mag niet veranderen als de candles na i wijzigen."""

    def test_ranges_do_not_change_when_future_candles_change(self):
        _, b1h, _ = frames()
        cut = SWEEP_HOUR - 1
        _, full = rs.range_series(b1h, "1h")
        mutated = b1h.copy()
        mutated.loc[cut + 1:, ["open", "high", "low", "close"]] = 500.0
        _, other = rs.range_series(mutated, "1h")
        self.assertEqual(full[:cut + 1], other[:cut + 1])
        self.assertIsNotNone(full[cut])

    def test_zone_knowledge_ignores_the_future(self):
        _, b1h, _ = frames()
        b = add_indicators(b1h).reset_index(drop=True)
        cut = 100
        early = [z for z in rs.find_zones(b.iloc[:cut + 1].reset_index(drop=True)) if z.known_idx <= cut]
        full = [z for z in rs.find_zones(b) if z.known_idx <= cut]
        strip = lambda zs: [(z.kind, z.low, z.high, z.ob_idx, z.known_idx, z.disp_bars) for z in zs]
        self.assertEqual(strip(early), strip(full))
        for z in full:
            if z.broken_idx is not None and z.broken_idx > cut:
                self.assertTrue(rs.zone_active(z, cut) or cut <= z.known_idx)


class EdgeCaseTest(unittest.TestCase):
    def test_short_and_empty_frames(self):
        _, b1h, _ = frames()
        for n in (0, 1, 5, 20):
            b, ranges = rs.range_series(b1h.iloc[:n], "1h")
            self.assertEqual(len(ranges), n)
            self.assertTrue(all(r is None for r in ranges))
            self.assertEqual(rs.find_zones(b) if n else [], [])

    def test_nan_atr_gives_no_range_and_no_zone(self):
        _, b1h, _ = frames()
        b = add_indicators(b1h).reset_index(drop=True)
        b["atr"] = np.nan
        hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
        r, _ = rs.range_at(b, SWEEP_HOUR - 1, "1h", tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N))
        self.assertIsNone(r)
        self.assertEqual(rs.find_zones(b), [])

    def test_resample_of_tiny_frames_is_empty(self):
        b15, _, _ = frames()
        self.assertEqual(len(rs.resample(b15.iloc[:0], "30m")), 0)
        self.assertEqual(len(rs.resample(b15.iloc[:1], "30m")), 0)

    def test_resample_30m_matches_manual_aggregation(self):
        b15, _, _ = frames()
        r = rs.resample(b15, "30m")
        self.assertAlmostEqual(r["low"].iloc[3], min(b15["low"].iloc[6], b15["low"].iloc[7]))
        self.assertAlmostEqual(r["close"].iloc[3], b15["close"].iloc[7])
        self.assertAlmostEqual(r["volume"].iloc[3], 2.0)

    def test_inner_edge_of_demand_zone_is_its_top(self):
        z = rs.Zone("bull", 99.0, 100.0, 0, 2, None, 2, 1.5)
        self.assertEqual((z.inner("long"), z.outer), (100.0, 99.0))


class PreregTest(unittest.TestCase):
    def test_constants_equal_the_preregistration(self):
        import re
        from pathlib import Path
        text = (Path(__file__).resolve().parents[2] / "docs/onderzoek/range-sweep/preregistratie.md").read_text()
        block = re.search(r"```prereg-constants\n(.*?)```", text, re.S).group(1)
        checked = 0
        for line in block.splitlines():
            m = re.match(r"rangesweep\.(\w+) = (.+)", line)
            if m and hasattr(rs, m.group(1)):
                self.assertEqual(getattr(rs, m.group(1)), float(m.group(2).replace(",", ".")), m.group(1))
                checked += 1
        self.assertGreaterEqual(checked, 10)


GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "range_sweep_setup.json"


class SweepSetupTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f, self.b1h = rs.build_frames(b15, b1h, b4h), b1h

    def setups(self, entry="ob", confirm="slot"):
        return rs.find_setups(self.f, "1h", "sweep", entry, confirm, use_htf=False)

    def test_one_short_setup_at_the_sweep(self):
        setups, _ = self.setups()
        self.assertEqual(len(setups), 1)
        s = setups[0]
        self.assertEqual((s["direction"], s["family"]), ("short", "sweep"))
        self.assertAlmostEqual(s["extreme"], 106.5)
        self.assertEqual(s["sweep_at"], self.b1h["timestamp"].iloc[SWEEP_HOUR])
        self.assertEqual(s["placed_at"], self.b1h["timestamp"].iloc[SWEEP_HOUR] + pd.Timedelta(hours=1))
        self.assertEqual(s["place_idx15"], 4 * (SWEEP_HOUR + 1))
        self.assertAlmostEqual(s["ref_price"], 105.6)

    def test_order_block_is_the_last_green_15m_candle_at_the_top(self):
        s = self.setups()[0][0]
        self.assertAlmostEqual(s["zone_low"], 105.875)
        self.assertAlmostEqual(s["zone_high"], 106.5)
        self.assertEqual(s["legs"], [(1.0, (105.875 + 106.5) / 2)])

    def test_features(self):
        f = self.setups()[0][0]["features"]
        self.assertEqual((f["touches_high"], f["touches_low"]), (6, 6))
        self.assertEqual(f["age_bars"], SWEEP_HOUR - FIRST_PEAK_HOUR)
        self.assertTrue(f["ob_opposite"])
        self.assertTrue(f["zone_fresh"])
        self.assertLess(f["displacement_atr"], 1.5)
        self.assertLessEqual(f["zone_atr"], 1.5)

    def test_choch_is_missing_here_and_says_why(self):
        setups, refused = self.setups(confirm="choch15")
        self.assertEqual(setups, [])
        self.assertIn("geen CHoCH op 15m binnen 6 uur", [r["reason"] for r in refused])

    def test_breakout_is_not_a_sweep(self):
        b15, _, b4h = frames()
        b15 = b15.copy()
        b15.loc[4 * SWEEP_HOUR + 1, "high"] = 108.0
        b1h = rs.resample(b15, "1h")
        setups, refused = rs.find_setups(rs.build_frames(b15, b1h, b4h), "1h", "sweep", "ob", "slot", use_htf=False)
        self.assertEqual(setups, [])
        self.assertIn("prik te diep, dit is een uitbraak", [r["reason"] for r in refused])

    def test_stops(self):
        s = self.setups()[0][0]
        raw = rs.raw_stops(s)
        self.assertEqual(set(raw), {"zone_0", "zone_025", "zone_05", "wick_025"})
        self.assertAlmostEqual(raw["zone_0"], 106.5)
        self.assertAlmostEqual(raw["wick_025"], 106.5 + 0.25 * s["atr_t"])
        self.assertGreaterEqual(rs.final_stop(s, "zone_025"), raw["zone_025"])

    def test_golden(self):
        s = self.setups()[0][0]
        got = json.loads(json.dumps({k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in s.items()}, default=float))
        if os.environ.get("REGEN_GOLDEN"):
            GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True))
        if not GOLDEN.exists():
            self.fail(f"maak {GOLDEN} met REGEN_GOLDEN=1 en controleer hem met de hand tegen de definities")
        want = json.loads(GOLDEN.read_text())
        self.assertEqual(set(got), set(want))
        for k in want:
            if isinstance(want[k], float):
                self.assertAlmostEqual(got[k], want[k], places=6, msg=k)
            else:
                self.assertEqual(got[k], want[k], msg=k)


class ZoneSetupTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f, self.b1h = rs.build_frames(b15, b1h, b4h), b1h
        self.setups, self.refused = rs.find_setups(self.f, "1h", "zone", "zone", "slot", use_htf=False)

    def test_first_short_is_the_first_approach_with_a_known_range(self):
        short = [s for s in self.setups if s["direction"] == "short"][0]
        self.assertEqual(short["placed_at"], self.b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1))
        self.assertEqual(short["legs"], [(1.0, 105.375)])
        self.assertAlmostEqual(short["zone_high"], 106.025)
        self.assertIsNone(short["extreme"])

    def test_first_long_mirrors(self):
        long_ = [s for s in self.setups if s["direction"] == "long"][0]
        self.assertEqual(long_["placed_at"], self.b1h["timestamp"].iloc[FIRST_LONG_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1))
        self.assertEqual(long_["legs"], [(1.0, 100.625)])

    def test_earlier_approaches_were_refused_for_lack_of_a_range(self):
        self.assertTrue(any(r["reason"].startswith("geen range op 1h") for r in self.refused))

    def test_one_setup_per_zone(self):
        keys = [(s["direction"], s["zone_low"], s["zone_high"]) for s in self.setups]
        self.assertEqual(len(keys), len(set(keys)))

    def test_zone_stops_have_no_wick(self):
        s = self.setups[0]
        self.assertEqual(set(rs.raw_stops(s)), {"zone_0", "zone_025", "zone_05"})

    def test_htf_ok(self):
        r = rs.Range("1h", pd.Timestamp("2025-01-01", tz="UTC"), 110.0, 100.0, 3, 3, 0.0, 0.0, pd.Timestamp("2025-01-01", tz="UTC"), 1.0)
        self.assertTrue(rs.htf_ok("short", -1, 200.0, 0.0, r))
        self.assertFalse(rs.htf_ok("short", 1, 300.0, 0.0, r))
        self.assertTrue(rs.htf_ok("short", 1, 120.0, 80.0, r))
        self.assertTrue(rs.htf_ok("long", 1, 120.0, 80.0, r))
        self.assertFalse(rs.htf_ok("long", 0, float("nan"), float("nan"), r))

    def test_diagnose(self):
        at = self.b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)
        self.assertTrue(rs.diagnose(self.f, at, "short", "1h", "zone", "zone", "slot", False)["seen"])
        early = self.b1h["timestamp"].iloc[30]
        d = rs.diagnose(self.f, early, "short", "1h", "zone", "zone", "slot", False)
        self.assertFalse(d["seen"])
        self.assertIn("geen range op 1h", d["reason"])


def _noisy_bars(n: int, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 0.3, n)) + 3 * np.sin(np.arange(n) / 40)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"timestamp": pd.date_range("2022-01-01", periods=n, freq="30min", tz="UTC"), "open": o,
                         "high": np.maximum(o, c) + abs(rng.normal(0, 0.15, n)), "low": np.minimum(o, c) - abs(rng.normal(0, 0.15, n)),
                         "close": c, "volume": 1.0})


def _simple_best_cluster(values, tol):
    best = np.array([], dtype=int)
    for a in range(len(values)):
        group = np.flatnonzero(np.abs(values - values[a]) <= tol)
        if len(group) > len(best) or (len(group) == len(best) and len(group) and group[-1] > best[-1]):
            best = group
    return best


class SpeedTest(unittest.TestCase):
    def test_best_cluster_equals_the_simple_version(self):
        rng = np.random.default_rng(7)
        for _ in range(300):
            values = np.round(rng.uniform(0, 5, rng.integers(0, 14)), 1)
            np.testing.assert_array_equal(rs._best_cluster(values, 0.5), _simple_best_cluster(values, 0.5))

    def test_range_series_equals_range_at_per_candle(self):
        b, ranges = rs.range_series(_noisy_bars(1500), "30m")
        hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
        ph, pl = tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N)
        self.assertGreater(sum(r is not None for r in ranges), 0)
        self.assertEqual(ranges, [rs.range_at(b, i, "30m", ph, pl)[0] for i in range(len(b))])

    def test_twenty_thousand_candles_in_a_few_seconds(self):
        import time
        bars = _noisy_bars(20000)
        t0 = time.perf_counter()
        rs.range_series(bars, "30m")
        self.assertLess(time.perf_counter() - t0, 5.0)


class SetupLookaheadTest(unittest.TestCase):
    """Een setup is bekend op placed_at: veranderen of weglaten van candles vanaf placed_at mag hem niet veranderen."""

    def setUp(self):
        self.b15, self.b1h, self.b4h = frames()

    def run_setups(self, b15, family, entry, confirm):
        b1h = rs.resample(b15, "1h")
        b4h = rs.resample(b15, "4h")
        return rs.find_setups(rs.build_frames(b15, b1h, b4h), "1h", family, entry, confirm, use_htf=False)[0]

    def check(self, family, entry, confirm):
        base = self.run_setups(self.b15, family, entry, confirm)
        self.assertGreater(len(base), 0)
        for s in base:
            cut = int(self.b15["timestamp"].searchsorted(s["placed_at"]))
            changed = self.b15.copy()
            changed.loc[cut:, ["open", "high", "low", "close"]] = changed.loc[cut:, ["open", "high", "low", "close"]].to_numpy()[::-1] * 1.3
            again = self.run_setups(changed, family, entry, confirm)
            same = [t for t in again if t["placed_at"] == s["placed_at"] and t["direction"] == s["direction"] and t["zone_low"] == s["zone_low"]]
            self.assertEqual(len(same), 1, (family, entry, confirm, s["placed_at"]))
            self.assertEqual({k: v for k, v in same[0].items() if k != "features"}, {k: v for k, v in s.items() if k != "features"})

    def test_zone_slot(self):
        self.check("zone", "zone", "slot")

    def test_sweep_slot(self):
        self.check("sweep", "ob", "slot")

    def test_zone_split(self):
        self.check("zone", "split", "slot")

    def test_diagnose_sweep_sees_the_short_and_explains_the_long(self):
        f = rs.build_frames(self.b15, self.b1h, self.b4h)
        at = self.b1h["timestamp"].iloc[SWEEP_HOUR] + pd.Timedelta(hours=1)
        self.assertTrue(rs.diagnose(f, at, "short", "1h", "sweep", "ob", "slot", False)["seen"])
        d = rs.diagnose(f, at, "long", "1h", "sweep", "ob", "slot", False)
        self.assertFalse(d["seen"])
        self.assertIn("geen prik voorbij de rand", d["reason"])
        d = rs.diagnose(f, at, "short", "1h", "sweep", "ob", "choch15", False)
        self.assertEqual(d["reason"], "geen CHoCH op 15m binnen 6 uur")


class StopSideTest(unittest.TestCase):
    def setup_for(self, direction):
        if direction == "short":
            return {"direction": "short", "zone_low": 105.0, "zone_high": 106.0, "extreme": 106.5, "atr_t": 0.4, "legs": [(1.0, 105.5)]}
        return {"direction": "long", "zone_low": 100.0, "zone_high": 101.0, "extreme": 99.5, "atr_t": 0.4, "legs": [(1.0, 100.5)]}

    def test_stop_is_beyond_the_outer_edge_for_both_sides_in_atr_units(self):
        short, long_ = self.setup_for("short"), self.setup_for("long")
        self.assertAlmostEqual(rs.raw_stops(short)["zone_05"], 106.0 + 0.5 * 0.4)
        self.assertAlmostEqual(rs.raw_stops(long_)["zone_05"], 100.0 - 0.5 * 0.4)
        self.assertAlmostEqual(rs.raw_stops(short)["wick_025"], 106.5 + 0.1)
        self.assertAlmostEqual(rs.raw_stops(long_)["wick_025"], 99.5 - 0.1)

    def test_floor_widens_a_tight_stop_and_never_refuses(self):
        s = self.setup_for("short")
        s["atr_t"], s["zone_high"] = 0.001, 105.6
        planned = 105.5
        self.assertAlmostEqual(rs.final_stop(s, "zone_0"), planned * 1.004)
        s = self.setup_for("long")
        s["atr_t"], s["zone_low"] = 0.001, 100.4
        self.assertAlmostEqual(rs.final_stop(s, "zone_0"), 100.5 * 0.996)

    def test_floor_leaves_a_wide_stop_alone(self):
        s = self.setup_for("short")
        self.assertAlmostEqual(rs.final_stop(s, "zone_05"), 106.2)

    def test_floor_uses_the_weighted_entry_of_a_split(self):
        s = self.setup_for("short")
        s["atr_t"], s["zone_high"] = 0.001, 105.6
        s["legs"] = [(0.4, 105.0), (0.6, 105.5)]
        self.assertAlmostEqual(rs.final_stop(s, "zone_0"), 105.3 * 1.004)


def _bars15(rows):
    b = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    b.insert(0, "timestamp", pd.date_range("2025-01-01", periods=len(rows), freq="15min", tz="UTC"))
    return b


class ChochAndLimitTest(unittest.TestCase):
    # Short: een zwaaidal op 10 (laag 99), daarna een prik naar 106 op 14, en een slot onder 99 op m.
    def short_bars(self, close_below_at=22, new_high_at=None):
        rows = []
        for q in range(30):
            c = 100.0
            lo, hi = 99.5, 100.5
            if q == 10:
                lo = 99.0
            if q == 14:
                hi = 106.0
            if q == close_below_at:
                c, lo = 98.5, 98.4
            if q == new_high_at:
                hi = 107.0
            rows.append((100.0, hi, lo, c))
        return _bars15(rows)

    def test_choch_short_is_the_first_close_below_the_last_swing_low(self):
        b = self.short_bars()
        self.assertEqual(rs.choch_index(b, 14, 16, "short", 106.0), 22)

    def test_a_new_extreme_first_cancels_the_choch(self):
        b = self.short_bars(new_high_at=18)
        self.assertIsNone(rs.choch_index(b, 14, 16, "short", 106.0))

    def test_no_choch_without_a_known_swing(self):
        b = self.short_bars()
        self.assertIsNone(rs.choch_index(b, 14, 11, "short", 106.0))

    def test_choch_long_mirrors(self):
        rows = [(100.0, 100.5, 99.5, 100.0) for _ in range(30)]
        rows[10] = (100.0, 101.0, 99.5, 100.0)
        rows[14] = (100.0, 100.5, 94.0, 100.0)
        rows[22] = (100.0, 101.6, 99.5, 101.5)
        self.assertEqual(rs.choch_index(_bars15(rows), 14, 16, "long", 94.0), 22)

    def test_order_block_is_the_last_opposite_candle_and_falls_back_to_the_extreme(self):
        rows = [(100.0, 101.0, 99.0, 100.5), (100.5, 102.0, 100.0, 101.0), (101.0, 106.0, 100.5, 100.8)]
        self.assertEqual(rs.order_block(_bars15(rows), 2, "short")[:3], (100.0, 102.0, 1))
        red = [(101.0, 102.0, 100.0, 100.5)] * 3
        self.assertEqual(rs.order_block(_bars15(red), 2, "short"), (100.0, 102.0, 2, False))

    def test_limit_on_the_wrong_side_of_the_price_is_dropped(self):
        r = rs.Range("1h", pd.Timestamp("2025-01-01", tz="UTC"), 110.0, 100.0, 3, 3, 0.0, 0.0, pd.Timestamp("2025-01-01", tz="UTC"), 1.0)
        self.assertEqual(rs.legs_for("zone", "short", r, 108.0, 107.0), [(1.0, 108.0)])
        self.assertEqual(rs.legs_for("zone", "short", r, 108.0, 108.0), [])
        self.assertEqual(rs.legs_for("zone", "long", r, 102.0, 102.0), [])
        self.assertEqual(rs.legs_for("split", "short", r, 108.0, 109.0), [(0.4, 110.0)])
        self.assertEqual(rs.legs_for("split", "long", r, 102.0, 101.0), [(0.4, 100.0)])


def _random_market(n: int = 9000, seed: int = 1):
    """Een terugkerende markt (naar een langzaam verschuivend gemiddelde) die genoeg ranges en zones geeft voor eigenschapstoetsen."""
    rng = np.random.default_rng(seed)
    x, lvl, mu = np.zeros(n), 100.0, 100.0
    for t in range(1, n):
        if t % 1500 == 0:
            mu *= np.exp(rng.normal(0, 0.08))
        lvl = lvl + 0.02 * (mu - lvl) + rng.normal(0, 0.35) * lvl / 100
        x[t] = lvl
    x[0] = 100
    op = np.r_[x[0], x[:-1]]
    hi = np.maximum(op, x) + np.abs(rng.normal(0, 0.15, n))
    lo = np.minimum(op, x) - np.abs(rng.normal(0, 0.15, n))
    b15 = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"), "open": op, "high": hi, "low": lo,
                        "close": x, "volume": 1.0})
    return b15, rs.resample(b15, "1h"), rs.resample(b15, "4h")


class SplitStopSideTest(unittest.TestCase):
    def test_every_leg_is_on_the_profit_side_of_every_final_stop(self):
        checked = 0
        for seed in (1, 2, 3):
            f = rs.build_frames(*_random_market(seed=seed))
            for tf in ("1h", "2h"):
                setups, _ = rs.find_setups(f, tf, "zone", "split", "slot", use_htf=False)
                for s in setups:
                    for name in rs.raw_stops(s):
                        stop = rs.final_stop(s, name)
                        for _, p in s["legs"]:
                            # zone_0 heeft geen buffer: een randbeen op de zonerand zelf is daar gelijk aan de stop, en dat is alleen ter vergelijking.
                            strict = name != "zone_0"
                            ok = (p < stop if strict else p <= stop) if s["direction"] == "short" else (p > stop if strict else p >= stop)
                            self.assertTrue(ok, (s["direction"], s["legs"], name, stop))
                            checked += 1
        self.assertGreater(checked, 50)

    def test_edge_leg_beyond_the_zone_pulls_the_stop_outwards(self):
        s = {"direction": "long", "zone_low": 98.0, "zone_high": 98.6, "extreme": None, "atr_t": 0.1, "range_high": 106.0, "range_low": 97.7,
             "legs": [(0.4, 97.739), (0.6, 98.523)]}
        self.assertLess(rs.final_stop(s, "zone_025"), 97.739)
        s = {"direction": "short", "zone_low": 105.0, "zone_high": 105.6, "extreme": None, "atr_t": 0.1, "range_high": 106.3, "range_low": 99.0,
             "legs": [(0.4, 106.3), (0.6, 105.2)]}
        self.assertGreater(rs.final_stop(s, "zone_025"), 106.3)


class ChochApproachTest(unittest.TestCase):
    """Zone-retest met choch15: de eerste nadering waarop alle voorwaarden kloppen telt, ook als een eerdere geen CHoCH had."""

    def setUp(self):
        self.f = rs.build_frames(*frames())

    def run_with(self, fake):
        with mock.patch.object(rs, "choch_index", fake):
            return rs.find_setups(self.f, "1h", "zone", "zone", "choch15", use_htf=False)

    def test_a_missing_choch_does_not_kill_the_zone(self):
        starts = []

        def fake(b15, k, start, direction, extreme):
            starts.append((start, direction))
            if len([x for x in starts if x[1] == direction]) == 1:
                return None
            # een 15m-slot voorbij de limiet (105,375 short, 100,625 long), zoals een echte CHoCH die zou geven
            cl = b15["close"].to_numpy(float)
            return next(m for m in range(start, len(cl)) if (cl[m] < 105.3 if direction == "short" else cl[m] > 100.7))

        setups, refused = self.run_with(fake)
        first = {}
        for st, d in starts:
            first.setdefault(d, st)
        self.assertGreater(len(starts), 2)
        for d in ("short", "long"):
            mine = [s for s in setups if s["direction"] == d]
            self.assertTrue(mine, d)
            self.assertGreater(mine[0]["place_idx15"], first[d] + 1, "de setup komt bij de tweede nadering, niet de eerste")
        self.assertEqual(sum(r["reason"] == "geen CHoCH op 15m binnen 6 uur" for r in refused), 2)

    def test_an_approach_inside_the_same_visit_never_counts_twice(self):
        starts = []

        def fake(b15, k, start, direction, extreme):
            starts.append((start, direction))
            return None

        self.run_with(fake)
        self.assertGreater(len(starts), 2)
        b = add_indicators(frames()[1]).reset_index(drop=True)
        zones = rs.find_zones(b)
        for start, d in starts:
            i = start // 4 - 1
            inner = [z.inner(d) for z in zones if z.kind == ("bear" if d == "short" else "bull") and rs.zone_active(z, i)]
            touched = lambda j: any((b["high"].iloc[j] >= x) if d == "short" else (b["low"].iloc[j] <= x) for x in inner)
            self.assertTrue(touched(i))
            self.assertFalse(touched(i - 1), "dezelfde nadering telde twee keer")


class DiagnoseReasonTest(unittest.TestCase):
    """Elke weigering schrijft haar eigen reden, zodat de misser-controle niet 'geen prik voorbij de rand' meldt terwijl er wel een prik was."""

    def second_prick(self, hour=SWEEP_HOUR + 2):
        b15, _, b4h = frames()
        b15 = b15.copy()
        b15.loc[4 * hour + 1, "high"] = 106.4
        b1h = rs.resample(b15, "1h")
        return rs.build_frames(b15, b1h, rs.resample(b15, "4h")), b1h["timestamp"].iloc[hour]

    def why(self, f, at, family="sweep", entry="ob"):
        d = rs.diagnose(f, at, "short", "1h", family, entry, "slot", False, window=pd.Timedelta(minutes=30))
        self.assertFalse(d["seen"])
        return d["reason"]

    def test_prick_inside_the_cooldown(self):
        f, at = self.second_prick()
        self.assertEqual(self.why(f, at), "cooldown na eerdere prik")

    def test_second_prick_on_the_same_range_side(self):
        f, at = self.second_prick(SWEEP_HOUR + 1)
        with mock.patch.object(rs, "SWEEP_COOLDOWN", 1):
            _, refused = rs.find_setups(f, "1h", "sweep", "ob", "slot", use_htf=False)
        self.assertIn((at, "al een sweep op deze rand"), [(r["at"], r["reason"]) for r in refused])

    def test_later_approach_of_a_zone_that_already_had_a_setup(self):
        b15, b1h, b4h = frames()
        f = rs.build_frames(b15, b1h, b4h)
        setups, refused = rs.find_setups(f, "1h", "zone", "zone", "slot", use_htf=False)
        short = [s for s in setups if s["direction"] == "short"][0]
        later = [r for r in refused if r["direction"] == "short" and r["reason"].startswith("zone had al een setup op ")]
        self.assertTrue(later)
        self.assertEqual(later[0]["reason"], f"zone had al een setup op {short['placed_at']:%Y-%m-%d %H:%M}")
        self.assertGreater(later[0]["at"], short["placed_at"])
        self.assertEqual(self.why(f, later[0]["at"], "zone", "zone"), later[0]["reason"])

    def test_no_refusal_inside_the_visit_that_made_the_setup(self):
        f = rs.build_frames(*frames())
        setups, refused = rs.find_setups(f, "1h", "zone", "zone", "slot", use_htf=False)
        short = [s for s in setups if s["direction"] == "short"][0]
        first = min(r["at"] for r in refused if r["reason"].startswith("zone had al een setup op "))
        self.assertGreater(first - short["placed_at"], pd.Timedelta(hours=5))


class DiagnosePriceTest(unittest.TestCase):
    """De trader noemt ook zijn instapprijs: een setup of weigering van een ander niveau binnen 12 uur telt dan niet."""

    def setUp(self):
        b15, self.b1h, b4h = frames()
        self.f = rs.build_frames(b15, self.b1h, b4h)
        self.at = self.b1h["timestamp"].iloc[SWEEP_HOUR] + pd.Timedelta(hours=1)

    def diag(self, price, confirm="slot"):
        return rs.diagnose(self.f, self.at, "short", "1h", "sweep", "ob", confirm, False, price=price)

    def test_setup_near_the_price_is_seen(self):
        self.assertTrue(self.diag(106.2)["seen"])
        self.assertTrue(self.diag(None)["seen"])

    def test_setup_far_from_the_price_is_not_this_trade(self):
        d = self.diag(112.0)
        self.assertFalse(d["seen"])
        self.assertNotEqual(d["reason"], "")

    def test_refusal_far_from_the_price_is_not_reported(self):
        near = self.diag(106.2, confirm="choch15")
        self.assertEqual(near["reason"], "geen CHoCH op 15m binnen 6 uur")
        far = self.diag(112.0, confirm="choch15")
        self.assertNotEqual(far["reason"], "geen CHoCH op 15m binnen 6 uur")
