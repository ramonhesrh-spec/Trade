import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import db, level_check, notifications_view, price_alerts, repo
from tests.test_samenval import DbCase


class PureTest(unittest.TestCase):
    def test_side_is_fixed_by_the_price_at_creation(self):
        self.assertEqual(price_alerts.side_for(105.0, 100.0), "above")
        self.assertEqual(price_alerts.side_for(95.0, 100.0), "below")
        self.assertEqual(price_alerts.side_for(100.0, 100.0), "above")

    def test_first_hit_only_counts_a_move_towards_the_level(self):
        bars = [(101.0, 99.0), (104.0, 100.0), (106.0, 103.0)]
        self.assertEqual(price_alerts.first_hit("above", 105.0, bars), 106.0)
        self.assertIsNone(price_alerts.first_hit("above", 107.0, bars))
        self.assertEqual(price_alerts.first_hit("below", 99.5, bars), 99.0)
        self.assertIsNone(price_alerts.first_hit("below", 98.0, bars))
        self.assertIsNone(price_alerts.first_hit("above", 105.0, []))

    def test_text(self):
        title, body = price_alerts.alert_text("BTC", "Doel", 61000.0, 61012.5)
        self.assertEqual(title, "Prijsalarm BTC: doel 61000.00 bereikt")
        self.assertIn("61012.50", body)
        self.assertNotIn("—", title + body)

    def test_notification_chip(self):
        self.assertEqual(notifications_view.TYPE_CHIPS["prijsalarm"][0], "Alarm")


def frame(start, rows):
    return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(minutes=5 * i)), "open": c, "high": h, "low": l, "close": c, "volume": 1.0}
                         for i, (h, l, c) in enumerate(rows)])


class CheckTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        self.push = mock.patch("app.push_notify.send_push", new=mock.AsyncMock())
        self.sent = self.push.start()
        self.addCleanup(self.push.stop)

    def alert(self, price, side, minutes_ago):
        aid = repo.create_price_alert(self.uid, "BTC", price, side, "Doel", "/smc#radar-setup-1")
        with db.session() as conn:
            conn.execute("UPDATE price_alerts SET created_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(), aid))
        return aid

    def run_check(self, df):
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: df):
            asyncio.run(level_check.check_price_alerts())

    def test_fires_once_with_push_and_notification(self):
        aid = self.alert(105.0, "above", 40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.run_check(frame(start, [(101, 99, 100), (106, 100, 105), (104, 102, 103)]))
        self.assertEqual(self.sent.await_count, 1)
        self.assertEqual(self.sent.await_args.args[3], "/smc#radar-setup-1")
        self.assertEqual(repo.list_price_alerts(self.uid), [])
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT type FROM notifications WHERE user_id = ?", (self.uid,)).fetchone()["type"], "prijsalarm")
        self.run_check(frame(start, [(106, 100, 105)]))
        self.assertEqual(self.sent.await_count, 1)                        # fire once
        self.assertIsNotNone(aid)

    def test_candles_from_before_the_alert_do_not_count(self):
        self.alert(105.0, "above", 5)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.run_check(frame(start, [(106, 100, 105)] + [(101, 99, 100)] * 5))       # alleen de oude candle raakte het niveau
        self.assertEqual(self.sent.await_count, 0)
        self.assertEqual(len(repo.list_price_alerts(self.uid)), 1)

    def test_a_failed_push_does_not_make_it_fire_again(self):
        self.sent.side_effect = RuntimeError("push stuk")
        self.alert(95.0, "below", 40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.run_check(frame(start, [(101, 94, 96)]))
        self.run_check(frame(start, [(101, 94, 96)]))
        self.assertEqual(self.sent.await_count, 1)

    def test_repo_cap_count_and_delete_are_per_user(self):
        aid = repo.create_price_alert(self.uid, "ETH", 2500.0, "below", "Stop", None)
        self.assertEqual(repo.count_open_price_alerts(self.uid), 1)
        self.assertFalse(repo.delete_price_alert(aid, self.uid + 1))
        self.assertTrue(repo.delete_price_alert(aid, self.uid))
        self.assertEqual(repo.count_open_price_alerts(self.uid), 0)


if __name__ == "__main__":
    unittest.main()
