import unittest

import pandas as pd

from app.replay import report
from app.replay.engine import ReplaySignal
from app.replay.outcome import Outcome


def sig(at, result, r_net, confirmed=True, coin="ETH"):
    ts = pd.Timestamp(at, tz="UTC")
    return ReplaySignal(coin, "long", ts, 100.0, 99.0, 102.0, confirmed, "",
                        Outcome(result, ts, 100.0, r_net, r_net))


SIGNALS = [
    sig("2026-01-01", "stop_loss", -1.0), sig("2026-01-02", "stop_loss", -1.0),
    sig("2026-01-03", "take_profit", 2.0), sig("2026-01-04", "expired", 0.2),
    sig("2026-01-05", "stop_loss", -1.0, confirmed=False),
]


class ReportTest(unittest.TestCase):
    def test_confirmed_only_is_default(self):
        self.assertEqual(len(report.to_frame(SIGNALS)), 4)
        self.assertEqual(len(report.to_frame(SIGNALS, confirmed_only=False)), 5)

    def test_summarize(self):
        s = report.summarize(report.to_frame(SIGNALS))
        self.assertEqual((s["n"], s["take_profit"], s["stop_loss"], s["expired"]), (4, 1, 2, 1))
        self.assertAlmostEqual(s["winrate"], 1 / 3)
        self.assertAlmostEqual(s["expectancy_net"], (-1 - 1 + 2 + 0.2) / 4)
        self.assertEqual(s["worst_streak"], 2)

    def test_signals_without_outcome_are_skipped(self):
        open_signal = ReplaySignal("ETH", "long", pd.Timestamp("2026-01-06", tz="UTC"), 1, 1, 1, True, "", None)
        self.assertEqual(len(report.to_frame(SIGNALS + [open_signal])), 4)

    def test_format_report_mentions_split_and_limits(self):
        text = report.format_report(SIGNALS, notes=("zone-cooldown benaderd",))
        self.assertIn("train", text)
        self.assertIn("test", text)
        self.assertIn("zone-cooldown benaderd", text)
        self.assertIn("ETH", text)


if __name__ == "__main__":
    unittest.main()
