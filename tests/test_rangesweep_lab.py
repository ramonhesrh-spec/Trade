import re
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs, rangesweep_lab as rl, stopquality as sq
from tests.replay.rangesweep_fixtures import frames

ROOT = Path(__file__).resolve().parent.parent
PREREG = ROOT / "docs" / "onderzoek" / "range-sweep" / "preregistratie.md"
_TF = {"30m": "30m", "1u": "1h", "2u": "2h", "4u": "4h"}
_FAMILY = {"zone-retest": "zone", "sweep": "sweep"}
_ENTRY = {"binnenkant zone": "zone", "40% rand, 60% zone": "split", "midden order block": "ob"}


def prereg_variants():
    """De varianttabel uit de pre-registratie zelf, zodat een afwijking in code of document een test breekt."""
    out = []
    for line in PREREG.read_text(encoding="utf-8").splitlines():
        if not re.match(r"\| `R[ZS]_", line):
            continue
        name, fam, tf, entry, confirm, htf, oi, stops = (c.strip() for c in line.strip().strip("|").split("|"))
        out.append((name.strip("`"), _FAMILY[fam], _TF[tf], _ENTRY[entry], confirm, htf == "ja", oi == "ja", tuple(stops.split(", "))))
    return out


def random_walk_frames(n15=20000, seed=3):
    """Een willekeurige reeks 15m-candles (kunstmatig, geen markt) met de afgeleide frames, voor snelheid en determinisme."""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.25, n15))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) + rng.uniform(0, 0.2, n15)
    low = np.minimum(open_, close) - rng.uniform(0, 0.2, n15)
    b15 = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=n15, freq="15min", tz="UTC"), "open": open_, "high": high, "low": low,
                        "close": close, "volume": 1.0})
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    b1h = b15.set_index("timestamp").resample("1h", origin="epoch").agg(agg).dropna().reset_index()
    b4h = b15.set_index("timestamp").resample("4h", origin="epoch").agg(agg).dropna().reset_index()
    return rs.build_frames(b15, b1h, b4h)


class PreregTest(unittest.TestCase):
    def test_constants_match_the_preregistration(self):
        block = re.search(r"```prereg-constants\n(.*?)```", PREREG.read_text(encoding="utf-8"), re.S).group(1)
        mods = {"rangesweep": rs, "stopquality": sq, "rangesweep_lab": rl}
        for line in block.strip().splitlines():
            name, value = (x.strip() for x in line.split("="))
            mod, attr = name.split(".")
            self.assertAlmostEqual(float(getattr(mods[mod], attr)), float(value), msg=name)

    def test_every_variant_is_preregistered(self):
        text = PREREG.read_text(encoding="utf-8")
        for v in rl.VARIANTS:
            self.assertIn(f"`{v.name}`", text)
        self.assertEqual(len(rl.VARIANTS), 15)
        self.assertEqual(rl.TESTED_TOTAL, 64)

    def test_register_equals_the_preregistered_table_exactly(self):
        code = [(v.name, v.family, v.tf, v.entry, v.confirm, v.htf, v.oi_flush, v.stops) for v in rl.VARIANTS]
        self.assertEqual(code, prereg_variants())
        self.assertEqual(len({v.name for v in rl.VARIANTS}), 15)

    def test_misser_combos_match_the_variants(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import misser_check
        lab = {(v.name, v.family, v.tf, v.confirm, v.htf) for v in rl.VARIANTS if v.entry != "split" and not v.oi_flush}
        self.assertEqual(set(misser_check.RS_COMBOS), lab)

    def test_kill_check_counts_the_same_tests_as_the_register(self):
        self.assertEqual(sum(len(v.stops) for v in rl.VARIANTS), sq.KILL_TESTS)


class RunCoinTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f = rs.build_frames(b15, b1h, b4h)

    def test_sweep_setup_is_measured_for_every_stop_and_runs_away(self):
        v = rl.RSVariant("T", "sweep", "1h", "ob", "slot", False, False)
        rows = rl.run_coin(v, "TST", self.f, 0.12, {})
        self.assertEqual(sorted(rows["stop_name"]), sorted(["zone_0", "zone_025", "zone_05", "wick_025"]))
        self.assertTrue((~rows["filled"]).all())
        self.assertEqual(set(rows["cancel"]), {"weggelopen"})
        self.assertEqual(set(rows["grade"]), {"A"})

    def test_zone_retest_fills_and_reaches_one_r(self):
        v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        rows = rl.run_coin(v, "TST", self.f, 0.12, {})
        prim = rows[rows["stop_name"] == "zone_025"]
        first_two = prim.sort_values("placed_at").head(2)
        self.assertTrue(first_two["filled"].all())
        self.assertTrue(first_two["reach_1r"].all())

    def test_row_ids_are_unique_per_setup_and_stop(self):
        v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        rows = rl.run_coin(v, "TST", self.f, 0.12, {})
        self.assertEqual(rows["row_id"].nunique(), len(rows[rows["stop_name"] == "zone_025"]))
        self.assertFalse(rows.duplicated(["row_id", "stop_name"]).any())

    def test_oi_flush_without_data_drops_the_setup(self):
        v = rl.RSVariant("T", "sweep", "1h", "ob", "slot", False, True)
        self.assertTrue(rl.run_coin(v, "TST", self.f, 0.12, {}, metrics=None).empty)

    def test_oi_flush_keeps_a_sweep_with_a_falling_oi(self):
        v = rl.RSVariant("T", "sweep", "1h", "ob", "slot", False, True)
        base = rl.run_coin(rl.RSVariant("T", "sweep", "1h", "ob", "slot", False, False), "TST", self.f, 0.12, {})
        t = base["placed_at"].iloc[0]
        ts = pd.date_range(t - pd.Timedelta(hours=40), t + pd.Timedelta(hours=2), freq="5min")
        falling = pd.DataFrame({"timestamp": ts, "oi": np.linspace(100.0, 20.0, len(ts))})
        rising = pd.DataFrame({"timestamp": ts, "oi": np.linspace(20.0, 100.0, len(ts))})
        self.assertEqual(len(rl.run_coin(v, "TST", self.f, 0.12, {}, metrics=falling)), len(base))
        self.assertTrue(rl.run_coin(v, "TST", self.f, 0.12, {}, metrics=rising).empty)

    def test_oi_change(self):
        m = pd.DataFrame({"timestamp": pd.date_range("2025-01-06", periods=4, freq="5min", tz="UTC"), "oi": [100.0, 100.0, 98.0, 97.0]})
        t0, t1 = pd.Timestamp("2025-01-06 00:06", tz="UTC"), pd.Timestamp("2025-01-06 00:16", tz="UTC")
        self.assertAlmostEqual(rl.oi_change_pct(m, t0, t1), -2.0)
        self.assertIsNone(rl.oi_change_pct(m, pd.Timestamp("2024-01-01", tz="UTC"), t1))
        self.assertIsNone(rl.oi_change_pct(None, t0, t1))

    def test_oi_point_is_unknown_until_its_own_period_has_passed(self):
        m = pd.DataFrame({"timestamp": pd.date_range("2025-01-06", periods=3, freq="5min", tz="UTC"), "oi": [100.0, 100.0, 50.0]})
        t0 = pd.Timestamp("2025-01-06 00:06", tz="UTC")
        # Het punt van 00:10 is pas om 00:15 bekend; op 00:14 mag het niet meetellen.
        self.assertAlmostEqual(rl.oi_change_pct(m, t0, pd.Timestamp("2025-01-06 00:14", tz="UTC")), 0.0)
        self.assertAlmostEqual(rl.oi_change_pct(m, t0, pd.Timestamp("2025-01-06 00:15", tz="UTC")), -50.0)

    def test_timeframes_are_aligned_on_utc_boundaries(self):
        self.assertTrue((self.f["2h"]["timestamp"].dt.hour % 2 == 0).all())
        self.assertTrue((self.f["30m"]["timestamp"].dt.minute % 30 == 0).all())
        self.assertEqual(self.f["2h"]["timestamp"].dt.tz is not None, True)


class IsolationAndDeterminismTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f = rs.build_frames(b15, b1h, b4h)
        self.v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)

    def test_two_runs_give_identical_rows(self):
        a = rl.run_coin(self.v, "TST", self.f, 0.12, {})
        b = rl.run_coin(self.v, "TST", self.f, 0.12, {})
        pd.testing.assert_frame_equal(a, b)

    def test_a_shared_cache_does_not_leak_between_coins(self):
        shifted = {k: d.assign(open=d["open"] * 1.5, high=d["high"] * 1.5, low=d["low"] * 1.5, close=d["close"] * 1.5) for k, d in self.f.items()}
        cache = {}
        rl.run_coin(self.v, "AAA", self.f, 0.12, cache)
        shared = rl.run_coin(self.v, "BBB", shifted, 0.12, cache)
        fresh = rl.run_coin(self.v, "BBB", shifted, 0.12, {})
        pd.testing.assert_frame_equal(shared, fresh)

    def test_rows_do_not_depend_on_variant_order(self):
        w = rl.RSVariant("U", "sweep", "1h", "ob", "slot", False, False)
        c1, c2 = {}, {}
        a1, b1 = rl.run_coin(self.v, "TST", self.f, 0.12, c1), rl.run_coin(w, "TST", self.f, 0.12, c1)
        b2, a2 = rl.run_coin(w, "TST", self.f, 0.12, c2), rl.run_coin(self.v, "TST", self.f, 0.12, c2)
        pd.testing.assert_frame_equal(a1, a2)
        pd.testing.assert_frame_equal(b1, b2)

    def test_the_input_frames_are_not_modified(self):
        before = {k: d.copy() for k, d in self.f.items()}
        rl.run_coin(self.v, "TST", self.f, 0.12, {})
        for k in before:
            pd.testing.assert_frame_equal(before[k], self.f[k])

    def test_no_lookahead_cutting_the_data_keeps_earlier_detections(self):
        """Dezelfde detectie op data die op het moment `cut` stopt: elke setup die in die data is geplaatst bestaat ook in de volledige run, met dezelfde
        kant, plaatsing, score en stop. Zo zou een toekomstige candle in de range, zone of HTF-context hier opvallen."""
        keys = ["stop_name", "placed_at", "direction", "grade", "score"]
        cases = [(self.v, 150), (rl.RSVariant("V", "sweep", "2h", "ob", "slot", False, False), 185),
                 (rl.RSVariant("U", "sweep", "1h", "ob", "slot", False, False), 185)]
        for v, hour in cases:
            cut = self.f["1h"]["timestamp"].iloc[hour]
            part = {tf: rs.closed_only(d, cut, tf) for tf, d in self.f.items()}
            full = rl.run_coin(v, "TST", self.f, 0.12, {})
            early = rl.run_coin(v, "TST", part, 0.12, {})
            self.assertGreater(len(early), 0, v.name)
            merged = early[keys].merge(full[keys], on=keys, how="left", indicator=True)
            self.assertTrue((merged["_merge"] == "both").all(), v.name)


class PlaceboTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f = rs.build_frames(b15, b1h, b4h)
        self.v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        self.rows = rl.run_coin(self.v, "TST", self.f, 0.12, {})
        self.real = self.rows[self.rows["stop_name"] == "zone_025"]

    def test_placebo_is_deterministic_and_draws_many_per_trade(self):
        a = rl.placebo_coin(self.v, self.f, {}, self.real, 0.12, 7)
        b = rl.placebo_coin(self.v, self.f, {}, self.real, 0.12, 7)
        pd.testing.assert_frame_equal(a, b)
        self.assertGreaterEqual(rl.PLACEBO_DRAWS, 20)
        filled = self.real[self.real["filled"]]
        self.assertGreaterEqual(len(a), len(filled))
        self.assertLessEqual(a.groupby("pair_id").size().max(), rl.PLACEBO_DRAWS)
        self.assertTrue(set(a["pair_id"]) <= set(filled["row_id"]))

    def test_placebo_by_stop_has_one_frame_per_tested_stop(self):
        out = rl.placebo_by_stop(self.v, self.f, {}, self.rows, 0.12)
        self.assertEqual(set(out), set(self.v.stops))


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.f = random_walk_frames(4000)
        self.v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)

    def test_judge_has_the_shape_the_report_needs(self):
        rows = rl.run_coin(self.v, "TST", self.f, 0.12, {})
        res = rl.judge(rows, rl.placebo_by_stop(self.v, self.f, {}, rows, 0.12), self.v)
        self.assertEqual(set(res), {"zone_0", "zone_025", "zone_05"})
        self.assertEqual(set(res["zone_0"]), {"summary"})
        for name in self.v.stops:
            self.assertEqual(set(res[name]), {"summary", "quality", "edge", "doelkans"})
            self.assertFalse(res[name]["quality"]["passes"])
            self.assertFalse(res[name]["edge"]["passes"])

    def test_judge_with_no_rows_does_not_crash_and_never_passes(self):
        res = rl.judge(pd.DataFrame(), {}, self.v)
        for name in self.v.stops:
            self.assertFalse(res[name]["quality"]["passes"])
            self.assertFalse(res[name]["edge"]["passes"])
            self.assertEqual(res[name]["summary"]["n"], 0)
        self.assertEqual(res["zone_0"]["summary"]["setups"], 0)

    def test_edge_needs_the_week_clustered_t(self):
        n = 600
        at = pd.date_range("2024-01-01", periods=n, freq="6h", tz="UTC")
        rng = np.random.default_rng(1)
        prim = pd.DataFrame({"at": at, "ref_trail": rng.normal(0.0, 1.0, n), "cost_r": 0.05, "stop_pct": 2.0})
        plac = pd.DataFrame({"ref_trail": rng.normal(0.0, 1.0, n), "cost_r": 0.05})
        out = rl.edge_verdict(prim, plac)
        self.assertFalse(out["passes"])
        self.assertIn(f"t per week minstens {rl.EDGE_T_MIN}", out["checks"])
        strong = prim.assign(ref_trail=prim["ref_trail"] + 1.0)
        self.assertTrue(rl.edge_verdict(strong, plac)["passes"])


class LoadFramesTest(unittest.TestCase):
    def test_load_frames_builds_30m_and_2h_from_the_cached_timeframes(self):
        b15, b1h, b4h = frames()
        calls = []

        def ensure(coin, years, timeframe):
            calls.append((coin, timeframe))
            return {"15m": b15, "1h": b1h, "4h": b4h}[timeframe]

        f = rl.load_frames("TST", 3, ensure=ensure)
        self.assertEqual(calls, [("TST", "15m"), ("TST", "1h"), ("TST", "4h")])
        self.assertEqual(set(f), {"15m", "30m", "1h", "2h", "4h"})


class SelectTest(unittest.TestCase):
    def test_most_fills_then_cheapest_then_wider_stop(self):
        a = next(v for v in rl.VARIANTS if v.name == "RZ_2H")
        b = next(v for v in rl.VARIANTS if v.name == "RS_1H")
        ok = lambda n, cost: {"quality": {"passes": True}, "summary": {"n": n, "median_cost_r": cost}}
        bad = {"quality": {"passes": False}, "summary": {"n": 999, "median_cost_r": 0.01}}
        res = [(a, {"zone_025": ok(400, 0.05), "zone_05": ok(400, 0.05)}), (b, {"zone_025": bad, "wick_025": ok(350, 0.04)})]
        self.assertEqual(rl.select_live(res), (a, "zone_05"))
        self.assertIsNone(rl.select_live([(a, {"zone_025": bad, "zone_05": bad})]))

    def test_choice_does_not_depend_on_the_order_of_the_results(self):
        a = next(v for v in rl.VARIANTS if v.name == "RS_1H")
        b = next(v for v in rl.VARIANTS if v.name == "RS_2H")
        ok = {"quality": {"passes": True}, "summary": {"n": 400, "median_cost_r": 0.05, "median_stop_pct": 2.0}}
        ra, rb = (a, {"zone_025": ok}), (b, {"zone_025": ok})
        self.assertEqual(rl.select_live([ra, rb]), rl.select_live([rb, ra]))


class SpeedTest(unittest.TestCase):
    def test_a_twenty_thousand_candle_frame_runs_in_reasonable_time(self):
        import time
        f = random_walk_frames(20000)
        v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        t0 = time.time()
        rows = rl.run_coin(v, "TST", f, 0.12, {})
        self.assertLess(time.time() - t0, 60)
        self.assertGreater(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
