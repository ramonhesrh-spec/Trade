import unittest

from app import misser

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


if __name__ == "__main__":
    unittest.main()
