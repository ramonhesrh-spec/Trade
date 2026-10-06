import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, market_script as ms, repo
from tests.test_samenval import DbCase

PRICE, ATR = 100.0, 1.0


def raw(**kw):
    base = {"direction": "long", "trigger": {"type": "close_above", "level": 101.0}, "entry": 100.8, "stop_loss": 99.8,
            "take_profit": 103.0, "reason": "Break boven gisteren hoog."}
    base.update(kw)
    return base


def candles(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


class ValidateTest(unittest.TestCase):
    def check(self, item, reason_part=None):
        good, dropped = ms.validate_scenarios([item], PRICE, ATR, min_stop_pct=0.2)
        if reason_part is None:
            self.assertEqual((len(good), dropped), (1, []))
        else:
            self.assertEqual(good, [])
            self.assertIn(reason_part, dropped[0])

    def test_valid_scenario_passes(self):
        self.check(raw())

    def test_each_rule_drops(self):
        self.check(raw(stop_loss=101.0), "volgorde")
        self.check(raw(entry=100.8, stop_loss=100.7, take_profit=103.0), "stop te dichtbij")
        self.check(raw(take_profit=101.5), "R:R")
        self.check(raw(trigger={"type": "close_above", "level": 110.0}, entry=100.8), "te ver")
        self.check(raw(trigger={"type": "close_above", "level": 99.0}), "klopt al")
        self.check(raw(trigger={"type": "close_below", "level": 101.0}), "klopt al")
        self.check(raw(trigger={"type": "sweep_reclaim", "level": 101.0}), "verkeerde kant")
        self.check(raw(reason=""), "geen reden")
        self.check(raw(direction="omhoog"), "onbekende")
        self.check({"direction": "long"}, "onvolledig")

    def test_short_and_sweep_variants_and_cap_at_two(self):
        short = raw(direction="short", trigger={"type": "sweep_reclaim", "level": 101.0}, entry=100.6, stop_loss=101.6, take_profit=98.4)
        self.check(short)
        good, dropped = ms.validate_scenarios([raw(), raw(), raw()], PRICE, ATR, min_stop_pct=0.2)
        self.assertEqual((len(good), len(dropped)), (2, 1))

    def test_empty_or_missing_list_is_fine(self):
        self.assertEqual(ms.validate_scenarios(None, PRICE, ATR), ([], []))
        self.assertEqual(ms.validate_scenarios([], PRICE, ATR), ([], []))


class TriggerTest(unittest.TestCase):
    def test_close_above_and_below(self):
        c = candles([[100, 101, 99, 100], [100, 102, 100, 101.5]])
        self.assertTrue(ms.check_trigger("close_above", "long", 101.0, c))
        self.assertFalse(ms.check_trigger("close_below", "short", 101.0, c))
        self.assertFalse(ms.check_trigger("close_above", "long", 101.0, c.iloc[:1]))

    def test_sweep_reclaim_needs_wick_through_and_close_back(self):
        long = candles([[100, 100.5, 98.9, 99.2], [99.2, 100.2, 99.0, 100.1]])
        self.assertTrue(ms.check_trigger("sweep_reclaim", "long", 99.0, long))
        no_wick = candles([[100, 100.5, 99.5, 100.2], [100.2, 100.4, 99.6, 100.1]])
        self.assertFalse(ms.check_trigger("sweep_reclaim", "long", 99.0, no_wick))
        not_back = candles([[100, 100.5, 98.9, 99.2], [99.2, 99.4, 98.8, 98.9]])
        self.assertFalse(ms.check_trigger("sweep_reclaim", "long", 99.0, not_back))
        short = candles([[100, 101.2, 100, 100.8], [100.8, 101.0, 99.7, 99.8]])
        self.assertTrue(ms.check_trigger("sweep_reclaim", "short", 101.0, short))

    def test_actionable_and_disable(self):
        self.assertTrue(ms.still_actionable("long", 99, 103, 100.5))
        self.assertFalse(ms.still_actionable("long", 99, 103, 98.5))
        self.assertFalse(ms.still_actionable("short", 103, 97, 96.0))
        win = {"price": 100, "stop_loss": 99, "take_profit": 102, "auto_outcome": "take_profit"}
        loss = {**win, "auto_outcome": "stop_loss"}
        self.assertTrue(ms.should_disable([win] * 8 + [loss] * 22, 30))
        self.assertFalse(ms.should_disable([loss] * 29, 30))


class EngineTest(DbCase):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        sid = repo.insert_market_script("BTC", "Samenvatting", "long", "m", [raw_row()], 0, (self.now + timedelta(hours=12)).isoformat())
        self.sid = sid

    def run_engine(self, df, **cfg):
        pushed = []

        async def fake_push(user_id, title, body, url, silent=False):
            pushed.append((title, body))

        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: df), \
                mock.patch("app.push_notify.send_push", fake_push), \
                mock.patch.multiple(config, SCRIPT_ENABLED=cfg.get('SCRIPT_ENABLED', True),
                                    SCRIPT_MAX_ALERTS_PER_DAY=cfg.get('SCRIPT_MAX_ALERTS_PER_DAY', 6)):
            fired = asyncio.run(ms.run_triggers(self.now))
        return fired, pushed

    def test_fires_once_creates_signal_and_message(self):
        df = candles([[100, 101, 99, 100], [100, 102, 100, 101.5], [101.5, 101.6, 101.2, 101.4]])  # laatste = vormend
        fired, pushed = self.run_engine(df)
        self.assertEqual(fired, 1)
        self.assertIn("ongetest", pushed[0][0])
        self.assertIn("Limietorder 100.8000", pushed[0][1])
        rows = repo.list_signals_for_quality_report(None)
        self.assertEqual([r["trade_type"] for r in rows], ["script"])
        self.assertEqual(self.run_engine(df)[0], 0)           # tweede keer niets: scenario is al afgegaan

    def test_does_not_fire_when_condition_false_or_price_already_past_stop(self):
        flat = candles([[100, 100.4, 99.8, 100.1]] * 3)
        self.assertEqual(self.run_engine(flat)[0], 0)
        gone = candles([[100, 101, 99, 100], [100, 104.5, 100, 104.0], [104, 104.2, 103.8, 104.1]])  # al voorbij de take
        self.assertEqual(self.run_engine(gone)[0], 0)
        self.assertEqual(repo.list_waiting_scenarios(), [])  # gemist, niet blijven hangen

    def test_daily_cap_and_off_switch(self):
        df = candles([[100, 101, 99, 100], [100, 102, 100, 101.5], [101.5, 101.6, 101.2, 101.4]])
        fired, _ = self.run_engine(df, SCRIPT_MAX_ALERTS_PER_DAY=0)
        self.assertEqual(fired, 0)
        self.assertEqual(self.run_engine(df, SCRIPT_ENABLED=False)[0], 0)

    def test_new_script_replaces_waiting_and_old_ones_expire(self):
        repo.insert_market_script("BTC", "Nieuw", "short", "m", [], 0, (self.now + timedelta(hours=12)).isoformat())
        self.assertEqual(repo.list_waiting_scenarios(), [])
        repo.insert_market_script("ETH", "x", "long", "m", [raw_row()], 0, (self.now - timedelta(hours=1)).isoformat())
        repo.expire_scenarios(self.now.isoformat())
        self.assertEqual(repo.list_waiting_scenarios(), [])
        self.assertEqual({s["coin"] for s in repo.latest_scripts()}, {"BTC", "ETH"})


def raw_row():
    return {"direction": "long", "trigger_type": "close_above", "trigger_level": 101.0, "entry": 100.8, "stop_loss": 99.8,
            "take_profit": 103.0, "reason": "Break boven gisteren hoog."}


if __name__ == "__main__":
    unittest.main()
