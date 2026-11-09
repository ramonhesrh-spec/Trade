import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import strategy_lab  # noqa: E402

from app import track_record  # noqa: E402
from app.replay import rangesweep as rs, rangesweep_lab as rl, stopquality as sq, zonesweep as zs, zonesweep_lab as zl  # noqa: E402
from tests.replay.test_zonesweep import DRIFT, PRIK_HERSTEL, UP, ZONE, base, make_frames, mirror  # noqa: E402
from tests.test_strategy_lab_rangesweep import fake_cell, synthetic_ensure  # noqa: E402

PREREG = ROOT / "docs" / "onderzoek" / "zone-sweep" / "preregistratie.md"
_TF = {"1u": "1h", "2u": "2h", "4u": "4h"}
_ENTRY = {"bovenkant zone": "zone", "midden van de zone": "midden"}
# Na het herstel eerst een terugval tot in de zone (laag 100,2, onder de limiet 100,3, boven de stop) zonder het midden van het kader (100,6) te raken.
DIP = (100.5, 100.55, 100.2, 100.4)
INSIDE = [(100.2, 100.25, 99.9, 100.1)] * 5


def prereg_variants():
    out = []
    for line in PREREG.read_text(encoding="utf-8").splitlines():
        if not re.match(r"\| ZS_", line):
            continue
        name, tf, entry, htf = (c.strip() for c in line.strip().strip("|").split("|"))
        out.append((name, _TF[tf], _ENTRY[entry], htf == "met"))
    return out


class PreregTest(unittest.TestCase):
    def test_variants_equal_the_preregistered_table(self):
        self.assertEqual([(v.name, v.tf, v.entry, v.htf) for v in zl.VARIANTS], prereg_variants())
        self.assertEqual(len(zl.VARIANTS), 7)
        for v in zl.VARIANTS:
            self.assertEqual(v.stops, ("wick_025", "wick_05"))
            self.assertFalse(v.oi_flush)

    def test_register_counts(self):
        self.assertEqual(zl.PRIOR_VARIANTS, 64)
        self.assertEqual(zl.KILL_TESTS, 14)
        self.assertEqual(zl.TESTED_TOTAL, 78)
        self.assertEqual(zl.EDGE_T_MIN, 3.4)
        self.assertEqual((zl.LAB_COST_PCT, zl.LAB_YEARS, zl.PLACEBO_DRAWS, zl.PLACEBO_SEED), (0.12, 3.0, 20, 7))

    def test_constants_match_the_preregistration(self):
        block = re.search(r"```prereg-constants\n(.*?)```", PREREG.read_text(encoding="utf-8"), re.S).group(1)
        mods = {"zonesweep": zs, "zonesweep_lab": zl, "rangesweep": rs}
        lines = block.strip().splitlines()
        self.assertGreaterEqual(len(lines), 15)
        for line in lines:
            name, value = (x.strip() for x in line.split("="))
            mod, attr = name.split(".")
            self.assertAlmostEqual(float(getattr(mods[mod], attr)), float(value), msg=name)
        self.assertEqual(zs.BUFFERS, {"wick_025": 0.25, "wick_05": 0.5})

    def test_register_placebo_and_choice_are_written_down(self):
        text = PREREG.read_text(encoding="utf-8")
        for part in ("**78**", "t ≥ 3,4", "dezelfde soort", "vraagzone bij long, aanbodzone bij short", "zonesweep.active_zones",
                     "meeste vullingen", "laagste mediane kosten", "bredere stop", "S2", "S3", "14 toetsen"):
            self.assertIn(part, text)


class RunCoinTest(unittest.TestCase):
    def test_setup_that_runs_away_is_cancelled_for_both_stops(self):
        rows = zl.run_coin(zl.VARIANTS[3], "TST", make_frames(base([PRIK_HERSTEL] + UP)), 0.12, {})
        self.assertEqual(sorted(rows["stop_name"]), ["wick_025", "wick_05"])
        self.assertFalse(rows["filled"].any())
        self.assertEqual(set(rows["cancel"]), {"weggelopen"})
        self.assertEqual(rows["row_id"].nunique(), 1)

    def test_dip_into_the_zone_fills_and_is_measured(self):
        f = make_frames(base([PRIK_HERSTEL, DIP] + UP))
        rows = zl.run_coin(zl.VARIANTS[3], "TST", f, 0.12, {})
        self.assertTrue(rows["filled"].all(), rows[["stop_name", "cancel"]])
        setup = zs.find_setups(f, "1h", "zone", False)[0][0]
        for r in rows.itertuples():
            self.assertAlmostEqual(r.entry, 100.3)
            self.assertAlmostEqual(r.stop, zs.final_stop(setup, r.stop_name))
            self.assertTrue(r.reach_1r)
        self.assertNotIn("grade", rows)

    def test_htf_filter_variant_can_differ_from_the_variant_without(self):
        rows = base([PRIK_HERSTEL] + UP)
        with mock.patch.object(rs, "htf_context", lambda b, b4h: (pd.Series([-1] * len(b)).to_numpy(), pd.Series([102.0] * len(b)).to_numpy(),
                                                                   pd.Series([90.0] * len(b)).to_numpy())):
            self.assertTrue(zl.run_coin(zl.VARIANTS[0], "TST", make_frames(rows), 0.12, {}).empty)
            self.assertEqual(len(zl.run_coin(zl.VARIANTS[3], "TST", make_frames(rows), 0.12, {})), 2)


class ActiveZoneTest(unittest.TestCase):
    def test_closes_inside_an_active_demand_zone_are_candidates(self):
        f = make_frames(base(INSIDE + UP))
        bull, bear = zs.active_zones(f, "1h", "bull"), zs.active_zones(f, "1h", "bear")
        start = 30 + len(ZONE) + len(DRIFT)
        self.assertEqual(len(bull), len(f["1h"]))
        for j in range(start, start + len(INSIDE)):
            self.assertIsNotNone(bull[j])
            self.assertEqual((bull[j].kind, bull[j].low, bull[j].high), ("bull", 99.7, 100.3))
        self.assertTrue(all(z is None for z in bull[:start]))
        self.assertTrue(all(bull[j] is None for j in range(start + len(INSIDE), len(bull))))
        self.assertTrue(all(z is None or z.kind == "bear" for z in bear))
        self.assertFalse(any(bear[j] is not None for j in range(start, start + len(INSIDE))))

    def test_matches_zone_active_and_the_known_bar(self):
        f = make_frames(base(INSIDE + UP))
        b = zl.add_indicators(f["1h"]).reset_index(drop=True)
        for j, z in enumerate(zs.active_zones(f, "1h", "bull")):
            if z is not None:
                self.assertTrue(rs.zone_active(z, j - 1), j)
                self.assertTrue(z.low < b["close"].iloc[j] < z.high)

    def test_mirror_gives_supply_zones(self):
        f = make_frames(mirror(base(INSIDE + UP)))
        start = 30 + len(ZONE) + len(DRIFT)
        bear = zs.active_zones(f, "1h", "bear")
        self.assertEqual(bear[start].kind, "bear")


class PlaceboTest(unittest.TestCase):
    def setUp(self):
        self.f = make_frames(base([PRIK_HERSTEL, DIP] + INSIDE + UP + INSIDE + UP))
        self.v = zl.VARIANTS[3]
        rows = zl.run_coin(self.v, "TST", self.f, 0.12, {})
        self.filled = rows[rows["filled"].astype(bool)]

    def test_placebo_pairs_with_the_real_trade_and_is_deterministic(self):
        part = self.filled[self.filled["stop_name"] == "wick_025"]
        a = zl.placebo_coin(self.v, self.f, {}, part, 0.12)
        b = zl.placebo_coin(self.v, self.f, {}, part, 0.12)
        self.assertEqual(len(a), zl.PLACEBO_DRAWS * len(part))
        self.assertEqual(set(a["pair_id"]), set(part["row_id"]))
        pd.testing.assert_frame_equal(a, b)
        # Elke trekking ligt binnen een actieve zone van de soort die bij de kant van de echte trade hoort.
        side = dict(zip(part["row_id"], part["direction"]))
        bt = zl.add_indicators(self.f["1h"]).reset_index(drop=True)
        zones = {d: zs.active_zones(self.f, self.v.tf, k) for d, k in (("long", "bull"), ("short", "bear"))}
        for r in a.itertuples():
            j = int(bt["timestamp"].searchsorted(r.at))
            z = zones[side[r.pair_id]][j]
            self.assertIsNotNone(z, r)
            self.assertTrue(z.low < r.entry < z.high)
        self.assertIn("long", set(side.values()))

    def test_each_side_draws_from_its_own_zone_kind_and_seed(self):
        long_row = self.filled.iloc[:1]
        short_row = long_row.assign(direction="short", row_id="TST:S:0")
        calls = []

        def fake(real, b15, bt, active, atr15, cost, seed, draws):
            calls.append((set(real["direction"]), active, seed, draws))
            return pd.DataFrame()

        cache = {}
        with mock.patch.object(zl.sq, "placebo_rows", side_effect=fake):
            out = zl.placebo_coin(self.v, self.f, cache, pd.concat([long_row, short_row]), 0.12)
        self.assertTrue(out.empty)
        self.assertEqual([(c[0], c[2], c[3]) for c in calls], [({"long"}, 7, 20), ({"short"}, 8, 20)])
        self.assertEqual(calls[0][1], zs.active_zones(self.f, self.v.tf, "bull"))
        self.assertEqual(calls[1][1], zs.active_zones(self.f, self.v.tf, "bear"))

    def test_no_fills_no_placebo(self):
        self.assertTrue(zl.placebo_coin(self.v, self.f, {}, self.filled.iloc[:0], 0.12).empty)
        by_stop = zl.placebo_by_stop(self.v, self.f, {}, self.filled.iloc[:0], 0.12)
        self.assertEqual(set(by_stop), {"wick_025", "wick_05"})


class JudgeAndChoiceTest(unittest.TestCase):
    def test_judge_has_only_the_two_tested_stops(self):
        f = make_frames(base([PRIK_HERSTEL, DIP] + UP))
        v = zl.VARIANTS[3]
        rows = zl.run_coin(v, "TST", f, 0.12, {})
        out = zl.judge(rows, zl.placebo_by_stop(v, f, {}, rows[rows["filled"]], 0.12), v)
        self.assertEqual(set(out), {"wick_025", "wick_05"})
        for name in out:
            self.assertEqual(out[name]["quality"]["verdict"], "TE WEINIG TRADES")
            self.assertFalse(out[name]["edge"]["passes"])

    def test_select_live_prefers_the_wider_buffer_on_a_tie(self):
        results = [(v, {s: fake_cell(passes=True, n=400) for s in v.stops}) for v in zl.VARIANTS[:2]]
        self.assertEqual(zl.select_live(results), (zl.VARIANTS[0], "wick_05"))
        results[1][1]["wick_025"]["summary"] = {**results[1][1]["wick_025"]["summary"], "n": 500}
        self.assertEqual(zl.select_live(results), (zl.VARIANTS[1], "wick_025"))
        self.assertIsNone(zl.select_live([(v, {s: fake_cell(passes=False) for s in v.stops}) for v in zl.VARIANTS]))

    def test_kill_check_decides_over_fourteen_tests(self):
        res = [{"summary": {"n": 400, "median_cost_r": 0.05}, "accept": {"passes": False}}] * zl.KILL_TESTS
        self.assertEqual(sq.kill_check(res)["status"], "onvolledig")
        out = sq.kill_check(res, zl.KILL_TESTS)
        self.assertEqual(out["status"], "volledig")
        self.assertTrue(out["S2"])

    def test_labels_for_bewijs(self):
        for v in zl.VARIANTS:
            self.assertIn(v.name.lower(), track_record.LAB_LABELS)
        for key in (zl.STOP_KEY, zl.EDGE_KEY):
            self.assertIn(key, track_record.LAB_LABELS)


def zs_result(v, passes=False):
    return {s: fake_cell(passes) for s in v.stops}


META = {"kosten": 0.12, "jaren": 3.0, "coins": 20, "first": "2023-10-20", "last": "2026-10-19"}


class ReportTest(unittest.TestCase):
    def test_report_names_the_register_and_every_variant(self):
        md = strategy_lab.render_rangesweep([(v, zs_result(v)) for v in zl.VARIANTS], META, strategy_lab.ZONESWEEP)
        self.assertIn("14 toetsen in deze familie, 78 in het register", md)
        self.assertIn("t ≥ 3.4", md)
        for v in zl.VARIANTS:
            self.assertIn(v.name, md)
        self.assertIn("S2 (geen enkele toets geslaagd): ja", md)
        self.assertIn("Bij 14 toetsen", md)
        self.assertNotIn("zonder buffer", md)

    def test_incomplete_set_is_not_judged(self):
        md = strategy_lab.render_rangesweep([(zl.VARIANTS[0], zs_result(zl.VARIANTS[0]))], META, strategy_lab.ZONESWEEP)
        self.assertIn("S2 en S3 niet beoordeeld: 2 van 14 toetsen", md)

    def test_save_writes_the_zone_sweep_keys(self):
        results = [(v, zs_result(v, passes=True)) for v in zl.VARIANTS]
        with mock.patch.object(strategy_lab.repo, "set_rule_lab") as s, mock.patch.object(strategy_lab.db, "init_db"):
            n = strategy_lab.save_zonesweep(results, (zl.VARIANTS[1], "wick_05"), "t")
        calls = {c.args[0]: c.args for c in s.call_args_list}
        self.assertEqual(n, len(zl.VARIANTS) + 2)
        self.assertEqual(set(calls), {v.name.lower() for v in zl.VARIANTS} | {"zone_sweep_stop", "zone_sweep"})
        self.assertTrue(calls["zone_sweep_stop"][1])
        self.assertEqual((calls["zone_sweep_stop"][2]["variant"], calls["zone_sweep_stop"][2]["stop_name"]), ("ZS_2H", "wick_05"))
        self.assertNotIn("range_sweep_stop", calls)


def args(**kw):
    base_args = dict(coins="AAA,BBB", jaren=0.1, kosten=0.12, familie="zonesweep", alleen_volledig=False, opslaan=False, rapport=None, hervat=None,
                     verse_start=False)
    base_args.update(kw)
    return argparse.Namespace(**base_args)


def run(a, ensure, positioning_fn=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        strategy_lab.run_zonesweep(a, ensure=ensure, positioning_fn=positioning_fn or mock.Mock(side_effect=AssertionError("geen OI nodig")))
    return out.getvalue()


class CliTest(unittest.TestCase):
    def lab_protocol(self):
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(strategy_lab.tl, "LAB_COINS", ("AAA", "BBB")))
        stack.enter_context(mock.patch.object(strategy_lab, "coverage_warning", return_value=None))
        return stack

    def test_run_prints_the_register_and_never_asks_for_oi(self):
        oi = mock.Mock()
        text = run(args(), synthetic_ensure(), oi)
        oi.assert_not_called()
        self.assertIn("7 varianten, 14 toetsen", text)
        self.assertIn("78 in het register", text)
        self.assertIn("ZS_2H_MIDDEN", text)
        self.assertRegex(text, r"Stopcriteria: S2 \(geen enkele toets geslaagd\): (ja|nee)")
        self.assertRegex(text, r"Geen variant gekozen|Gekozen voor de proef")

    def test_resume_pins_the_zone_sweep_variants_and_prereg_and_gives_the_same_result(self):
        full = run(args(), synthetic_ensure())
        with tempfile.TemporaryDirectory() as d:
            run(args(hervat=d), synthetic_ensure())
            meta = json.loads((Path(d) / "instellingen.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["varianten"], [v.name for v in zl.VARIANTS])
            self.assertEqual(meta["prereg"], strategy_lab.prereg_hash(strategy_lab.ZS_PREREG))
            self.assertNotEqual(meta["prereg"], strategy_lab.prereg_hash())
            calls = []
            resumed = run(args(hervat=d), synthetic_ensure(calls))
            self.assertEqual(calls, [])
            with self.assertRaises(SystemExit):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    strategy_lab.run_rangesweep(argparse.Namespace(**{**vars(args(hervat=d)), "familie": "rangesweep"}), ensure=synthetic_ensure(),
                                                positioning_fn=mock.Mock(side_effect=RuntimeError))
        self.assertEqual(resumed[resumed.index("Run:"):], full[full.index("Run:"):])

    def test_opslaan_guards(self):
        calls = []
        with self.assertRaises(SystemExit) as cm:
            run(args(kosten=0.06, opslaan=True), synthetic_ensure(calls))
        self.assertIn("zonesweep", str(cm.exception))
        self.assertEqual(calls, [])
        with self.lab_protocol():
            for kw, msg in (({"coins": "AAA"}, "LAB_COINS"), ({"jaren": 1.0}, "--jaren 3"), ({"alleen_volledig": False}, "--alleen-volledig")):
                a = args(opslaan=True, **{"jaren": 3.0, "alleen_volledig": True, **kw})
                with self.subTest(kw), self.assertRaises(SystemExit) as cm:
                    run(a, synthetic_ensure(calls))
                self.assertIn(msg, str(cm.exception))
            self.assertEqual(calls, [])

    def test_opslaan_is_refused_without_a_pass(self):
        with self.lab_protocol(), mock.patch.object(strategy_lab.repo, "set_rule_lab") as s, mock.patch.object(strategy_lab.db, "init_db"):
            with self.assertRaises(SystemExit):
                run(args(opslaan=True, jaren=3.0, alleen_volledig=True), synthetic_ensure())
        s.assert_not_called()

    def test_opslaan_with_a_pass_uses_the_zone_sweep_saver(self):
        choice = (zl.VARIANTS[1], "wick_025")
        with self.lab_protocol(), mock.patch.object(strategy_lab.zl, "select_live", return_value=choice), \
                mock.patch.object(strategy_lab, "save_zonesweep", return_value=9) as save, mock.patch.object(strategy_lab, "save_rangesweep") as other:
            text = run(args(opslaan=True, jaren=3.0, alleen_volledig=True), synthetic_ensure())
        save.assert_called_once()
        other.assert_not_called()
        self.assertEqual(save.call_args.args[1], choice)
        self.assertIn("9 regels opgeslagen", text)

    def test_parser_and_main_dispatch(self):
        self.assertEqual(strategy_lab.build_parser().parse_args(["--familie", "zonesweep"]).familie, "zonesweep")
        with mock.patch.object(sys, "argv", ["strategy_lab.py", "--familie", "zonesweep"]), mock.patch.object(strategy_lab, "run_zonesweep") as rz:
            strategy_lab.main()
        rz.assert_called_once()


if __name__ == "__main__":
    unittest.main()
