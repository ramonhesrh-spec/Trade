import unittest
from unittest import mock

import pandas as pd

from app import config
from app.replay import engine
from tests.replay.fixtures import make_base


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.base = {"BTC": make_base(days=60, seed=1), "ETH": make_base(days=60, seed=2, start_price=50.0)}
        self.start = pd.Timestamp("2026-02-05", tz="UTC")
        self.end = pd.Timestamp("2026-02-20", tz="UTC")

    def run_engine(self, **kw):
        with mock.patch.object(config, "ENABLE_ADVANCED_FACTORS", True):
            return engine.replay_day_trading("ETH", self.base, self.start, self.end, **kw)

    def test_signals_are_in_range_and_have_levels(self):
        signals = self.run_engine(step=pd.Timedelta(hours=4))
        self.assertGreater(len(signals), 0)
        for s in signals:
            self.assertGreaterEqual(s.at, self.start)
            self.assertLessEqual(s.at, self.end)
            self.assertNotEqual(s.stop, s.entry)
            self.assertIn(s.direction, ("long", "short"))

    def test_one_open_signal_per_direction(self):
        signals = self.run_engine(step=pd.Timedelta(hours=2))
        pairs = 0
        for direction in ("long", "short"):
            own = sorted([s for s in signals if s.direction == direction], key=lambda s: s.at)
            for a, b in zip(own, own[1:]):
                # een vervangen onbevestigd signaal is uit de lijst; wat overblijft overlapt dus nooit
                self.assertIsNotNone(a.outcome, "een signaal zonder uitkomst moet het laatste van zijn richting zijn")
                self.assertGreaterEqual(b.at, a.outcome.exit_at)
                pairs += 1
        self.assertGreater(pairs, 0)

    def test_deterministic(self):
        a = self.run_engine(step=pd.Timedelta(hours=4))
        b = self.run_engine(step=pd.Timedelta(hours=4))
        self.assertEqual([(s.at, s.direction, s.confirmed) for s in a], [(s.at, s.direction, s.confirmed) for s in b])


if __name__ == "__main__":
    unittest.main()
