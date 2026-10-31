"""Reproducties van de externe review (2026-10-31): elk geval faalde vóór zijn reparatie."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import db, level_check, repo
from tests.test_samenval import DbCase


class ResolvedSignalIsNeverUpdatedTest(DbCase):
    def _open_day_trade(self) -> int:
        sid = self.insert_signal(trade_type="day_trading")
        uid = repo.list_users()[0]["id"]
        repo.create_journal_entry(sid, uid, None)
        return sid

    def test_find_open_signal_skips_a_signal_with_an_outcome(self):
        sid = self._open_day_trade()
        self.assertEqual(repo.find_open_signal("BTC", "long")["id"], sid)
        repo.mark_signal_auto_outcome(sid, "stop_loss", db.now_iso())
        self.assertIsNone(repo.find_open_signal("BTC", "long"))

    def test_update_signal_leaves_a_resolved_plan_alone(self):
        sid = self._open_day_trade()
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        data = dict(repo.get_signal(sid))
        data.update(price=50.0, stop_loss=40.0, take_profit=70.0)
        repo.update_signal(sid, data)
        after = repo.get_signal(sid)
        self.assertEqual((after["price"], after["stop_loss"], after["take_profit"]), (100.0, 99.0, 102.0))


def _bars(start: datetime, rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(minutes=5 * i)), "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
                         for i, (o, h, l, c) in enumerate(rows)])


class OpenTradeAlertTest(DbCase):
    """level_check.check_open_trades: de stop-/doelmelding voor een genomen trade."""

    def setUp(self):
        super().setUp()
        self.sent = []

    async def _push(self, user_id, title, body, url, silent=False, **kw):
        self.sent.append((title, body))

    def _taken(self, minutes_ago: float) -> int:
        sid = self.insert_signal(trade_type="zone_radar")
        created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?", (created.isoformat(), sid))
        uid = repo.list_users()[0]["id"]
        entry = repo.create_journal_entry(sid, uid, None)
        repo.update_journal_status(entry, uid, "genomen", 100.0)
        return entry

    def _run(self, frame, push=None):
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: frame), \
                mock.patch.object(level_check.push_notify, "send_push", push or self._push):
            asyncio.run(level_check.check_open_trades())

    def _alert_sent(self, entry_id: int) -> int:
        with db.session() as conn:
            return conn.execute("SELECT level_alert_sent FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()[0]

    def test_a_stop_touch_before_the_signal_existed_does_not_alert(self):
        entry = self._taken(minutes_ago=12)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        # Eerste candle (30 min geleden, vóór het signaal) raakte de stop; daarna rustig.
        self._run(_bars(start, [(100, 100.2, 98.5, 100.0)] + [(100, 100.3, 99.6, 100.1)] * 5))
        self.assertEqual(self.sent, [])
        self.assertEqual(self._alert_sent(entry), 0)

    def test_the_candle_that_overlaps_the_signal_moment_does_not_count(self):
        self._taken(minutes_ago=12)
        start = datetime.now(timezone.utc) - timedelta(minutes=15)       # opent 3 minuten vóór het signaal
        self._run(_bars(start, [(100, 100.2, 98.5, 100.0)] + [(100, 100.3, 99.6, 100.1)] * 2))
        self.assertEqual(self.sent, [])

    def test_a_stop_touch_after_the_signal_still_alerts(self):
        entry = self._taken(minutes_ago=40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._run(_bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 100.2, 98.5, 99.0)] + [(99, 99.5, 98.8, 99.1)] * 2))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self._alert_sent(entry), 1)


if __name__ == "__main__":
    unittest.main()
