import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from app import config, db, repo, samenval

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def sig(i, coin="BTC", direction="long", at="2026-10-05T10:00:00+00:00"):
    return {"id": i, "coin": coin, "direction": direction, "created_at": at, "stop_loss": 99.0, "take_profit": 102.0,
            "price": 100.0}


def call(at, coin="BTC", direction="long", category="day_trading", mid=1):
    return {"message_id": mid, "at": at, "coin": coin, "direction": direction, "category": category}


class FindMatchesTest(unittest.TestCase):
    def test_matches_same_coin_side_inside_window_either_order(self):
        s = [sig(1)]
        self.assertEqual(len(samenval.find_matches(s, [call("2026-10-05T07:00:00+00:00")], set(), 6)), 1)  # call vooraf
        self.assertEqual(len(samenval.find_matches(s, [call("2026-10-05T15:30:00+00:00")], set(), 6)), 1)  # call erna

    def test_no_match_outside_window_other_side_other_coin_or_category(self):
        s = [sig(1)]
        for c in (call("2026-10-05T03:00:00+00:00"), call("2026-10-05T10:00:00+00:00", direction="short"),
                  call("2026-10-05T10:00:00+00:00", coin="ETH"), call("2026-10-05T10:00:00+00:00", category="lange_termijn")):
            self.assertEqual(samenval.find_matches(s, [c], set(), 6), [])

    def test_already_matched_signal_is_skipped_and_closest_call_wins(self):
        self.assertEqual(samenval.find_matches([sig(1)], [call("2026-10-05T10:05:00+00:00")], {1}, 6), [])
        best = samenval.find_matches([sig(1)], [call("2026-10-05T07:00:00+00:00", mid=1), call("2026-10-05T10:20:00+00:00", mid=2)], set(), 6)
        self.assertEqual(best[0]["message_id"], 2)


class DisableTest(unittest.TestCase):
    def results(self, wins, losses):
        win = {"price": 100, "stop_loss": 99, "take_profit": 102, "auto_outcome": "take_profit"}
        loss = {**win, "auto_outcome": "stop_loss"}
        return [win] * wins + [loss] * losses

    def test_disables_only_with_enough_trades_and_negative_sum(self):
        self.assertTrue(samenval.should_disable(self.results(8, 22), 30))   # 8*2 - 22 < 0
        self.assertFalse(samenval.should_disable(self.results(12, 18), 30))  # 24 - 18 > 0
        self.assertFalse(samenval.should_disable(self.results(0, 29), 30))   # te weinig


class DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(config, "DATABASE_PATH", str(Path(self.tmp.name) / "t.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init_db()
        repo.create_user("a", "x", 0, 1)

    def insert_signal(self, **kw):
        data = {"message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "smc",
                "pattern_name": None, "price": 100.0, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None,
                "ema9": None, "ema21": None, "atr": None, "atr_avg20": None, "adx": None, "technical_confirmed": 1,
                "pass_pct": None, "hard_gates_ok": 1, "confidence": "x", "reason": "", "stop_loss": 99.0, "take_profit": 102.0,
                "context_note": None, "is_practice": 0, "plain_explanation": None, "suggested_entry_low": None,
                "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None}
        data.update(kw)
        return repo.insert_signal(data)

class RunTest(DbCase):
    def test_run_notifies_once_per_signal(self):
        sid = self.insert_signal()
        with db.session() as conn:
            conn.execute("INSERT INTO messages (received_at, raw_text, category, coin, direction, unclear) VALUES (?, 'x', 'day_trading', 'BTC', 'long', 0)",
                         (db.now_iso(),))
        sent = []
        async def fake_push(user_id, title, body, url, silent=False):
            sent.append(title)
        with mock.patch.object(samenval.push_notify, "send_push", fake_push):
            first = asyncio.run(samenval.run())
            second = asyncio.run(samenval.run())
        self.assertEqual((first, second), (1, 0))
        self.assertEqual(len(sent), 1)
        self.assertIn("ongetest", sent[0])
        self.assertEqual(repo.samenval_signal_ids(), {sid})
        rows = repo.list_signals_for_quality_report(None)
        self.assertTrue(rows[0]["samenval"])


if __name__ == "__main__":
    unittest.main()
