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


if __name__ == "__main__":
    unittest.main()
