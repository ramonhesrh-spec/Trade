import unittest

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs
from app.replay import trendlab as tl
from app.replay.lab import add_indicators
from tests.replay.rangesweep_fixtures import FIRST_PEAK_HOUR, SWEEP_HOUR, frames


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
