import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import db, level_check, repo
from tests.test_samenval import DbCase


def candles(start: datetime, rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(minutes=5 * i)), "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
                         for i, (o, h, l, c) in enumerate(rows)])


class OutcomeTest(DbCase):
    def make_signal(self, hours_ago: float) -> int:
        sid = self.insert_signal(direction="long", price=100.0, stop_loss=99.0, take_profit=102.0)
        created = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?", (created.isoformat(), sid))
        return sid

    def run_check(self, frame: pd.DataFrame) -> None:
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: frame):
            asyncio.run(level_check.check_signal_outcomes())

    def test_a_target_hit_hours_ago_is_still_found(self):
        sid = self.make_signal(hours_ago=3)
        start = datetime.now(timezone.utc) - timedelta(hours=3, minutes=-5)
        rows = [(100, 100.5, 99.5, 100.2)] * 12 + [(100.2, 102.4, 100.1, 102.2)] + [(102, 102.3, 101.5, 102)] * 60       # doel na een uur, daarna rustig
        self.run_check(candles(start, rows))
        signal = repo.get_signal(sid)
        self.assertEqual(signal["auto_outcome"], "take_profit")              # met alleen de laatste 30 minuten was dit gemist
        self.assertIn("T", signal["auto_outcome_at"])

    def test_a_hit_before_the_signal_existed_does_not_count(self):
        sid = self.make_signal(hours_ago=1)
        start = datetime.now(timezone.utc) - timedelta(hours=3)
        rows = [(100, 102.5, 99.8, 102.0)] + [(100, 100.4, 99.6, 100.1)] * 40            # de eerste candle raakte het doel, ruim vóór de melding
        self.run_check(candles(start, rows))
        self.assertIsNone(repo.get_signal(sid)["auto_outcome"])

    def test_a_hit_after_the_signal_expired_does_not_count(self):
        sid = self.make_signal(hours_ago=60)                                  # 2,5 dag oud: de geldigheid is verlopen
        start = datetime.now(timezone.utc) - timedelta(hours=60)
        rows = [(100, 100.3, 99.7, 100.1)] * 12 * 52 + [(100, 102.6, 100, 102.2)] + [(102, 102.1, 101.9, 102)] * 50       # doel pas na ruim 52 uur
        self.run_check(candles(start, rows))
        signal = repo.get_signal(sid)
        self.assertEqual(signal["auto_outcome"], "vervallen")                 # hetzelfde als de oude regel: geen late uitkomst

    def test_stop_wins_when_both_levels_are_in_one_candle(self):
        sid = self.make_signal(hours_ago=1)
        start = datetime.now(timezone.utc) - timedelta(minutes=50)
        self.run_check(candles(start, [(100, 102.5, 98.5, 100.0)] + [(100, 100.2, 99.9, 100.0)] * 8))
        self.assertEqual(repo.get_signal(sid)["auto_outcome"], "stop_loss")


if __name__ == "__main__":
    unittest.main()
