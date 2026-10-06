import asyncio
import json
import unittest
from datetime import timedelta
from unittest import mock

import pandas as pd

from app import config, repo, structure_live as sl
from app.replay import breakretest as br
from app.replay.lab import make_bars
from tests.replay.test_breakretest import frame
from tests.test_samenval import DbCase

CUT = 4800                      # breukcandle = 4800 / 30 = bar 160, ruim voorbij de minimale historie
BREAK_BAR = CUT // 30


class PureTest(unittest.TestCase):
    def test_line_value_follows_slope_per_30m(self):
        s = {"p1_at": "2026-03-02T00:00:00+00:00", "line_a": 100.0, "line_slope": 0.1}
        self.assertAlmostEqual(sl.line_value(s, pd.Timestamp("2026-03-02T03:00:00+00:00")), 100.6)

    def test_parse_grade_rejects_unknown_and_truncates(self):
        self.assertEqual(sl.parse_grade({"grade": "a", "reason": "x" * 400})[0], "A")
        self.assertEqual(len(sl.parse_grade({"grade": "A", "reason": "x" * 400})[1]), sl.REASON_MAX)
        self.assertIsNone(sl.parse_grade({"grade": "S", "reason": ""})[0])

    def test_disable_needs_enough_negative_results(self):
        win = {"price": 100, "stop_loss": 99, "take_profit": 102, "auto_outcome": "take_profit"}
        loss = {**win, "auto_outcome": "stop_loss"}
        self.assertTrue(sl.should_disable([win] * 8 + [loss] * 22, 30))
        self.assertFalse(sl.should_disable([loss] * 29, 30))


class LiveTest(DbCase):
    def setUp(self):
        super().setUp()
        self.f = frame(minutes=60 * 24 * 6, plant=True, cut=CUT)
        self.bars = make_bars(self.f, 30)
        self.pushed = []
        self.graded = []

    def fetch(self, n_closed, step_min=None):
        bars, f = self.bars, self.f

        def fake(coin, timeframe="30m", limit=300, since=None):
            if timeframe == "30m":
                return bars.iloc[:n_closed + 1][["timestamp", "open", "high", "low", "close", "volume"]]
            end = bars.at[n_closed - 1, "close_time"]
            part = f[f["timestamp"] < end].set_index("timestamp").resample("5min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
            return part.tail(limit)
        return fake

    def run_live(self, n_closed, grade="A"):
        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            self.pushed.append((title, body, url, silent))

        def fake_claude(ctx):
            self.graded.append(ctx)
            return {"grade": grade, "reason": "Schone range, duidelijke breuk."}

        now = (self.bars.at[n_closed - 1, "close_time"]).to_pydatetime()
        with mock.patch("app.exchange.fetch_ohlcv", self.fetch(n_closed)), mock.patch("app.push_notify.send_push", fake_push), \
                mock.patch.object(sl, "call_claude", fake_claude), mock.patch.object(config, "BASE_COINS", ["BTC"]), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]):
            asyncio.run(sl.run(now))

    def test_discovers_break_grades_it_and_alerts_once_with_plan(self):
        self.run_live(BREAK_BAR + 4)
        rows = repo.list_structure_setups(("waiting",))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["direction"], rows[0]["grade"]), ("short", "A"))
        title, body, url, silent = self.pushed[0]
        self.assertIn("Structuur A (ongetest)", title)
        self.assertIn("Limietorder", body)
        self.assertIn("Doelen", body)
        self.assertTrue(url.startswith("/smc#structuur-"))
        self.assertEqual(len(self.graded), 1)
        self.assertIn("laatste_candles_30m", self.graded[0])
        self.run_live(BREAK_BAR + 4)
        self.assertEqual(len(self.graded), 1)                 # dezelfde breuk wordt niet opnieuw beoordeeld

    def test_grade_c_is_stored_but_not_alerted(self):
        self.run_live(BREAK_BAR + 4, grade="C")
        self.assertEqual(self.pushed, [])
        self.assertEqual(repo.list_structure_setups(("waiting",)), [])
        self.assertEqual(len(repo.list_structure_setups(("niet_gemeld",))), 1)

    def test_grade_b_is_silent(self):
        self.run_live(BREAK_BAR + 4, grade="B")
        self.assertTrue(self.pushed[0][3])

    def test_retest_fills_and_becomes_a_tracked_signal(self):
        self.run_live(BREAK_BAR + 4)
        self.pushed.clear()
        self.run_live(BREAK_BAR + 9)                           # de koers is terug bij het gebroken niveau
        rows = repo.list_signals_for_quality_report(None)
        self.assertEqual([r["trade_type"] for r in rows], ["structuur"])
        self.assertIsNotNone(repo.list_structure_setups(("fired",))[0]["signal_id"])
        sig = rows[0]
        self.assertGreater(sig["stop_loss"], sig["price"])     # short: stop boven de instap
        self.assertLess(sig["take_profit"], sig["price"])
        self.assertTrue(any("gevuld" in t for t, *_ in self.pushed))

    def test_off_switch(self):
        with mock.patch.object(config, "STRUCTURE_ENABLED", False):
            self.run_live(BREAK_BAR + 4)
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()
