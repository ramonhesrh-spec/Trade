import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import strategy_lab  # noqa: E402

from app import track_record  # noqa: E402
from app.replay import rangesweep_lab as rl, stopquality as sq  # noqa: E402


def fake_cell(passes=False, n=10):
    summ = {"setups": 20, "n": n, "fill_rate": 0.5, "cancels": {}, "weeks": 5, "median_stop_pct": 2.4, "median_stop_atr": 1.1, "median_cost_r": 0.05,
            "share_cost_over_01": 0.1, "stop_hit": {"p": 0.5, "ci": (0.4, 0.6)}, "reach": {k: {"p": 0.5 / k, "ci": (0.3 / k, 0.6 / k)} for k in sq.R_LEVELS},
            "median_hours_to_stop": 5.0, "mae_q": [0.2, 0.5, 0.9, 1.0], "mfe_q": [0.3, 0.8, 1.6, 2.4], "tight_rate": 0.2, "halves": (0.5, 0.5),
            "blocks": [0.5] * 6, "ref": {k: {"n": n, "avg_net": -0.05, "ci": (-0.2, 0.1)} for k in sq.REF_NAMES},
            "by_grade": {"A": {"n": n, "reach1": 0.5, "stop_hit": 0.4}}}
    return {"summary": summ, "quality": {"passes": passes, "reason": "" if passes else "faalt: genoeg vullingen (300)", "checks": {}, "placebo_diff": 0.02, "placebo_ci": (-0.03, 0.07)},
            "edge": {"passes": False, "n": n, "avg": -0.05, "t_week": 0.4, "reason": "faalt"}, "doelkans": [{"r": 1, "p_text": "50%", "ci_text": "30 tot 60%", "n": n}]}


def fake_result(v, passes=False):
    return {"zone_0": {"summary": fake_cell()["summary"]}, **{s: fake_cell(passes) for s in v.stops}}


META = {"kosten": 0.12, "jaren": 3.0, "coins": 20, "first": "2023-10-16", "last": "2026-10-15"}


class RangeSweepReportTest(unittest.TestCase):
    def test_markers(self):
        doc = "kop\n<!-- resultaten:begin -->\noud\n<!-- resultaten:end -->\nstaart"
        out = strategy_lab.write_between_markers(doc, "nieuw")
        self.assertIn("<!-- resultaten:begin -->\nnieuw\n<!-- resultaten:end -->", out)
        self.assertTrue(out.startswith("kop") and out.endswith("staart"))
        self.assertEqual(strategy_lab.write_between_markers(out, "nieuw"), out)
        with self.assertRaises(ValueError):
            strategy_lab.write_between_markers("geen markers", "x")

    def test_report_names_the_register_and_every_variant(self):
        md = strategy_lab.render_rangesweep([(v, fake_result(v)) for v in rl.VARIANTS], META)
        self.assertIn("30 toetsen in deze familie, 64 in het register", md)
        for v in rl.VARIANTS:
            self.assertIn(v.name, md)
        self.assertIn("+1R vóór de stop", md)
        self.assertIn("+6R", md)
        self.assertIn("geen enkele toets slaagt", md)

    def test_report_marks_a_passing_test(self):
        results = [(v, fake_result(v, passes=(v.name == "RS_1H"))) for v in rl.VARIANTS]
        md = strategy_lab.render_rangesweep(results, META)
        self.assertIn("2 van 30 toetsen slagen", md)
        self.assertNotIn("geen enkele toets slaagt", md)

    def test_report_prints_the_stop_criteria_s2_and_s3(self):
        md = strategy_lab.render_rangesweep([(v, fake_result(v)) for v in rl.VARIANTS], META)
        self.assertIn("S2 (geen enkele toets geslaagd): ja", md)
        self.assertIn("S3 (mediane kosten boven 0,10R bij alle toetsen): nee", md)
        results = [(v, fake_result(v, passes=(v.name == "RS_1H"))) for v in rl.VARIANTS]
        self.assertIn("S2 (geen enkele toets geslaagd): nee", strategy_lab.render_rangesweep(results, META))
        costly = [(v, fake_result(v)) for v in rl.VARIANTS]
        for _, r in costly:
            for name in _.stops:
                r[name]["summary"]["median_cost_r"] = 0.2
        self.assertIn("S3 (mediane kosten boven 0,10R bij alle toetsen): ja", strategy_lab.render_rangesweep(costly, META))

    def test_report_says_when_the_stop_criteria_cannot_be_judged(self):
        md = strategy_lab.render_rangesweep([(rl.VARIANTS[0], fake_result(rl.VARIANTS[0]))], META)
        self.assertIn("S2 en S3 niet beoordeeld: 2 van 30 toetsen", md)

    def test_report_copes_with_variants_without_fills(self):
        empty = {"zone_0": {"summary": {"setups": 0, "n": 0}}, **{s: {"summary": {"setups": 0, "n": 0}, "quality": {"passes": False}, "edge": {}, "doelkans": []} for s in rl.VARIANTS[0].stops}}
        md = strategy_lab.render_rangesweep([(rl.VARIANTS[0], empty)], META)
        self.assertIn("geen vullingen", md)

    def test_save_refuses_low_costs(self):
        with self.assertRaises(SystemExit):
            strategy_lab.check_rangesweep_costs(0.06, opslaan=True)
        strategy_lab.check_rangesweep_costs(0.06, opslaan=False)
        strategy_lab.check_rangesweep_costs(0.12, opslaan=True)

    def test_save_refuses_without_a_pass(self):
        with self.assertRaises(SystemExit):
            strategy_lab.check_rangesweep_verdict(None, opslaan=True)
        strategy_lab.check_rangesweep_verdict(None, opslaan=False)
        strategy_lab.check_rangesweep_verdict((rl.VARIANTS[0], "zone_025"), opslaan=True)

    def test_save_writes_variant_rows_and_the_two_live_rows(self):
        with mock.patch.object(strategy_lab.repo, "set_rule_lab") as s, mock.patch.object(strategy_lab.db, "init_db"):
            n = strategy_lab.save_rangesweep([(v, fake_result(v)) for v in rl.VARIANTS], None, "2026-10-16T00:00:00+00:00")
        keys = [c.args[0] for c in s.call_args_list]
        self.assertEqual(n, len(rl.VARIANTS) + 2)
        self.assertIn("range_sweep_stop", keys)
        self.assertFalse(next(c for c in s.call_args_list if c.args[0] == "range_sweep_stop").args[1])

    def test_save_with_a_choice_stores_quality_and_target_odds(self):
        results = [(v, fake_result(v, passes=True)) for v in rl.VARIANTS]
        with mock.patch.object(strategy_lab.repo, "set_rule_lab") as s, mock.patch.object(strategy_lab.db, "init_db"):
            strategy_lab.save_rangesweep(results, (rl.VARIANTS[9], "zone_025"), "t")
        calls = {c.args[0]: c.args for c in s.call_args_list}
        self.assertTrue(calls["range_sweep_stop"][1])
        self.assertEqual(calls["range_sweep_stop"][2]["variant"], "RS_1H")
        self.assertIn("doelkans", calls["range_sweep_stop"][2])
        self.assertFalse(calls["range_sweep"][1])

    def test_save_into_a_real_database(self):
        from app import config, repo
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "DATABASE_PATH", str(Path(d) / "t.db")):
            results = [(v, fake_result(v, passes=True)) for v in rl.VARIANTS]
            strategy_lab.save_rangesweep(results, (rl.VARIANTS[9], "zone_025"), "2026-10-16T00:00:00+00:00")
            self.assertTrue(repo.get_rule_lab("range_sweep_stop")["lab_passes"])
            self.assertIn("rs_1h", {r["rule"] for r in repo.list_rule_labs()})

    def test_labels(self):
        self.assertEqual(track_record.TYPE_LABELS["range_sweep"], "Range sweep (ongetest)")
        for v in rl.VARIANTS:
            self.assertIn(v.name.lower(), track_record.LAB_LABELS)
        self.assertIn("range_sweep_stop", track_record.LAB_LABELS)

    def test_resume_paths_per_coin(self):
        with tempfile.TemporaryDirectory() as d:
            rows, plac = strategy_lab.coin_part_paths(Path(d), "ARB")
            self.assertEqual((rows.name, plac.name), ("ARB_rows.pkl", "ARB_placebo.pkl"))


def synthetic_ensure(calls=None, fail_on=None):
    """Een lader met kunstmatige candles per coin (willekeurige wandeling met vaste seed), de naad voor de CLI-tests: geen beurs, geen schijf."""
    def ensure(coin, years, timeframe="1h"):
        if calls is not None:
            calls.append((coin, timeframe))
        if fail_on == coin:
            raise KeyboardInterrupt("onderbroken")
        n = 4000
        rng = np.random.default_rng(sum(map(ord, coin)))
        close = 100 + np.cumsum(rng.normal(0, 0.3, n))
        open_ = np.concatenate([[100.0], close[:-1]])
        b15 = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"), "open": open_,
                            "high": np.maximum(open_, close) + rng.uniform(0, 0.2, n), "low": np.minimum(open_, close) - rng.uniform(0, 0.2, n),
                            "close": close, "volume": 1.0})
        if timeframe == "15m":
            return b15
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        return b15.set_index("timestamp").resample(timeframe, origin="epoch").agg(agg).dropna().reset_index()
    return ensure


def no_oi(coin, start, end):
    raise RuntimeError("geen OI in de test")


def args(**kw):
    base = dict(coins="AAA,BBB,CCC", jaren=0.1, kosten=0.12, familie="rangesweep", alleen_volledig=False, opslaan=False, rapport=None, hervat=None, verse_start=False)
    base.update(kw)
    return argparse.Namespace(**base)


def run(a, ensure, last_15m=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        strategy_lab.run_rangesweep(a, ensure=ensure, positioning_fn=no_oi, **({"last_15m": last_15m} if last_15m else {}))
    return out.getvalue()


def result_lines(text):
    """De uitkomst zonder de voortgangsregels per coin (die verschillen bij een hervatte run)."""
    return text[text.index("Run:"):]


class RangeSweepCliTest(unittest.TestCase):
    def test_run_prints_the_number_of_tests_and_the_verdict(self):
        text = run(args(), synthetic_ensure())
        self.assertIn("30 toetsen in deze familie, 64 in het register", text)
        self.assertIn("15 varianten", text)
        self.assertRegex(text, r"Geen variant gekozen|Gekozen voor de proef")
        self.assertRegex(text, r"Stopcriteria: S2 \(geen enkele toets geslaagd\): (ja|nee)")

    def test_resume_gives_the_same_result_as_an_uninterrupted_run(self):
        full = run(args(), synthetic_ensure())
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(KeyboardInterrupt):
                run(args(hervat=d), synthetic_ensure(fail_on="CCC"))
            self.assertEqual(sorted(p.name for p in Path(d).glob("*.pkl")), ["AAA_placebo.pkl", "AAA_rows.pkl", "BBB_placebo.pkl", "BBB_rows.pkl"])
            calls = []
            resumed = run(args(hervat=d), synthetic_ensure(calls))
            self.assertEqual({c for c, _ in calls}, {"CCC"})
            self.assertIn("uit ", resumed)
            again = run(args(hervat=d), synthetic_ensure(calls := []))
            self.assertEqual(calls, [])
        self.assertEqual(result_lines(resumed), result_lines(full))
        self.assertEqual(result_lines(again), result_lines(full))

    def test_resume_refuses_a_directory_from_other_settings(self):
        with tempfile.TemporaryDirectory() as d:
            run(args(hervat=d, coins="AAA"), synthetic_ensure())
            with self.assertRaises(SystemExit):
                run(args(hervat=d, coins="AAA", kosten=0.16), synthetic_ensure())

    def test_state_file_pins_code_prereg_placebo_and_last_candle(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(strategy_lab, "git_head", return_value="abc1234"):
            run(args(hervat=d, coins="AAA"), synthetic_ensure())
            meta = json.loads((Path(d) / "instellingen.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["git"], meta["placebo_draws"], meta["placebo_seed"]), ("abc1234", rl.PLACEBO_DRAWS, rl.PLACEBO_SEED))
        self.assertRegex(meta["prereg"], r"^[0-9a-f]{64}$")
        self.assertEqual(list(meta["laatste_15m"]), ["AAA"])
        self.assertTrue(meta["laatste_15m"]["AAA"].startswith("2024-02-11"))

    def test_resume_refuses_other_code_prereg_or_placebo_settings(self):
        changes = [("git_head", {"return_value": "def5678"}, "git"), ("prereg_hash", {"return_value": "0" * 64}, "prereg"),
                   (None, {"attr": "PLACEBO_DRAWS", "new": 5}, "placebo_draws"), (None, {"attr": "PLACEBO_SEED", "new": 8}, "placebo_seed")]
        for fn, kw, key in changes:
            with self.subTest(key), tempfile.TemporaryDirectory() as d:
                with mock.patch.object(strategy_lab, "git_head", return_value="abc1234"):
                    run(args(hervat=d, coins="AAA"), synthetic_ensure())
                with contextlib.ExitStack() as stack:
                    stack.enter_context(mock.patch.object(strategy_lab, "git_head", return_value="abc1234"))
                    stack.enter_context(mock.patch.object(strategy_lab, fn, **kw) if fn else mock.patch.object(strategy_lab.rl, kw["attr"], kw["new"]))
                    with self.assertRaises(SystemExit) as cm:
                        run(args(hervat=d, coins="AAA"), synthetic_ensure())
                self.assertIn(key, str(cm.exception))
                self.assertIn("--verse-start", str(cm.exception))

    def test_unknown_git_head_does_not_block_a_resume(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(strategy_lab, "git_head", return_value="abc1234"):
                run(args(hervat=d, coins="AAA"), synthetic_ensure())
            with mock.patch.object(strategy_lab, "git_head", return_value=None):
                run(args(hervat=d, coins="AAA"), synthetic_ensure())

    def test_resume_refuses_a_part_when_the_candle_cache_moved_on(self):
        with tempfile.TemporaryDirectory() as d:
            run(args(hervat=d, coins="AAA"), synthetic_ensure())
            with self.assertRaises(SystemExit) as cm:
                run(args(hervat=d, coins="AAA"), synthetic_ensure(), last_15m=lambda c: pd.Timestamp("2030-01-01", tz="UTC"))
            self.assertIn("AAA", str(cm.exception))
            self.assertIn("--verse-start", str(cm.exception))
            same = synthetic_ensure()("AAA", 1, timeframe="15m")["timestamp"].iloc[-1]
            run(args(hervat=d, coins="AAA"), synthetic_ensure(), last_15m=lambda c: same)

    def test_verse_start_wipes_the_state_and_recomputes(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(strategy_lab, "git_head", return_value="abc1234"):
                run(args(hervat=d, coins="AAA"), synthetic_ensure())
            calls = []
            with mock.patch.object(strategy_lab, "git_head", return_value="def5678"):
                run(args(hervat=d, coins="AAA", verse_start=True), synthetic_ensure(calls))
            self.assertTrue(calls)
            self.assertEqual(json.loads((Path(d) / "instellingen.json").read_text(encoding="utf-8"))["git"], "def5678")

    def test_verse_start_needs_hervat(self):
        with self.assertRaises(SystemExit):
            run(args(verse_start=True), synthetic_ensure())

    def test_corrupt_part_is_recomputed(self):
        with tempfile.TemporaryDirectory() as d:
            full = run(args(hervat=d, coins="AAA"), synthetic_ensure())
            (Path(d) / "AAA_rows.pkl").write_bytes(b"kapot")
            again = run(args(hervat=d, coins="AAA"), synthetic_ensure())
        self.assertEqual(result_lines(again), result_lines(full))

    def test_no_stray_temp_files_after_a_run(self):
        with tempfile.TemporaryDirectory() as d:
            run(args(hervat=d, coins="AAA"), synthetic_ensure())
            self.assertEqual([p.name for p in Path(d).iterdir() if p.suffix == ".tmp"], [])

    def test_report_fills_only_between_the_markers(self):
        doc = "voor\n<!-- resultaten:begin -->\n(nog geen run)\n<!-- resultaten:end -->\nna\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.md"
            p.write_text(doc, encoding="utf-8")
            run(args(coins="AAA", rapport=str(p)), synthetic_ensure())
            out = p.read_text(encoding="utf-8")
        self.assertTrue(out.startswith("voor\n<!-- resultaten:begin -->\n") and out.endswith("<!-- resultaten:end -->\nna\n"))
        self.assertIn("30 toetsen", out)
        self.assertNotIn("nog geen run", out)

    def test_report_without_markers_fails_before_the_long_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.md"
            p.write_text("geen markers", encoding="utf-8")
            calls = []
            with self.assertRaises(SystemExit):
                run(args(rapport=str(p)), synthetic_ensure(calls))
            self.assertEqual(calls, [])

    def lab_protocol(self):
        """De drie coins van de test spelen de 20 van het lab, de korte synthetische cache telt als drie jaar: alleen het opslaan-pad wordt zo getoetst."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(strategy_lab.tl, "LAB_COINS", ("AAA", "BBB", "CCC")))
        stack.enter_context(mock.patch.object(strategy_lab, "coverage_warning", return_value=None))
        return stack

    def test_opslaan_is_refused_without_a_pass_and_writes_nothing(self):
        with self.lab_protocol(), mock.patch.object(strategy_lab.repo, "set_rule_lab") as s, mock.patch.object(strategy_lab.db, "init_db"):
            with self.assertRaises(SystemExit):
                run(args(opslaan=True, jaren=3.0, alleen_volledig=True), synthetic_ensure())
        s.assert_not_called()

    def test_opslaan_with_low_costs_stops_before_loading(self):
        calls = []
        with self.assertRaises(SystemExit):
            run(args(kosten=0.06, opslaan=True), synthetic_ensure(calls))
        self.assertEqual(calls, [])

    def test_opslaan_saves_when_the_verdict_is_a_pass(self):
        choice = (rl.VARIANTS[9], "zone_025")
        with self.lab_protocol(), mock.patch.object(strategy_lab.rl, "select_live", return_value=choice), \
                mock.patch.object(strategy_lab, "save_rangesweep", return_value=17) as save:
            text = run(args(opslaan=True, jaren=3.0, alleen_volledig=True), synthetic_ensure())
        save.assert_called_once()
        self.assertEqual(save.call_args.args[1], choice)
        self.assertIn("17 regels opgeslagen", text)

    def test_opslaan_refuses_a_subset_of_the_lab_coins_before_loading(self):
        calls = []
        with self.lab_protocol(), self.assertRaises(SystemExit) as cm:
            run(args(coins="AAA,BBB", opslaan=True, jaren=3.0, alleen_volledig=True), synthetic_ensure(calls))
        self.assertIn("LAB_COINS", str(cm.exception))
        self.assertEqual(calls, [])

    def test_opslaan_refuses_other_years_and_missing_alleen_volledig(self):
        for kw in ({"jaren": 1.0, "alleen_volledig": True}, {"jaren": 3.0, "alleen_volledig": False}):
            with self.lab_protocol(), self.assertRaises(SystemExit) as cm:
                strategy_lab.check_rangesweep_protocol(args(opslaan=True, **kw))
            self.assertRegex(str(cm.exception), r"--jaren 3|--alleen-volledig")
        with self.lab_protocol():
            strategy_lab.check_rangesweep_protocol(args(opslaan=True, jaren=3.0, alleen_volledig=True, coins="CCC,AAA,BBB"))
            strategy_lab.check_rangesweep_protocol(args(opslaan=False, coins="AAA"))

    def test_opslaan_refuses_duplicated_coins(self):
        with self.lab_protocol(), self.assertRaises(SystemExit):
            strategy_lab.check_rangesweep_protocol(args(opslaan=True, jaren=3.0, alleen_volledig=True, coins="AAA,AAA,BBB,CCC"))

    def test_state_file_pins_coins_years_and_alleen_volledig(self):
        with tempfile.TemporaryDirectory() as d:
            run(args(hervat=d, coins="AAA"), synthetic_ensure())
            meta = json.loads((Path(d) / "instellingen.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["coins"], meta["jaren"], meta["alleen_volledig"]), (["AAA"], 0.1, False))
            with self.assertRaises(SystemExit):
                run(args(hervat=d, coins="AAA,BBB"), synthetic_ensure())
            with self.assertRaises(SystemExit):
                run(args(hervat=d, coins="AAA", alleen_volledig=True), synthetic_ensure())

    def test_short_cache_stops_the_run_with_a_clear_message(self):
        # De synthetische cache dekt ~42 dagen terwijl een jaar gevraagd wordt: de situatie van een galerij-run met 1 jaar voor de lab-run met 3.
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            strategy_lab.run_rangesweep(args(coins="AAA", jaren=1.0), ensure=synthetic_ensure(), positioning_fn=no_oi)
        self.assertIn("AAA", str(cm.exception))
        self.assertIn("dekt maar", str(cm.exception))
        self.assertIn("refresh", str(cm.exception))

    def test_short_cache_is_caught_before_alleen_volledig_drops_coins(self):
        calls = []
        with self.assertRaises(SystemExit) as cm:
            run(args(coins="AAA,BBB", jaren=1.0, alleen_volledig=True), synthetic_ensure(calls))
        self.assertIn("dekt maar", str(cm.exception))
        self.assertEqual({t for _, t in calls}, {"15m"})

    def test_cache_that_covers_the_request_runs(self):
        self.assertIn("15 varianten", run(args(coins="AAA", jaren=0.1), synthetic_ensure()))

    def test_check_coverage_names_every_short_timeframe(self):
        ens = synthetic_ensure()
        frames = {tf: ens("AAA", 1, timeframe=tf) for tf in ("15m", "1h", "4h")}
        with self.assertRaises(SystemExit) as cm:
            strategy_lab.check_coverage("AAA", frames, 1.0)
        self.assertTrue(all(tf in str(cm.exception) for tf in ("15m", "1h", "4h")))
        strategy_lab.check_coverage("AAA", frames, 0.1)

    def test_other_families_still_parse(self):
        parser = strategy_lab.build_parser()
        for f in ("alle", "kanteling", "standaard", "rangesweep"):
            self.assertEqual(parser.parse_args(["--familie", f]).familie, f)
        a = parser.parse_args(["--familie", "rangesweep", "--hervat", "x", "--rapport", "y.md", "--opslaan", "--alleen-volledig"])
        self.assertEqual((a.hervat, a.rapport, a.opslaan, a.alleen_volledig), ("x", "y.md", True, True))
        self.assertEqual(len(strategy_lab.select_variants("alle")), 20)


if __name__ == "__main__":
    unittest.main()
