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


if __name__ == "__main__":
    unittest.main()
