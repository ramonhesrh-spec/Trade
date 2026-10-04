import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from app.replay import engine
from app.replay.outcome import Outcome
from app.setup_eval import SetupEvaluation
from tests.replay.fixtures import make_base

T0 = pd.Timestamp("2026-02-05", tz="UTC")
H = pd.Timedelta(hours=1)


class ZoneRecentlyFailedTest(unittest.TestCase):
    now = pd.Timestamp("2026-02-10", tz="UTC")

    def check(self, failures, direction="long", zone=100.0, atr=2.0):
        return engine._zone_recently_failed(failures, direction, zone, atr, self.now)

    def test_window_edges(self):
        self.assertTrue(self.check([("long", 100.0, self.now - pd.Timedelta(days=3))]))
        self.assertFalse(self.check([("long", 100.0, self.now - pd.Timedelta(days=3, seconds=1))]))
        self.assertTrue(self.check([("long", 100.0, self.now)]))

    def test_future_failure_is_ignored(self):
        self.assertFalse(self.check([("long", 100.0, self.now + pd.Timedelta(seconds=1))]))

    def test_tolerance_is_half_atr(self):
        f = self.now - H
        self.assertTrue(self.check([("long", 101.0, f)]))  # precies 0,5 * 2.0
        self.assertFalse(self.check([("long", 101.01, f)]))
        self.assertTrue(self.check([("long", 99.0, f)]))
        self.assertFalse(self.check([("long", 98.99, f)]))

    def test_direction_mismatch(self):
        self.assertFalse(self.check([("short", 100.0, self.now - H)]))

    def test_no_atr_is_false(self):
        f = [("long", 100.0, self.now - H)]
        self.assertFalse(self.check(f, atr=0))
        self.assertFalse(self.check(f, atr=None))


def evaluation(confirmed, zone=None):
    return SetupEvaluation(confirmed, True, 80.0, "r", 99.0, 103.0, zone, None, None, None, None, 2.0)


def outcome(result, exit_at):
    return Outcome(result, exit_at, 100.0, 0.0, 0.0)


class ScriptedRulesTest(unittest.TestCase):
    """Beslislogica gescript: richting altijd long, beoordeling en uitkomst per aanroep."""

    def setUp(self):
        self.base = {"BTC": make_base(days=60, seed=1), "ETH": make_base(days=60, seed=2, start_price=50.0)}

    def run_script(self, evaluations, outcomes, steps, step):
        """evaluations: lijst (confirmed, zone), één per evaluatie-aanroep; outcomes: {signaaltijd: Outcome|None}.
        Geeft (signalen, lijst van (tijd, zone-100 geblokkeerd?) per evaluatie)."""
        calls = []
        queue = list(evaluations)
        ind = SimpleNamespace(price=100.0, ema9=2.0, ema21=1.0, atr=2.0)

        def fake_eval(direction, df, ind_, zones, confirmation, zone_failed, levels):
            confirmed, zone = queue.pop(0)
            calls.append(zone_failed(100.0))
            return evaluation(confirmed, zone)

        def fake_resolve(direction, entry, stop, take, candles, at, *a):
            return outcomes[at]

        fake_ind = mock.Mock(compute_indicators=lambda df: ind, detect_sr_zones=lambda df: [])
        with mock.patch.object(engine, "indicators", fake_ind), \
                mock.patch.object(engine, "full_confirmation_sync", return_value=(True, "r", 80.0, True)), \
                mock.patch.object(engine.setup_eval, "evaluate_day_trading_setup", fake_eval), \
                mock.patch.object(engine, "resolve", fake_resolve):
            signals = engine.replay_day_trading("ETH", self.base, T0, T0 + step * (steps - 1), step=step)
        return signals, calls

    def test_confirmed_open_signal_blocks_until_exit(self):
        outcomes = {T0: outcome("take_profit", T0 + 3 * H), T0 + 3 * H: None}
        signals, calls = self.run_script([(True, None), (True, None)], outcomes, steps=5, step=H)
        self.assertEqual([s.at for s in signals], [T0, T0 + 3 * H])
        self.assertEqual(len(calls), 2)  # uren 1 en 2 worden niet eens beoordeeld

    def test_unconfirmed_replaced_by_confirmed_and_its_failure_is_dropped(self):
        outcomes = {T0: outcome("stop_loss", T0 + 3 * H), T0 + H: outcome("take_profit", T0 + 2 * H),
                    T0 + 2 * H: None}
        # u0 onbevestigd (stop om u3, zone 100); u1 bevestigd vervangt het; u2 nieuw (onbevestigd) signaal; u3 beoordeeld
        evals = [(False, 100.0), (True, 100.0), (False, None), (False, None)]
        signals, calls = self.run_script(evals, outcomes, steps=4, step=H)
        self.assertEqual([(s.at, s.confirmed) for s in signals], [(T0 + H, True), (T0 + 2 * H, False)])
        self.assertEqual(calls, [False, False, False, False])  # de vervangen stop blokkeert zone 100 niet

    def test_control_unreplaced_stop_does_block_from_exit_time(self):
        outcomes = {T0: outcome("stop_loss", T0 + 3 * H), T0 + 3 * H: None}
        evals = [(False, 100.0), (False, None), (False, None), (False, None)]
        signals, calls = self.run_script(evals, outcomes, steps=4, step=H)
        self.assertEqual([s.at for s in signals], [T0, T0 + 3 * H])
        self.assertEqual(calls, [False, False, False, True])  # pas vanaf de stop (u3), niet ervoor

    def test_zone_block_lasts_three_days_from_exit_time(self):
        step = pd.Timedelta(hours=12)
        exit_at = T0 + pd.Timedelta(days=1)
        outcomes = {T0: outcome("stop_loss", exit_at), exit_at: None}
        n = 12
        evals = [(False, 100.0)] + [(False, None)] * (n - 1)
        signals, calls = self.run_script(evals, outcomes, steps=n, step=step)
        # stappen i = 0..11 op T0 + 12u*i; evaluatie bij i=0,1 (open, onbevestigd), i=2 (verlopen) en verder
        times = [T0 + step * i for i in range(n)]
        blocked = [exit_at <= t <= exit_at + pd.Timedelta(days=3) for t in times]
        self.assertTrue(any(blocked) and not all(blocked))
        self.assertEqual(calls, blocked)


if __name__ == "__main__":
    unittest.main()
