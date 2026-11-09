"""Directe tests van setup_eval.evaluate_day_trading_setup op deterministische
nepdata: de takken die de live golden (lege database, geen bron-niveaus) niet
raakt."""
import unittest
from unittest import mock

import pandas as pd

from app import indicators, risk, setup_eval
from app.replay.view import ReplayData
from tests.replay.fixtures import make_base

BASE = {"BTC": make_base(days=60, seed=1), "ETH": make_base(days=60, seed=2, start_price=50.0)}
CONFIRMATION = (True, "basis", 1.0, True)
ZONE_REASON = " | ✗ Zone recent gefaald"


def build(coin, at):
    df = ReplayData(BASE, pd.Timestamp(at, tz="UTC")).fetch_ohlcv(coin)
    return df, indicators.compute_indicators(df), indicators.detect_sr_zones(df)


def evaluate(direction, df, ind, zones, failed=lambda price: False, message_levels=()):
    return setup_eval.evaluate_day_trading_setup(
        direction, df, ind, zones, CONFIRMATION, failed, list(message_levels),
    )


class ZoneFailureTest(unittest.TestCase):
    def test_failed_zone_blocks_and_is_called_with_nearest_price(self):
        df, ind, zones = build("BTC", "2026-02-14 08:15")
        base = evaluate("long", df, ind, zones)
        self.assertIsNotNone(base.nearest_sr_zone_price)
        calls = []
        ev = evaluate("long", df, ind, zones, failed=lambda price: calls.append(price) or True)
        self.assertEqual(calls, [base.nearest_sr_zone_price])
        self.assertFalse(ev.confirmed)
        self.assertFalse(ev.hard_gates_ok)
        self.assertIn(ZONE_REASON, ev.reason)
        self.assertNotIn(ZONE_REASON, base.reason)
        # Zone-faal komt vóór de sniper-reden: volgorde waar analysescripts op rekenen.
        if "Sniper-entry" in ev.reason:
            self.assertLess(ev.reason.index(ZONE_REASON), ev.reason.index("Sniper-entry"))

    def test_not_called_without_nearby_zone(self):
        df, ind, zones = build("ETH", "2026-02-14 08:15")
        calls = []
        ev = evaluate("short", df, ind, zones, failed=lambda price: calls.append(price) or True)
        self.assertIsNone(ev.nearest_sr_zone_price)
        self.assertEqual(calls, [])
        self.assertNotIn(ZONE_REASON, ev.reason)


class MessageLevelsTest(unittest.TestCase):
    def test_message_levels_feed_the_stop(self):
        df, ind, zones = build("BTC", "2026-02-14 08:15")
        level = ind.price * 0.995
        swing_low, swing_high = indicators.swing_levels(df)
        zone_levels = [
            edge for zone in zones for edge in (zone.price_low, zone.price_high)
            if abs(edge - ind.price) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
        ]
        expected = risk.compute_stop_take_from_levels(
            "long", ind.price, ind.atr, [level] + zone_levels, swing_low=swing_low, swing_high=swing_high,
        )
        without = evaluate("long", df, ind, zones)
        with_level = evaluate("long", df, ind, zones, message_levels=[level])
        self.assertEqual((with_level.stop_loss, with_level.take_profit), (expected.stop_loss, expected.take_profit))
        self.assertNotEqual(with_level.stop_loss, without.stop_loss)

    def test_no_levels_at_all_uses_atr_stop(self):
        df, ind, _ = build("BTC", "2026-02-14 08:15")
        swing_low, swing_high = indicators.swing_levels(df)
        expected = risk.compute_stop_take("long", ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high)
        ev = evaluate("long", df, ind, [])
        self.assertEqual((ev.stop_loss, ev.take_profit), (expected.stop_loss, expected.take_profit))


class RiskRewardTest(unittest.TestCase):
    def test_ratio_is_reward_over_risk(self):
        df, ind, zones = build("BTC", "2026-02-20 17:45")
        ev = evaluate("long", df, ind, zones)
        self.assertAlmostEqual(
            ev.risk_reward_ratio, abs(ev.take_profit - ind.price) / abs(ind.price - ev.stop_loss),
        )

    def test_gate_fires_below_minimum(self):
        df, ind, zones = build("BTC", "2026-02-20 17:45")
        ev = evaluate("long", df, ind, zones)
        self.assertLess(ev.risk_reward_ratio, setup_eval.MIN_RISK_REWARD_RATIO)
        self.assertIn(f" | ✗ Risico/rendement: {ev.risk_reward_ratio:.1f} tegen 1", ev.reason)
        self.assertFalse(ev.confirmed)
        self.assertFalse(ev.hard_gates_ok)

    def test_gate_silent_above_minimum(self):
        df, ind, zones = build("ETH", "2026-02-14 08:15")
        ev = evaluate("short", df, ind, zones)
        self.assertGreaterEqual(ev.risk_reward_ratio, setup_eval.MIN_RISK_REWARD_RATIO)
        self.assertNotIn("Risico/rendement", ev.reason)

    def test_patched_minimum_forces_gate(self):
        df, ind, zones = build("ETH", "2026-02-14 08:15")
        with mock.patch.object(setup_eval, "MIN_RISK_REWARD_RATIO", 100.0):
            ev = evaluate("short", df, ind, zones)
        self.assertIn("Risico/rendement", ev.reason)
        self.assertFalse(ev.hard_gates_ok)


class StopDistanceTest(unittest.TestCase):
    def test_tiny_max_distance_fires_gate_last(self):
        df, ind, zones = build("BTC", "2026-02-14 08:15")
        with mock.patch.object(setup_eval, "MAX_STOP_DISTANCE_PCT", 0.001):
            ev = evaluate("long", df, ind, zones)
        pct = abs(ind.price - ev.stop_loss) / ind.price * 100
        self.assertIn(f" | ✗ Stopafstand: {pct:.1f}% van entry, boven de ondergrens van 0.001%", ev.reason)
        self.assertFalse(ev.confirmed)
        self.assertTrue(ev.reason.endswith("0.001%"))

    def test_default_limit_passes_for_tight_stop(self):
        self.assertTrue(setup_eval.stop_within_max_distance(100.0, 99.0))
        self.assertFalse(setup_eval.stop_within_max_distance(100.0, 98.0))
        self.assertFalse(setup_eval.stop_within_max_distance(0.0, 98.0))


if __name__ == "__main__":
    unittest.main()
