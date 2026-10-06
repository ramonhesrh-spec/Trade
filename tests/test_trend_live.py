import asyncio
import unittest
from unittest import mock

import pandas as pd

from app import config, repo, trend_live as tl
from app.replay import trendpullback as tp
from app.replay.lab import make_bars
from tests.replay.test_trendpullback import frame
from tests.test_samenval import DbCase


class TrendLiveTest(DbCase):
    def setUp(self):
        super().setUp()
        self.f = frame()
        b = tp.prepare(self.f)
        ent = tp.entries(*b)
        risk_pct = (ent["entry"] - ent["stop"]).abs() / ent["entry"] * 100
        self.entries = ent[(risk_pct >= tp.MIN_STOP_PCT) & (risk_pct <= tp.MAX_STOP_PCT)]
        self.at = self.entries["at"].iloc[len(self.entries) // 2]
        self.now = self.at + pd.Timedelta(minutes=2)
        self.pushed = []

    def fetch(self, coin, timeframe="5m", limit=300, since=None):
        minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}[timeframe]
        bars = make_bars(self.f[self.f["timestamp"] < self.now], minutes)
        return bars[["timestamp", "open", "high", "low", "close", "volume"]].tail(limit)

    def run_live(self, **cfg):
        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            self.pushed.append((title, body, silent))
        with mock.patch("app.exchange.fetch_ohlcv", self.fetch), mock.patch("app.push_notify.send_push", fake_push), \
                mock.patch.object(config, "BASE_COINS", ["BTC"]), mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]), \
                mock.patch.multiple(config, TREND_ENABLED=cfg.get("enabled", True), TREND_MAX_PER_DAY=cfg.get("cap", 6)):
            asyncio.run(tl.run(self.now.to_pydatetime()))

    def test_recent_entry_becomes_a_loud_signal_once(self):
        self.run_live()
        rows = repo.list_signals_for_quality_report(None)
        self.assertEqual([r["trade_type"] for r in rows], ["trend"])
        title, body, silent = self.pushed[0]
        self.assertIn("Trend-pullback", title)
        self.assertNotIn("ngetest", title + body)
        self.assertNotIn("-0,06R", body)                       # geen afschrikkende regel in de melding, de score staat op Bewijs
        self.assertIn("Tik voor de grafiek en het plan.", body)
        self.assertFalse(silent)
        self.run_live()
        self.assertEqual(len(repo.list_signals_for_quality_report(None)), 1)       # zelfde instap, tweede scan: niets

    def test_daily_cap_and_off_switch(self):
        self.run_live(cap=0)
        self.assertEqual(repo.list_signals_for_quality_report(None), [])
        self.run_live(enabled=False)
        self.assertEqual(self.pushed, [])

    def test_levels_widen_tight_stops_and_reject_only_too_wide_ones(self):
        stop, take = tl.levels("long", 100.0, 99.95)                          # stop 0,05%: verbreed tot de ondergrens, het doel schuift mee
        self.assertAlmostEqual(stop, 100.0 * (1 - 0.004))
        self.assertAlmostEqual(take, 100.0 + 0.4 * 2.0)
        self.assertIsNone(tl.levels("long", 100.0, 95.0))                     # 5% is te ruim
        stop, take = tl.levels("long", 100.0, 99.0)
        self.assertAlmostEqual(take, 102.0)

    def test_heartbeat_is_written(self):
        self.run_live()
        self.assertIsNotNone(repo.get_beat("trend"))


if __name__ == "__main__":
    unittest.main()
