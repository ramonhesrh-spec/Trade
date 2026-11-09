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
CANDLE = pd.Timedelta(minutes=15)  # exit_at is het begin van de candle, bekend een candle later


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

    def run_script(self, evaluations, outcomes, steps, step, directions=None, prefilter=True, trace=None):
        """evaluations: lijst (confirmed, zone), één per evaluatie-aanroep; outcomes: {signaaltijd: Outcome|None}.
        Geeft (signalen, lijst van (tijd, zone-100 geblokkeerd?) per evaluatie)."""
        calls = []
        queue = list(evaluations)
        ind = SimpleNamespace(price=100.0, ema9=2.0, ema21=1.0, atr=2.0)
        dirs = list(directions) if directions else None

        def fake_compute(df):
            if dirs:
                ind.ema9, ind.ema21 = (2.0, 1.0) if dirs.pop(0) == "long" else (1.0, 2.0)
            return ind

        def fake_eval(direction, df, ind_, zones, confirmation, zone_failed, levels):
            confirmed, zone = queue.pop(0)
            calls.append(zone_failed(100.0))
            self.directions_seen.append(direction)
            return evaluation(confirmed, zone)

        def fake_resolve(direction, entry, stop, take, candles, at, *a):
            return outcomes[at]

        self.directions_seen = []
        pre = list(prefilter) if isinstance(prefilter, list) else None

        def fake_prefilter(i, d):
            return (pre.pop(0) if pre is not None else prefilter), "", 0.0, True

        fake_ind = mock.Mock(compute_indicators=fake_compute, detect_sr_zones=lambda df: [],
                             confirms_direction=fake_prefilter)
        with mock.patch.object(engine, "indicators", fake_ind), \
                mock.patch.object(engine, "full_confirmation_sync", return_value=(True, "r", 80.0, True)), \
                mock.patch.object(engine.setup_eval, "evaluate_day_trading_setup", fake_eval), \
                mock.patch.object(engine, "resolve", fake_resolve):
            signals = engine.replay_day_trading("ETH", self.base, T0, T0 + step * (steps - 1), step=step, trace=trace)
        return signals, calls

    def test_confirmed_open_signal_blocks_until_exit(self):
        outcomes = {T0: outcome("take_profit", T0 + 3 * H), T0 + 4 * H: None}
        signals, calls = self.run_script([(True, None), (True, None)], outcomes, steps=5, step=H)
        # de uitkomst is bekend op u3 + 15 min: pas u4 is een nieuw signaal mogelijk
        self.assertEqual([s.at for s in signals], [T0, T0 + 4 * H])
        self.assertEqual(len(calls), 2)

    def test_signal_is_not_released_at_exit_candle_start(self):
        outcomes = {T0: outcome("take_profit", T0 + 3 * H), T0 + 3 * H: None}
        signals, _ = self.run_script([(True, None)], outcomes, steps=4, step=H)
        self.assertEqual([s.at for s in signals], [T0])

    def test_unconfirmed_replaced_by_confirmed_and_its_failure_is_dropped(self):
        outcomes = {T0: outcome("stop_loss", T0 + 3 * H), T0 + H: outcome("take_profit", T0 + H + 2 * CANDLE),
                    T0 + 2 * H: None}
        # u0 onbevestigd (stop om u3, zone 100); u1 bevestigd vervangt het; u2 nieuw (onbevestigd) signaal; u3 beoordeeld
        evals = [(False, 100.0), (True, 100.0), (False, None), (False, None)]
        signals, calls = self.run_script(evals, outcomes, steps=4, step=H)
        self.assertEqual([(s.at, s.confirmed) for s in signals], [(T0 + H, True), (T0 + 2 * H, False)])
        self.assertEqual(calls, [False, False, False, False])  # de vervangen stop blokkeert zone 100 niet

    def test_control_unreplaced_stop_blocks_from_exit_plus_one_candle(self):
        outcomes = {T0: outcome("stop_loss", T0 + 3 * H), T0 + 4 * H: None}
        evals = [(False, 100.0)] + [(False, None)] * 4
        signals, calls = self.run_script(evals, outcomes, steps=5, step=H)
        self.assertEqual([s.at for s in signals], [T0, T0 + 4 * H])
        # u3 (= exit_at) blokkeert nog niet: de stop is pas een candle later bekend
        self.assertEqual(calls, [False, False, False, False, True])

    def test_zone_block_lasts_three_days_from_exit_plus_one_candle(self):
        step = pd.Timedelta(hours=12)
        exit_at = T0 + pd.Timedelta(days=1)
        outcomes = {T0: outcome("stop_loss", exit_at), exit_at + step: None}
        n = 12
        evals = [(False, 100.0)] + [(False, None)] * (n - 1)
        signals, calls = self.run_script(evals, outcomes, steps=n, step=step)
        times = [T0 + step * i for i in range(n)]
        failed_at = exit_at + CANDLE
        blocked = [failed_at <= t <= failed_at + pd.Timedelta(days=3) for t in times]
        self.assertTrue(any(blocked) and not all(blocked))
        self.assertEqual(calls, blocked)

    def test_directions_are_independent(self):
        outcomes = {T0: None, T0 + H: None}
        evals = [(True, None), (True, None)]
        signals, calls = self.run_script(
            evals, outcomes, steps=3, step=H, directions=["long", "short", "long"])
        # een open long blokkeert een short niet; de tweede long (u2) is geblokkeerd door de open long
        self.assertEqual([(s.direction, s.at) for s in signals], [("long", T0), ("short", T0 + H)])
        self.assertEqual(self.directions_seen, ["long", "short"])

    def test_failing_prefilter_blocks_new_signal_without_evaluation(self):
        signals, calls = self.run_script([], {}, steps=3, step=H, prefilter=False)
        self.assertEqual((signals, calls), ([], []))

    def test_prefilter_is_skipped_for_open_signal(self):
        trace = []
        # u0 voorfilter ok -> onbevestigd signaal; u1 voorfilter faalt maar het signaal is open: wordt toch beoordeeld
        signals, calls = self.run_script([(False, None), (True, None)], {T0: None, T0 + H: None}, steps=2, step=H,
                                         prefilter=[True, False], trace=trace)
        self.assertEqual(trace, [("ETH", "long", T0, False), ("ETH", "long", T0 + H, True)])
        self.assertEqual([(s.at, s.confirmed) for s in signals], [(T0 + H, True)])

    def test_trace_does_not_change_result(self):
        outcomes = {T0: outcome("take_profit", T0 + 3 * H), T0 + 4 * H: None}
        a, _ = self.run_script([(True, None), (True, None)], dict(outcomes), steps=5, step=H)
        trace = []
        b, _ = self.run_script([(True, None), (True, None)], dict(outcomes), steps=5, step=H, trace=trace)
        self.assertEqual(a, b)
        self.assertEqual([t[2] for t in trace], [T0, T0 + 4 * H])


if __name__ == "__main__":
    unittest.main()
