"""Het HesPulse-model (app/model.py) op synthetische candles: elke stap met een positief en een negatief geval, geen vooruitkijken
(prefix-toets: meer candles veranderen niets aan wat eerder vaststond), geen dubbeltelling, en short als spiegelbeeld van long.
Preregistratie: docs/onderzoek/hespulse-model/preregistratie.md (§4)."""
import unittest

import numpy as np
import pandas as pd

from app import model as M
from app import poc, smc_eval
from tests.hespulse_model import synth as S

LEGS = [(64, 100.0), (64, 110.0), (48, 105.0), (80, 114.0), (40, 107.5), (24, 110.0), (24, 108.0)]
SWEEP = [108.0, 108.05, 107.0, 107.6]           # prik onder de pool 107,45 en slot erboven
RED = [107.6, 107.7, 107.3, 107.4]              # het order block
DISP = [107.4, 109.0, 107.35, 108.9]            # displacement: slot 1,2 boven de high van het order block
FVG3 = [108.9, 109.6, 108.8, 109.5]             # derde candle: low 108,8 > high 107,7 van het order block
SHIFT = [109.5, 110.4, 109.4, 110.3]            # slot boven de top 110,05 vóór de sweep
TAIL_FROM = 344                                  # index van de prikcandle (som van LEGS)


def base_rows(tail=None, after=16):
    rows = S.path(LEGS)
    rows += [list(c) for c in (tail if tail is not None else [SWEEP, RED, DISP, FVG3, SHIFT])]
    rows += S.path([(after, 111.0)], start_price=rows[-1][3]) if after else []
    return rows


def end_of(fr):
    return fr["15m"]["timestamp"].iloc[-1] + pd.Timedelta(minutes=15)


def run(rows, pocs=None, now=None):
    fr = S.frames(rows)
    return M.scenarios(fr, now or end_of(fr), pocs)


def longs(scs):
    return [s for s in scs if s["direction"] == "long"]


def steps(sc):
    return {s["stap"]: s for s in sc["steps"]}


def at(i15):
    return S.START + pd.Timedelta(minutes=15) * (i15 + 1)


class PivotAndBreakTest(unittest.TestCase):
    def frame(self, highs, lows=None, closes=None):
        highs = np.asarray(highs, float)
        lows = highs - 1 if lows is None else np.asarray(lows, float)
        closes = (highs + lows) / 2 if closes is None else np.asarray(closes, float)
        rows = [[c, h, l, c] for h, l, c in zip(highs, lows, closes)]
        return M._frame(S.frame(rows, "4h"), "4h", False)

    def test_equal_lows_are_one_swing_the_first(self):
        f = self.frame([5, 4, 3, 3, 4, 5, 6], lows=[4, 3, 2, 2, 3, 4, 5])
        self.assertEqual(list(np.flatnonzero(M.swing_lows(f, 2))), [2])

    def test_a_wick_through_the_swing_is_no_break(self):
        highs = [1, 2, 5, 2, 1, 1, 6, 2]
        closes = [0.5, 1.5, 4.5, 1.5, 0.5, 0.5, 4.9, 1.5]   # candle 6 prikt met een lont tot 6, slot 4,9 onder de top 5
        self.assertEqual([b for b in M.breaks(self.frame(highs, closes=closes), 2) if b.up], [])

    def test_a_close_breaks_the_swing_once(self):
        highs = [1, 2, 5, 2, 1, 1, 6, 7, 8]
        closes = [0.5, 1.5, 4.5, 1.5, 0.5, 0.5, 5.5, 6.5, 7.5]
        ups = [b for b in M.breaks(self.frame(highs, closes=closes), 2) if b.up]
        self.assertEqual([(b.i, b.level) for b in ups], [(6, 5.0)])
        self.assertIsNone(ups[0].label)

    def test_labels_bos_and_choch(self):
        f = M._frame(S.frames(base_rows())["4h"], "4h", False)
        evs = M.breaks(f, 2)
        self.assertTrue(evs)
        for prev, ev in zip(evs, evs[1:]):
            self.assertEqual(ev.label, "BOS" if prev.up == ev.up else "CHOCH")


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.fr = S.frames(base_rows())

    def ctx(self, i15):
        f4 = M._frame(self.fr["4h"], "4h", False)
        return M.Context4h(f4, "long").at(int(at(i15).value))

    def test_long_range_after_the_break(self):
        c = self.ctx(TAIL_FROM)
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c.L, 104.95, places=6)
        self.assertAlmostEqual(c.H, 114.05, places=6)
        self.assertAlmostEqual(c.eq, (104.95 + 114.05) / 2)

    def test_no_range_before_the_break(self):
        self.assertIsNone(self.ctx(150))

    def test_bias_turns_neutral_after_60_candles_of_4h(self):
        rows = base_rows(after=0) + S.path([(16 * 64, 112.0)], start_price=110.3)   # 64 candles van 4u zonder breuk, binnen de range
        fr = S.frames(rows)
        f4 = M._frame(fr["4h"], "4h", False)
        ctx = M.Context4h(f4, "long")
        b = M.breaks(f4, 2)[-1]
        self.assertIsNotNone(ctx.at(int(f4.ct[b.i + M.BIAS_MAX_BARS])))
        self.assertIsNone(ctx.at(int(f4.ct[b.i + M.BIAS_MAX_BARS + 1])))

    def test_close_below_L_ends_the_range(self):
        rows = base_rows(after=0) + S.path([(40, 103.0)], start_price=110.3)
        fr = S.frames(rows)
        f4 = M._frame(fr["4h"], "4h", False)
        self.assertIsNone(M.Context4h(f4, "long").at(int(f4.ct[-1])))


class PoolTest(unittest.TestCase):
    def pools(self, rows, i15):
        fr = S.frames(rows)
        f4, f1, f15 = (M._frame(fr[tf], tf, False) for tf in ("4h", "1h", "15m"))
        t = int(at(i15).value)
        ctx = M.Context4h(f4, "long").at(t)
        return M.Pools(f1, f15).valid(t, ctx, f15.c[i15]), ctx

    def test_untouched_pool_in_discount(self):
        pools, ctx = self.pools(base_rows(), TAIL_FROM - 1)
        levels = sorted(round(p.level, 2) for p in pools)
        self.assertEqual(levels, [104.95, 107.45])
        self.assertTrue(all(ctx.L <= p.level <= ctx.eq for p in pools))

    def test_a_touched_pool_is_used_up(self):
        pools, _ = self.pools(base_rows(), TAIL_FROM)          # de prikcandle raakte 107,45
        self.assertEqual([round(p.level, 2) for p in pools], [104.95])

    def test_equal_lows_are_one_pool(self):
        rows = S.path(LEGS[:-1]) + S.path([(24, 107.5), (24, 110.0), (24, 108.5)], start_price=110.0)
        pools, _ = self.pools(rows, len(rows) - 1)
        near = [p for p in pools if 107 < p.level < 108]
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0].n, 2)


class ScenarioTest(unittest.TestCase):
    def test_full_scenario_with_both_moments(self):
        (sc,) = longs(run(base_rows()))
        st = steps(sc)
        self.assertEqual(sc["status"], "afgerond")
        self.assertEqual(st["sweep"]["at"], at(TAIL_FROM))                  # het slot terug boven de pool
        self.assertEqual(st["shift"]["at"], at(TAIL_FROM + 4))
        self.assertEqual(st["displacement"]["at"], at(TAIL_FROM + 4))         # vastgesteld bij de shift
        self.assertEqual(st["displacement"]["gesloten_at"], at(TAIL_FROM + 3))  # de derde FVG-candle
        self.assertEqual(st["entry"]["at"], at(TAIL_FROM + 4))
        self.assertLess(sc["discovered_at"], st["sweep"]["at"])
        e = sc["entry"]
        self.assertAlmostEqual(e["limit"], 108.8)
        self.assertAlmostEqual(e["take"], 114.05, places=6)
        self.assertEqual(e["target_kind"], "range")
        self.assertFalse(e["ob_overlap"])
        self.assertAlmostEqual(e["extreme"], 107.0)
        self.assertLess(e["stop"], 107.0)
        self.assertAlmostEqual(e["rr"], (e["take"] - e["limit"]) / (e["limit"] - e["stop"]))
        self.assertEqual(e["expires_at"], st["entry"]["at"] + pd.Timedelta(hours=6))

    def test_sweep_names_the_pool_point_and_its_size(self):
        """De kaartgrafiek tekent de gesweepte pool vanaf zijn punt en noemt gelijke lows EQL: dat staat in de stap, niet herberekend."""
        (sc,) = longs(run(base_rows()))
        sw = steps(sc)["sweep"]
        self.assertAlmostEqual(sw["pool"], 107.45, places=6)
        self.assertLess(sw["pool_at"], sw["prik_at"])
        self.assertEqual(sw["pool_n"], 1)
        self.assertEqual(sc["pool0"]["n"], 1)
        e = sc["entry"]                     # de range zoals hij bij de entry was (de top groeit mee tot dan), met het doel op zijn rand
        self.assertAlmostEqual(e["range_high"], e["take"], places=6)
        self.assertAlmostEqual((e["range_low"] + e["range_high"]) / 2, e["eq"], places=6)
        self.assertAlmostEqual(e["range_low"], sc["range_low"], places=6)
        (sh,) = [s for s in run(S.mirror_rows(base_rows())) if s["direction"] == "short"]
        self.assertEqual((steps(sh)["sweep"]["pool_at"], steps(sh)["sweep"]["pool_n"]), (sw["pool_at"], 1))

    def test_run_is_no_sweep(self):
        tail = [[108.0, 108.05, 106.2, 107.6], RED, DISP, FVG3, SHIFT]     # 1,25 onder de pool: meer dan 2,5 ATR
        (sc,) = longs(run(base_rows(tail)))
        self.assertIsNone(sc["entry"])
        self.assertEqual(sc["attempts"][0]["reden"], "run")

    def test_no_close_back_within_six_candles(self):
        down = [[107.4, 107.45, 107.2, 107.3]] * 6
        tail = [[108.0, 108.05, 107.2, 107.4]] + down + [SHIFT]
        (sc,) = longs(run(base_rows(tail)))
        self.assertIsNone(sc["entry"])
        self.assertEqual(sc["attempts"][0]["reden"], "geen_herstel")

    def test_shift_without_displacement_does_not_count(self):
        # Een groene prikcandle en een trage klim zonder rode candle: geen order block, dus geen displacement.
        climb = S.path([(20, 110.3)], start_price=107.6, wick=0.02)
        (sc,) = longs(run(base_rows([[107.55, 108.0, 107.0, 107.6]] + climb)))
        self.assertIsNone(sc["entry"])
        self.assertEqual(sc["attempts"][0]["reden"], "geen_displacement")

    def test_limit_in_premium_is_refused(self):
        tail = [SWEEP, RED, [107.4, 109.65, 107.35, 109.6], [109.75, 109.95, 109.7, 109.9], [109.9, 110.4, 109.8, 110.3]]
        (sc,) = longs(run(base_rows(tail)))
        self.assertIsNone(sc["entry"])
        self.assertEqual(sc["attempts"][0]["reden"], "premium")

    def test_retest_before_entry_known(self):
        tail = [SWEEP, RED, DISP, FVG3, [109.5, 109.6, 108.7, 109.0], [109.0, 110.4, 108.95, 110.3]]
        (sc,) = longs(run(base_rows(tail)))
        self.assertIsNone(sc["entry"])
        self.assertEqual(sc["attempts"][0]["reden"], "terugtest_al_geweest")

    def test_entry_waits_for_the_third_fvg_candle(self):
        """Displacement op de shiftcandle zelf: de entry is pas bekend als de derde FVG-candle sloot."""
        tail = [SWEEP, RED, [107.4, 110.4, 107.35, 110.3], [110.3, 110.6, 109.3, 110.4]]
        rows = base_rows(tail)
        fr = S.frames(rows)
        (sc,) = longs(M.scenarios(fr, at(TAIL_FROM + 2)))
        self.assertEqual(sc["status"], "wacht_fvg")
        (sc,) = longs(M.scenarios(fr, end_of(fr)))
        self.assertEqual(steps(sc)["entry"]["at"], at(TAIL_FROM + 3))

    def test_one_scenario_per_range(self):
        scs = run(base_rows())
        self.assertEqual(len({s["range_id"] for s in scs}), len(scs))

    def test_short_is_the_mirror_of_long(self):
        (lg,) = longs(run(base_rows()))
        (sh,) = [s for s in run(S.mirror_rows(base_rows())) if s["direction"] == "short"]
        # 'ontdekt' hangt af van de 6%-afstand, en die is in procenten: rond 200 gespiegeld ligt de koers lager, dus kan dat moment
        # verschillen. Alle stappen in prijs (sweep, shift, displacement, entry) zijn exact gespiegeld.
        self.assertEqual([(s["stap"], s["at"]) for s in lg["steps"][1:]], [(s["stap"], s["at"]) for s in sh["steps"][1:]])
        for k in ("limit", "stop", "take", "extreme"):
            self.assertAlmostEqual(sh["entry"][k], 200 - lg["entry"][k], places=6)
        self.assertAlmostEqual(sh["entry"]["zone_low"], 200 - lg["entry"]["zone_high"], places=6)
        self.assertAlmostEqual(sh["range_high"], 200 - lg["range_low"], places=6)

    def test_floor_matches_smc_eval_for_both_directions(self):
        self.assertAlmostEqual(M._floor(100.0, 99.9), smc_eval.floor_stop("long", 100.0, 99.9, min_pct=0.4))
        self.assertAlmostEqual(-M._floor(-100.0, -100.1), smc_eval.floor_stop("short", 100.0, 100.1, min_pct=0.4))


class PocTest(unittest.TestCase):
    def level(self, price, touched=None, start="2026-10-02"):
        return poc.PocLevel("day", pd.Timestamp(start, tz="UTC"), price, touched)

    def test_a_closer_naked_poc_is_the_target(self):
        (sc,) = longs(run(base_rows(), pocs=[self.level(112.0)]))
        self.assertEqual(sc["entry"]["target_kind"], "poc")
        self.assertAlmostEqual(sc["entry"]["take"], 112.0)
        self.assertFalse(sc["entry"]["poc_samenval"])

    def test_a_touched_poc_does_not_count(self):
        (sc,) = longs(run(base_rows(), pocs=[self.level(112.0, touched=pd.Timestamp("2026-10-03T12:00Z"))]))
        self.assertEqual(sc["entry"]["target_kind"], "range")

    def test_poc_inside_the_zone_is_samenval(self):
        (sc,) = longs(run(base_rows(), pocs=[self.level(108.0)]))
        self.assertTrue(sc["entry"]["poc_samenval"])

    def test_without_poc_data_samenval_is_not_measured(self):
        (sc,) = longs(run(base_rows()))
        self.assertIsNone(sc["entry"]["poc_samenval"])


def random_rows(seed: int, n: int = 2600) -> list[list[float]]:
    rng = np.random.default_rng(seed)
    drift = np.zeros(n)
    i = 0
    while i < n:
        length = int(rng.integers(30, 200))
        drift[i:i + length] = rng.choice([-1, 1]) * rng.uniform(0.0003, 0.0015)
        i += length
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.003, n)))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.0015, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.0015, n)))
    return [list(r) for r in zip(open_, high, low, close)]


class NoLookaheadTest(unittest.TestCase):
    def assert_prefix(self, fr, cuts, pocs=None):
        full = M.scenarios(fr, end_of(fr), pocs)
        for cut in cuts:
            part = M.scenarios(S.cut_frames(fr, cut), cut, pocs)
            want = [s for s in full if s["discovered_at"] <= cut]
            self.assertEqual([(s["range_id"], s["discovered_at"]) for s in part], [(s["range_id"], s["discovered_at"]) for s in want])
            for p, w in zip(part, want):
                self.assertEqual(M.known_until(p, cut), M.known_until(w, cut), f"{w['range_id']} op {cut}")
                self.assertEqual([(a["reden"], a["at"]) for a in p["attempts"]], [(a["reden"], a["at"]) for a in w["attempts"] if a["at"] <= cut])
                if p["entry"]:
                    self.assertEqual(p["entry"], w["entry"])
                # Aanvullend besluit 2026-11-03: P, B en B0 volgen dezelfde eis. Wat op het snijmoment bekend was, is gelijk; niets eerder.
                for key in ("p", "b", "b0"):
                    if w[key] is not None and w[key]["known_at"] <= cut:
                        self.assertEqual(p[key], w[key], f"{key} {w['range_id']} op {cut}")
                    else:
                        self.assertIsNone(p[key], f"{key} {w['range_id']} op {cut} te vroeg")

    def test_more_candles_never_change_an_earlier_step(self):
        fr = S.frames(base_rows())
        self.assert_prefix(fr, [at(i) for i in range(TAIL_FROM - 3, TAIL_FROM + 8)])

    def test_random_walks(self):
        found = 0
        for seed in (1, 2, 3, 4, 5, 6):
            fr = S.frames(random_rows(seed))
            ts = fr["15m"]["timestamp"]
            found += len(M.scenarios(fr, end_of(fr)))
            self.assert_prefix(fr, [ts.iloc[k] + pd.Timedelta(minutes=15) for k in range(900, len(ts), 173)])
        self.assertGreater(found, 0, "de willekeurige reeksen moeten scenario's opleveren, anders toetst dit niets")


class AltEntryTest(unittest.TestCase):
    """B en B0 (lagere top, hier long-frame: hogere bodem) en P (POC-limiet): aanvullend besluit 2026-11-03."""

    def all_scs(self, seeds=(1, 3, 5, 10, 11)):
        out = []
        for seed in seeds:
            fr = S.frames(random_rows(seed))
            out += M.scenarios(fr, end_of(fr))
        return out

    def test_b_is_a_subset_rule_of_b0_and_lies_in_discount(self):
        scs = self.all_scs()
        bs = [s for s in scs if s["b"]]
        self.assertTrue(bs and len([s for s in scs if s["b0"]]) >= len(bs), "de reeksen moeten B en B0 opleveren")
        for s in scs:
            for key in ("b", "b0"):
                e = s[key]
                if not e:
                    continue
                sign = 1 if s["direction"] == "long" else -1
                self.assertGreater((e["take"] - e["limit"]) * sign, 0)
                self.assertGreater((e["limit"] - e["stop"]) * sign, 0)
                self.assertLess(e["low_at"], e["shift_at"])
                self.assertLessEqual(e["shift_at"], e["known_at"])
                self.assertTrue(e["range_low"] <= e["extreme"] <= e["range_high"])       # de range van het moment zelf (H groeit mee)
                if key == "b":
                    # discount (long) of premium (short): de bodem/top aan de goede kant van het evenwicht
                    self.assertLessEqual((e["extreme"] - e["eq"]) * sign, 1e-9)

    def test_p_on_a_naked_poc_in_discount(self):
        lvl = poc.PocLevel("day", pd.Timestamp("2026-10-02", tz="UTC"), 106.0, None)
        (sc,) = longs(run(base_rows(), pocs=[lvl]))
        self.assertIsNotNone(sc["p"])
        self.assertAlmostEqual(sc["p"]["limit"], 106.0)
        self.assertLess(sc["p"]["stop"], 106.0)
        self.assertGreater(sc["p"]["take"], 106.0)

    def test_tegenvoorbeeld_p_niet_in_premium_of_zonder_data(self):
        lvl = poc.PocLevel("day", pd.Timestamp("2026-10-02", tz="UTC"), 109.0, None)        # boven EQ 107,7
        (sc,) = longs(run(base_rows(), pocs=[lvl]))
        self.assertIsNone(sc["p"])
        (sc,) = longs(run(base_rows()))
        self.assertIsNone(sc["p"])

    def test_a_is_unchanged_by_the_new_entries(self):
        (sc,) = longs(run(base_rows()))
        self.assertAlmostEqual(sc["entry"]["limit"], 108.8)


class FillTest(unittest.TestCase):
    def b5(self, rows, start="2026-10-05T00:00Z"):
        return S.frame(rows, "5min", pd.Timestamp(start))

    def test_fill_on_first_touch_after_publication(self):
        b5 = self.b5([[110, 110.2, 109.5, 110], [110, 110.1, 108.8, 109], [109, 109.1, 108.5, 108.7]])
        r = M.walk_fill("long", 108.8, 114.0, pd.Timestamp("2026-10-05T00:00Z"), None, b5, price_at_publish=110.0)
        self.assertEqual((r["state"], r["at"], r["door_limiet"], r["vulbaar"]), ("gevuld", pd.Timestamp("2026-10-05T00:05Z"), False, True))

    def test_not_fillable_when_price_already_through(self):
        r = M.walk_fill("long", 108.8, 114.0, pd.Timestamp("2026-10-05T00:00Z"), None, self.b5([[108, 108.2, 107.9, 108]]), price_at_publish=108.5)
        self.assertEqual(r["state"], "niet_vulbaar")

    def test_target_first_runs_away_and_expiry(self):
        b5 = self.b5([[110, 114.5, 109.5, 114]])
        self.assertEqual(M.walk_fill("long", 108.8, 114.0, pd.Timestamp("2026-10-05T00:00Z"), None, b5)["state"], "weggelopen")
        b5 = self.b5([[110, 110.2, 109.5, 110]] * 3)
        r = M.walk_fill("long", 108.8, 114.0, pd.Timestamp("2026-10-05T00:00Z"), pd.Timestamp("2026-10-05T00:10Z"), b5)
        self.assertEqual(r["state"], "vervallen")

    def test_new_4h_break_cancels(self):
        b5 = self.b5([[110, 110.2, 109.5, 110]] * 3)
        r = M.walk_fill("long", 108.8, 114.0, pd.Timestamp("2026-10-05T00:00Z"), None, b5, breaks_at=[pd.Timestamp("2026-10-05T00:05Z")])
        self.assertEqual(r["state"], "context_weg")

    def test_outcome_stop_and_target_in_one_candle_is_stop(self):
        b5 = self.b5([[109, 109.1, 108.7, 109], [109, 114.5, 106.0, 110]])
        r = M.outcome("long", 108.8, 106.9, 114.0, pd.Timestamp("2026-10-05T00:00Z"), b5)
        self.assertEqual((r["state"], r["r"], r["ambiguous"]), ("stop_loss", -1.0, True))


if __name__ == "__main__":
    unittest.main()


def daily_trend(up: bool, end: pd.Timestamp = S.START, n_legs: int = 16) -> pd.DataFrame:
    """Dagcandles die eindigen op `end` met een duidelijke trap omhoog of omlaag: de laatste dagbreuk ligt dan in die richting."""
    legs, p = [], 100.0
    for i in range(n_legs):
        p = p + (6 if i % 2 == 0 else -3) * (1 if up else -1)
        legs.append((3, p))
    rows = S.path(legs, wick=0.3)
    return S.frame(rows, tf="1D", start=end - pd.Timedelta(days=len(rows)))


class TopDownTest(unittest.TestCase):
    """Aanvullend besluit 2026-11-03: de dag bepaalt de richting; de 4u-range volgt de laatste 4u-breuk in die richting."""

    def run_with_day(self, up: bool):
        fr = S.frames(base_rows())
        fr["1d"] = daily_trend(up)
        return M.scenarios(fr, end_of(fr))

    def test_dag_omlaag_houdt_het_long_scenario_tegen(self):
        self.assertEqual(longs(self.run_with_day(False)), [])

    def test_tegenvoorbeeld_dag_omhoog_laat_het_long_scenario_staan(self):
        (sc,) = longs(self.run_with_day(True))
        self.assertAlmostEqual(sc["entry"]["limit"], 108.8)
        self.assertEqual([s for s in self.run_with_day(True) if s["direction"] == "short"], [])

    def test_zonder_dagcandles_de_oude_regel(self):
        (sc,) = longs(run(base_rows()))
        self.assertIsNotNone(sc["entry"])

    def test_dagbias_zonder_vooruitkijken(self):
        day = daily_trend(False)
        bias = M.DailyBias(day, S.START)
        later = M.DailyBias(pd.concat([day, daily_trend(True, end=S.START + pd.Timedelta(days=60))]), S.START + pd.Timedelta(days=60))
        t = int((S.START - pd.Timedelta(hours=1)).value)
        self.assertEqual(bias.at(t), "short")
        self.assertEqual(later.at(t), "short")          # latere dagen veranderen een eerder moment niet

    def test_random_walks_met_dag_blijven_prefix_vast(self):
        nt = NoLookaheadTest()
        for seed in (1, 3, 5):
            fr = S.frames(random_rows(seed))
            b15 = fr["15m"]
            fr["1d"] = b15.set_index("timestamp").resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                                                      "volume": "sum"}).dropna().reset_index()
            ts = b15["timestamp"]
            nt.assert_prefix(fr, [ts.iloc[k] + pd.Timedelta(minutes=15) for k in range(900, len(ts), 211)])
