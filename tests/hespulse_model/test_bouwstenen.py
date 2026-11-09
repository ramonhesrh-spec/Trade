"""Alleen-lezen inventaris van de bouwstenen voor het HesPulse-model (docs/onderzoek/hespulse-model/preregistratie.md, paragraaf
Bouwstenen). Elke test legt een eigenschap vast die de preregistratie gebruikt: geen toekomstige candles (prefix-toets: de uitkomst op de
eerste `cut` candles is gelijk aan die op de hele reeks, beperkt tot wat vóór `cut` bekend was) en of één gebeurtenis meer dan eens als nieuw
kan tellen. Faalt een test na een wijziging van een bouwsteen, dan klopt het oordeel in de preregistratie niet meer: lees dat eerst na.
Synthetische candles, niets wordt gewijzigd."""
import unittest

import numpy as np
import pandas as pd

from app import indicators as ind
from app import poc
from app.replay import breakretest as br
from app.replay import rangesweep as rs
from app.replay import trendlab as tl
from app.replay import zonesweep as zs
from app.replay.lab import add_indicators

CUTS = (300, 450, 600, 777)
SEEDS = (1, 2, 3, 4, 5)


def walk(n: int = 900, seed: int = 3) -> pd.DataFrame:
    """30m-candles met trendstukken en ruis: genoeg breuken, zones en zwaaipunten voor de prefix-toetsen. Deterministisch."""
    rng = np.random.default_rng(seed)
    drift = np.zeros(n)
    i = 0
    while i < n:
        length = int(rng.integers(20, 80))
        drift[i:i + length] = rng.choice([-1, 1]) * rng.uniform(0.001, 0.004)
        i += length
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.006, n)))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    ts = pd.date_range("2026-01-01", periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high, "low": low, "close": close, "volume": rng.lognormal(5, 0.3, n)})


def ohlc(high, low=None, open_=None, close=None) -> pd.DataFrame:
    high = np.asarray(high, float)
    low = high - 0.1 if low is None else np.asarray(low, float)
    open_ = (high + low) / 2 if open_ is None else np.asarray(open_, float)
    close = (high + low) / 2 if close is None else np.asarray(close, float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


KEYS = ["bar", "direction", "kind", "p1", "p2"]


class PivotTest(unittest.TestCase):
    def test_breakretest_pivot_known_only_after_k_candles(self):
        b = walk(seed=1)
        full_hi, full_lo = br._pivots(b)
        for cut in CUTS:
            hi, lo = br._pivots(b.iloc[:cut])
            known = cut - br.PIVOT_K
            np.testing.assert_array_equal(hi[:known], full_hi[:known])
            np.testing.assert_array_equal(lo[:known], full_lo[:known])
            self.assertFalse(hi[known:].any() or lo[known:].any(), "een punt in de laatste K candles is nog niet bevestigd")

    def test_trendlab_pivot_known_only_after_n_candles(self):
        b = walk(seed=4)
        for n in (2, 3):
            full = tl._pivot_flags(b["low"].to_numpy(float), n)
            for cut in CUTS:
                part = tl._pivot_flags(b["low"].to_numpy(float)[:cut], n)
                np.testing.assert_array_equal(part[:cut - n], full[:cut - n])
                self.assertFalse(part[cut - n:].any())

    def test_three_tie_rules_for_equal_highs(self):
        """Twee gelijke toppen naast elkaar: breakretest telt ze allebei (dubbel), indicators geen van beide, trendlab de eerste."""
        h = [1, 2, 3, 5, 5, 3, 2, 1, 0.5]
        df = ohlc(h)
        self.assertEqual(list(np.flatnonzero(br._pivots(df)[0])), [3, 4])
        self.assertEqual([p.index for p in ind._find_pivots(df) if p.kind == "high"], [])
        self.assertEqual(list(np.flatnonzero(tl._pivot_flags(-np.asarray(h, float), 3))), [3])

    def test_indicators_pivot_needs_k_candles_on_the_right(self):
        df = ohlc([1, 2, 3, 6, 3, 2])
        self.assertEqual([p for p in ind._find_pivots(df) if p.kind == "high"], [])
        df = ohlc([1, 2, 3, 6, 3, 2, 1])
        self.assertEqual([p.index for p in ind._find_pivots(df) if p.kind == "high"], [3])


class BreakTest(unittest.TestCase):
    def test_find_breaks_and_choch_use_no_future_candles(self):
        for seed in SEEDS:
            b = walk(seed=seed)
            for fn in (br.find_breaks, br.find_choch):
                full = fn(b)
                self.assertGreater(len(full), 0)
                for cut in CUTS:
                    part = fn(b.iloc[:cut]).reset_index(drop=True)
                    want = full[full["bar"] < cut].reset_index(drop=True)
                    pd.testing.assert_frame_equal(part[KEYS], want[KEYS], check_dtype=False)
                    np.testing.assert_allclose(part["a"].to_numpy(float), want["a"].to_numpy(float))

    def test_one_break_per_swing_pair(self):
        for seed in SEEDS:
            b = walk(seed=seed)
            for fn in (br.find_breaks, br.find_choch):
                ev = fn(b)
                self.assertFalse(ev.duplicated(["direction", "p1", "p2"]).any())

    def test_a_new_swing_pair_can_restate_almost_the_same_break(self):
        """Per paar zwaaipunten één breuk, maar een nieuw paar kan binnen 8 candles op bijna hetzelfde niveau (0,5 ATR) opnieuw breken:
        één beweging telt dan als twee gebeurtenissen. Het model moet daarom per richting en niveau ontdubbelen."""
        near = 0
        for seed in range(1, 11):
            ev = br.find_structure_breaks(walk(seed=seed))
            for d in ("long", "short"):
                e = ev[ev["direction"] == d].sort_values("bar")
                bars, atr = e["bar"].to_numpy(), e["atr"].to_numpy()
                lv = (e["a"] + e["slope"] * (e["bar"] - e["p1"])).to_numpy()
                near += int(((np.diff(bars) <= 8) & (np.abs(np.diff(lv)) <= 0.5 * atr[1:])).sum())
        self.assertGreater(near, 0)

    def test_known_levels_use_no_future_and_ignore_whether_taken(self):
        b = add_indicators(walk(seed=2)).reset_index(drop=True)
        full_hi, full_lo = br._pivots(b)
        for bar in (200, 350, 500):
            part = b.iloc[:bar + 1]
            hi, lo = br._pivots(part)
            for d in ("long", br.SHORT):
                self.assertEqual(br.known_levels(b, full_hi, full_lo, d, bar), br.known_levels(part, hi, lo, d, bar))
        # Top op 5 bij candle 3, later gaat de koers tot 9: de top is opgehaald maar staat nog in de lijst.
        h = [1, 2, 3, 5, 3, 2, 1, 4, 9, 4, 3, 2]
        df = ohlc(h)
        p_hi, p_lo = br._pivots(df)
        self.assertIn(5.0, br.known_levels(df, p_hi, p_lo, "long", 11))


class ZoneTest(unittest.TestCase):
    def test_find_zones_use_no_future_candles(self):
        for seed in SEEDS:
            b = walk(seed=seed)
            full = rs.find_zones(add_indicators(b).reset_index(drop=True))
            self.assertGreater(len(full), 0)
            for cut in (300, 600):
                part = rs.find_zones(add_indicators(b.iloc[:cut]).reset_index(drop=True))
                want = [z for z in full if z.known_idx < cut]
                self.assertEqual(len(part), len(want))
                for a, z in zip(part, want):
                    self.assertEqual((a.kind, a.low, a.high, a.ob_idx, a.known_idx), (z.kind, z.low, z.high, z.ob_idx, z.known_idx))
                    # broken_idx kijkt vooruit; correct zolang de gebruiker hem alleen met zijn eigen index vergelijkt (zone_active).
                    self.assertEqual(a.broken_idx, z.broken_idx if z.broken_idx is not None and z.broken_idx < cut else None)

    def test_one_zone_per_order_block_candle(self):
        for seed in SEEDS:
            zones = rs.find_zones(add_indicators(walk(seed=seed)).reset_index(drop=True))
            self.assertEqual(len(zones), len({(z.kind, z.ob_idx) for z in zones}))

    def test_zone_active_only_after_its_known_candle(self):
        z = rs.Zone("bull", 100.0, 100.8, 4, 5, 9, 1, 1.0)
        self.assertEqual([i for i in range(12) if rs.zone_active(z, i)], [6, 7, 8])


def _sweep_case(n: int = 60):
    lo, hi, cl, atr = np.full(n, 100.5), np.full(n, 101.5), np.full(n, 101.0), np.ones(n)
    lo[10], cl[10] = 99.6, 99.8        # prik onder de vraagzone, slot eronder
    lo[11], cl[11] = 99.9, 100.4       # herstel: slot boven de onderkant
    lo[30], cl[30] = 99.5, 100.3       # tweede prik met herstel
    return rs.Zone("bull", 100.0, 100.8, 0, 0, None, 1, 1.0), (hi, lo, cl, atr), np.arange(n)


class SweepTest(unittest.TestCase):
    def test_one_setup_per_zone_second_sweep_refused(self):
        z, cols, pos = _sweep_case()
        self.assertEqual(zs._scan_zone(z, cols, pos, 1), [("setup", 10, 11, 99.6), ("refused", 30, "zone had al een setup", None)])

    def test_refusal_at_the_end_of_the_data_is_provisional(self):
        """Op de candles tot en met de prik is er nog geen herstel: de functie weigert, één candle later is het een setup. Een setup is
        definitief vanaf zijn herstelcandle; een weigering pas HERSTEL_BARS candles na de prik."""
        z, cols, pos = _sweep_case()
        cut = 11
        self.assertEqual(zs._scan_zone(z, tuple(a[:cut] for a in cols), pos[:cut], 1), [("refused", 10, "geen herstel binnen 6 candles", None)])


class ArrayTest(unittest.TestCase):
    def test_fvg_is_the_three_candle_gap_and_stays_after_being_filled(self):
        o = [10, 10.0, 10.5, 11.2, 11.0, 10.2]
        c = [10, 10.1, 11.3, 11.1, 10.3, 10.0]
        h = [10.1, 10.2, 11.4, 11.3, 11.1, 10.3]
        lo = [9.9, 9.95, 10.4, 10.9, 10.2, 9.8]     # candle 5 loopt helemaal door het gat 10,2 - 10,9
        gaps = ind.find_fair_value_gaps(ohlc(h, lo, o, c), "long")
        self.assertIn(ind.FVG(low=10.2, high=10.9), gaps)
        self.assertFalse(hasattr(gaps[0], "index"), "geen candle-index: wanneer het gat ontstond is niet terug te lezen")

    def test_two_displacement_candles_give_the_same_order_block_twice(self):
        o = np.array([10.0] * 12 + [10.0, 10.2, 11.8])
        c = np.array([10.05] * 12 + [9.8, 11.8, 13.4])
        blocks = ind.find_order_blocks(ohlc(np.maximum(o, c) + 0.02, np.minimum(o, c) - 0.02, o, c), "long")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0], blocks[1])



def five_minutes(days: int = 10, seed: int = 6) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = days * 288
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    open_ = np.r_[100.0, close[:-1]]
    ts = pd.date_range("2026-03-02", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_, close) * 1.0005,
                         "low": np.minimum(open_, close) * 0.9995, "close": close, "volume": rng.lognormal(5, 0.3, n)})


class PocTest(unittest.TestCase):
    def test_poc_levels_only_from_closed_periods_and_touch_without_future(self):
        """Een POC bestaat pas na het einde van zijn periode; 'naakt' op moment t hangt alleen af van candles vóór t."""
        c = five_minutes()
        later = pd.Timestamp("2026-03-12", tz="UTC")
        full = {lv.key: lv for lv in poc.new_levels(c, later, set())}
        for now in (pd.Timestamp("2026-03-06 13:00", tz="UTC"), pd.Timestamp("2026-03-09 07:00", tz="UTC")):
            part = poc.new_levels(c, now, set())
            self.assertGreater(len(part), 0)
            for lv in part:
                self.assertLessEqual(lv.end, now)
                self.assertAlmostEqual(lv.price, full[lv.key].price)
                ref = full[lv.key].touched_at
                self.assertEqual(lv.touched_at, ref if ref is not None and ref + poc.BAR <= now else None)


if __name__ == "__main__":
    unittest.main()
