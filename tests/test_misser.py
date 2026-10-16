import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import misser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import misser_check                                                     # noqa: E402

HEAD = "coin,richting,tijd,instap,stop,doel,uitkomst\n"


class ParseRowsTest(unittest.TestCase):
    def test_valid_rows_become_utc(self):
        rows = misser.parse_rows(HEAD + "BTC,long,2026-10-08 14:30,100,95,115,winst\n")
        self.assertEqual(rows[0]["coin"], "BTC")
        self.assertEqual(rows[0]["direction"], "long")
        self.assertEqual(rows[0]["at"].isoformat(), "2026-10-08T12:30:00+00:00")   # CEST is UTC+2
        self.assertEqual((rows[0]["entry"], rows[0]["stop"], rows[0]["target"], rows[0]["outcome"]), (100.0, 95.0, 115.0, "winst"))

    def test_winter_time_and_comma_decimal_and_blank_lines(self):
        rows = misser.parse_rows(HEAD + "\neth,SHORT,2026-12-01 10:00,\"86558,4\",\"86742,5\",83928.2,verlies\n\n")
        self.assertEqual(rows[0]["coin"], "ETH")
        self.assertEqual(rows[0]["direction"], "short")
        self.assertEqual(rows[0]["at"].isoformat(), "2026-12-01T09:00:00+00:00")
        self.assertEqual(rows[0]["entry"], 86558.4)

    def test_ambiguous_time_takes_first_occurrence(self):
        rows = misser.parse_rows(HEAD + "BTC,long,2026-10-25 02:30,1,0.5,2,x\n")
        self.assertEqual(rows[0]["at"].isoformat(), "2026-10-25T00:30:00+00:00")   # CEST, de eerste keer

    def test_nonexistent_time_names_the_line(self):
        with self.assertRaisesRegex(ValueError, "regel 2"):
            misser.parse_rows(HEAD + "BTC,long,2026-03-29 02:30,1,0.5,2,x\n")

    def test_bad_direction_names_the_line(self):
        with self.assertRaisesRegex(ValueError, "regel 2"):
            misser.parse_rows(HEAD + "BTC,omhoog,2026-10-08 14:30,100,95,115,winst\n")

    def test_line_number_counts_blank_lines_and_header(self):
        text = HEAD + "BTC,long,2026-10-08 14:30,100,95,115,winst\n\nBTC,long,2026-10-08 14:30,abc,95,115,winst\n"
        with self.assertRaisesRegex(ValueError, "regel 4"):
            misser.parse_rows(text)

    def test_bad_time_and_wrong_field_count(self):
        with self.assertRaisesRegex(ValueError, "regel 2"):
            misser.parse_rows(HEAD + "BTC,long,08-10-2026 14:30,100,95,115,winst\n")
        with self.assertRaisesRegex(ValueError, "regel 2"):
            misser.parse_rows(HEAD + "BTC,long,2026-10-08 14:30,100,95\n")

    def test_missing_column_in_header(self):
        with self.assertRaisesRegex(ValueError, "doel"):
            misser.parse_rows("coin,richting,tijd,instap,stop,uitkomst\nBTC,long,2026-10-08 14:30,1,2,x\n")

    def test_empty_text_has_no_header(self):
        with self.assertRaises(ValueError):
            misser.parse_rows("\n\n")

    def test_empty_stop_and_target_become_none(self):
        rows = misser.parse_rows(HEAD + "DOGE,short,2026-10-15 17:20,0.199,,,\n")
        self.assertIsNone(rows[0]["stop"])
        self.assertIsNone(rows[0]["target"])
        self.assertEqual(rows[0]["entry"], 0.199)

    def test_extra_columns_are_kept(self):
        text = "coin,richting,tijd,instap,stop,doel,uitkomst,bron,notitie,tf\nARB,short,2026-10-16 17:52,0.19903,0.20446,0.16254,,arb.webp,top,2h\n"
        r = misser.parse_rows(text)[0]
        self.assertEqual((r["source"], r["note"], r["tf"]), ("arb.webp", "top", "2h"))

    def test_missing_extra_columns_are_empty(self):
        r = misser.parse_rows(HEAD + "BTC,long,2026-10-08 14:30,100,95,115,winst\n")[0]
        self.assertEqual((r["source"], r["note"], r["tf"]), ("", "", ""))

    def test_bad_tf_names_the_line(self):
        text = "coin,richting,tijd,instap,stop,doel,uitkomst,tf\nBTC,long,2026-10-08 14:30,100,,,,3h\n"
        with self.assertRaisesRegex(ValueError, "regel 2: tf"):
            misser.parse_rows(text)

    def test_seed_csv_parses(self):
        rows = misser.parse_rows((ROOT / "docs" / "onderzoek" / "range-sweep" / "handtrades.csv").read_text(encoding="utf-8"))
        self.assertEqual([r["coin"] for r in rows], ["ARB", "APT", "APT", "WLD", "AAVE"])
        self.assertEqual(rows[4]["at"].isoformat(), "2026-10-15T21:42:00+00:00")
        self.assertEqual({r["tf"] for r in rows}, {"30m", "1h", "2h"})


class CsvFormatTest(unittest.TestCase):
    def test_bom_header(self):
        rows = misser.parse_rows("\ufeff" + HEAD + "BTC,long,2026-10-08 14:30,100,95,115,winst\n")
        self.assertEqual(rows[0]["coin"], "BTC")

    def test_semicolon_file_with_comma_decimals(self):
        text = HEAD.replace(",", ";") + "BTC;short;2026-10-08 02:30;86558,4;86742,5;83928,2;winst\n"
        rows = misser.parse_rows(text)
        self.assertEqual((rows[0]["entry"], rows[0]["stop"], rows[0]["target"]), (86558.4, 86742.5, 83928.2))

    def test_comma_file_with_dot_decimals_and_trailing_empty_cells(self):
        rows = misser.parse_rows(HEAD + "BTC,long,2026-10-08 14:30,100.5,95,115,winst,,\n")
        self.assertEqual(rows[0]["entry"], 100.5)

    def test_unquoted_comma_decimal_in_comma_file_is_an_error_with_line(self):
        with self.assertRaisesRegex(ValueError, "regel 2.*velden"):
            misser.parse_rows(HEAD + "BTC,long,2026-10-08 14:30,100,5,95,115,winst\n")

    def test_duplicate_header_name(self):
        with self.assertRaisesRegex(ValueError, "regel 1.*dubbel"):
            misser.parse_rows(HEAD.strip() + ",stop\nBTC,long,2026-10-08 14:30,1,2,3,x,4\n")


class SummarizeTest(unittest.TestCase):
    def test_summarize_counts_seen_and_blockers(self):
        out = misser.summarize([{"engines": ["structuur"], "blocker": None}, {"engines": [], "blocker": "stop te krap"}, {"engines": [], "blocker": "stop te krap"}])
        self.assertEqual(out["n"], 3)
        self.assertEqual(out["seen"], 1)
        self.assertEqual(out["by_engine"], {"structuur": 1})
        self.assertEqual(out["by_blocker"], {"stop te krap": 2})

    def test_blocker_ignored_when_an_engine_saw_it_and_empty_input(self):
        out = misser.summarize([{"engines": ["rejectie", "structuur"], "blocker": "x"}])
        self.assertEqual(out["by_engine"], {"rejectie": 1, "structuur": 1})
        self.assertEqual(out["by_blocker"], {})
        self.assertEqual(misser.summarize([]), {"n": 0, "seen": 0, "by_engine": {}, "by_blocker": {}})


def _bars(n=30):
    ts = pd.date_range("2026-10-01", periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0})


def _empty(cols):
    return pd.DataFrame({c: [] for c in cols})


class JudgeTest(unittest.TestCase):
    """judge() is zuiver gegeven de frame; de detectors worden vervangen door vaste uitkomsten zodat elk etiket gericht te raken is."""

    def judge(self, diag=None, rej_rows=None, plan=None, breaks=None, direction="short"):
        rej = pd.DataFrame(rej_rows) if rej_rows else _empty(["direction", "bar"])
        brk = pd.DataFrame(breaks) if breaks else _empty(["direction", "bar"])
        with mock.patch.object(misser_check.rj, "find_rejections", return_value=rej), \
             mock.patch.object(misser_check.rj, "plan_for", return_value=plan), \
             mock.patch.object(misser_check.rj, "diagnose", return_value=diag), \
             mock.patch.object(misser_check.br, "find_breaks", return_value=brk):
            return misser_check.judge(_bars(), 20, direction)

    GOOD = {"atr": 1.0, "touches": 3, "level": 100.0, "gap_to_level_atr": 0.0, "close_from_level_atr": 0.5, "bearish": True}

    def test_rejection_with_plan_is_seen(self):
        r = self.judge(rej_rows=[{"direction": "short", "bar": 19, "level": 100.0, "touches": 3}], plan={"entry": 1})
        self.assertEqual((r["engines"], r["blocker"]), (["rejectie"], None))

    def test_structure_break_is_seen(self):
        r = self.judge(diag=self.GOOD, breaks=[{"direction": "short", "bar": 18}])
        self.assertEqual((r["engines"], r["blocker"]), (["structuur"], None))

    def test_plan_dropped(self):
        r = self.judge(rej_rows=[{"direction": "short", "bar": 19, "level": 100.0, "touches": 3}], plan=None)
        self.assertEqual((r["engines"], r["blocker"]), ([], "rejectie: plan viel af (stop te ver)"))

    def test_nan_atr(self):
        self.assertEqual(self.judge(diag={**self.GOOD, "atr": float("nan")})["blocker"], "rejectie: te weinig candles voor de ATR")

    def test_too_few_touches_and_no_level(self):
        self.assertIn("te weinig aanrakingen", self.judge(diag={**self.GOOD, "touches": 2})["blocker"])
        self.assertIn("te weinig aanrakingen", self.judge(diag={"atr": 1.0, "touches": 0, "level": None})["blocker"])

    def test_gap_too_far(self):
        self.assertEqual(self.judge(diag={**self.GOOD, "gap_to_level_atr": 0.5})["blocker"], "rejectie: prik te ver van het niveau")

    def test_close_too_near(self):
        self.assertEqual(self.judge(diag={**self.GOOD, "close_from_level_atr": 0.1})["blocker"], "rejectie: slot te dicht bij het niveau")

    def test_wrong_colour_long_and_short(self):
        self.assertEqual(self.judge(diag={**self.GOOD, "bearish": False})["blocker"], "rejectie: candle heeft de verkeerde kleur voor de richting")
        bull = {k: v for k, v in self.GOOD.items() if k != "bearish"}
        self.assertEqual(self.judge(diag={**bull, "bullish": False}, direction="long")["blocker"], "rejectie: candle heeft de verkeerde kleur voor de richting")

    def test_neutral_fallback_when_everything_passes(self):
        self.assertEqual(self.judge(diag=self.GOOD)["blocker"], "rejectie: geen oorzaak aan te wijzen op de instapcandle")

    def test_real_detectors_on_flat_bars_do_not_crash(self):
        r = misser_check.judge(_bars(60), 40, "short")
        self.assertEqual(r["engines"], [])
        self.assertTrue(r["blocker"].startswith("rejectie:"))


class RunCsvTest(unittest.TestCase):
    def test_fetch_failure_uses_fixed_blocker_and_row_text(self):
        def boom(coin, at):
            raise RuntimeError("geen verbinding")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.csv"
            f.write_text(HEAD + "BTC,long,2026-10-08 14:30,1,0.9,1.3,x\nETH,long,2026-10-08 15:30,1,0.9,1.3,x\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                s = misser_check.run_csv(str(f), False, fetch=boom)
        self.assertEqual(s["by_blocker"], {"geen data": 2})
        self.assertIn("(geen verbinding)", out.getvalue())

    def test_csv_with_coin_exits_2(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "misser_check.py"), "--csv", "x.csv", "--coin", "BTC"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_bom_file_is_read_through_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.csv"
            f.write_bytes(b"\xef\xbb\xbf" + (HEAD + "BTC,long,2026-10-08 14:30,1,0.9,1.3,x\n").encode())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                misser_check.run_csv(str(f), True)
        self.assertIn("1 rijen gelezen", out.getvalue())


class RangeSweepJudgeTest(unittest.TestCase):
    def frames(self):
        from app.replay import rangesweep as rs
        from tests.replay.rangesweep_fixtures import frames
        b15, b1h, b4h = frames()
        return rs.build_frames(b15, b1h, b4h), b1h

    def test_fixture_short_zone_retest_is_seen_without_htf(self):
        from tests.replay.rangesweep_fixtures import FIRST_SHORT_ZONE_SETUP_HOUR
        f, b1h = self.frames()
        at = b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)
        r = misser_check.judge_rangesweep(f, at, "short", tf_hint="1h")
        self.assertIn("range_sweep:RZ_1H_ZONDERHTF", r["engines"])
        self.assertTrue(all("_1H" in k for k in r["per_variant"]))

    def test_fixture_sweep_is_seen(self):
        from tests.replay.rangesweep_fixtures import SWEEP_HOUR
        f, b1h = self.frames()
        at = b1h["timestamp"].iloc[SWEEP_HOUR] + pd.Timedelta(hours=1)
        self.assertIn("range_sweep:RS_1H_ZONDERHTF", misser_check.judge_rangesweep(f, at, "short")["engines"])

    def test_blocker_is_the_reason_of_the_furthest_variant(self):
        f, b1h = self.frames()
        r = misser_check.judge_rangesweep(f, b1h["timestamp"].iloc[30], "short")
        self.assertEqual(r["engines"], [])
        self.assertTrue(r["blocker"].startswith("range_sweep: "))

    def test_only_without_htf_is_flagged_and_the_blocker_prefers_the_deepest_stage(self):
        self.assertTrue(misser_check._stage("geen geldige limiet: x") > misser_check._stage("HTF-filter: x") > misser_check._stage("range op 1h gevonden, maar x")
                        > misser_check._stage("geen range op 1h: te weinig candles"))
        self.assertEqual(misser_check._stage("iets onbekends"), 0)

    def test_every_diag_only_name_is_a_without_htf_twin(self):
        names = [c[0] for c in misser_check.RS_COMBOS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n.endswith("_ZONDERHTF") and not c[4] for c in misser_check.RS_DIAG_ONLY for n in (c[0],)))
        self.assertFalse({c[0] for c in misser_check.RS_DIAG_ONLY} & set(names))

    def test_price_far_from_the_setup_is_not_seen(self):
        from tests.replay.rangesweep_fixtures import FIRST_SHORT_ZONE_SETUP_HOUR
        f, b1h = self.frames()
        at = b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)
        r = misser_check.judge_rangesweep(f, at, "short", tf_hint="1h", price=50.0)
        self.assertEqual(r["engines"], [])


class CandleCacheTest(unittest.TestCase):
    def test_cache_fetch_reads_the_csv_per_coin_and_timeframe_and_honours_since_and_limit(self):
        with tempfile.TemporaryDirectory() as d:
            ts = pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC")
            pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}).to_csv(Path(d) / "ARB_1h.csv", index=False)
            fetch = misser_check.cache_fetch(d)
            df = fetch("arb", timeframe="1h", limit=3, since=int(ts[4].timestamp() * 1000))
            self.assertEqual(list(df["timestamp"]), list(ts[4:7]))
            with self.assertRaises(FileNotFoundError):
                fetch("ARB", timeframe="4h", limit=3, since=0)

    def test_fetch_rangesweep_builds_all_four_frames_from_an_injected_source(self):
        from tests.replay.rangesweep_fixtures import frames
        b15, b1h, b4h = frames()
        src = {"15m": b15, "1h": b1h, "4h": b4h}
        calls = []

        def fetch(coin, timeframe, limit, since):
            calls.append(timeframe)
            return src[timeframe][src[timeframe]["timestamp"] >= pd.Timestamp(since, unit="ms", tz="UTC")]
        f = misser_check.fetch_rangesweep("ARB", b1h["timestamp"].iloc[150], fetch=fetch)
        self.assertEqual(sorted(calls), ["15m", "1h", "4h"])
        self.assertEqual(set(f), {"15m", "30m", "1h", "2h", "4h"})
        self.assertLessEqual(f["15m"]["timestamp"].max(), b1h["timestamp"].iloc[150] + pd.Timedelta(hours=14))


class RunCsvRangeSweepTest(unittest.TestCase):
    def test_motor_rangesweep_prints_per_variant_lines_and_counts_seen(self):
        from app.replay import rangesweep as rs
        from tests.replay.rangesweep_fixtures import frames, FIRST_SHORT_ZONE_SETUP_HOUR, START
        b15, b1h, b4h = frames()
        fr = rs.build_frames(b15, b1h, b4h)
        at_utc = START + pd.Timedelta(hours=FIRST_SHORT_ZONE_SETUP_HOUR + 1)
        local = at_utc.tz_convert("Europe/Amsterdam").strftime("%Y-%m-%d %H:%M")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.csv"
            f.write_text(HEAD.strip() + ",bron,notitie,tf\n" + f"ARB,short,{local},105.4,106.4,100,,x.webp,n,1h\n" + f"ARB,short,{local},105.4,106.4,100,,y.webp,n,4h\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                s = misser_check.run_csv(str(f), False, motor="rangesweep", window_hours=12, fetch_rs=lambda coin, at: fr)
        text = out.getvalue()
        self.assertIn("RZ_1H_ZONDERHTF: gezien", text)
        self.assertIn("RZ_1H: ", text)
        self.assertEqual(s["n"], 2)
        self.assertGreaterEqual(s["seen"], 1)

    def test_motor_rangesweep_fetch_failure_is_geen_data(self):
        def boom(coin, at):
            raise RuntimeError("geen verbinding")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.csv"
            f.write_text(HEAD + "BTC,long,2026-10-08 14:30,1,0.9,1.3,x\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                s = misser_check.run_csv(str(f), False, motor="rangesweep", fetch_rs=boom)
        self.assertEqual(s["by_blocker"], {"geen data": 1})


class DraftRowsTest(unittest.TestCase):
    def test_draft_takes_coin_direction_time_and_first_price(self):
        msgs = [{"id": 7, "received_at": "2026-10-15T15:28:00+00:00", "raw_text": "Entry was up top 0.19900 Now 0.19550", "coin": "ARB", "direction": "short"}]
        r = misser.draft_rows(msgs)[0]
        self.assertEqual((r["coin"], r["richting"], r["tijd"], r["instap"]), ("ARB", "short", "2026-10-15 17:28", "0.199"))
        self.assertEqual(r["bron"], "bericht 7")

    def test_draft_skips_messages_without_coin_or_direction(self):
        self.assertEqual(misser.draft_rows([{"id": 1, "received_at": "2026-10-15T15:28:00+00:00", "raw_text": "gm", "coin": None, "direction": None}]), [])


if __name__ == "__main__":
    unittest.main()
