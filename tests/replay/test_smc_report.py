import unittest

import pandas as pd

from app.replay import smc_report
from app.replay.outcome import Outcome
from app.replay.smc_engine import SmcFunnelEvent, SmcSignal


def sig(at, result, r_net, r_gross, minutes, entry=100.0, stop=99.0, coin="ETH"):
    t0 = pd.Timestamp(at, tz="UTC")
    exit_at = t0 + pd.Timedelta(minutes=minutes)
    return SmcSignal(coin, "long", t0, entry, stop, 102.0, 1, Outcome(result, exit_at, 100.0, r_gross, r_net))


class PerformanceTest(unittest.TestCase):
    def test_basic_stats_and_speed(self):
        signals = [sig("2026-01-01 10:00", "take_profit", 1.7, 2.0, 20), sig("2026-01-02 10:00", "stop_loss", -1.3, -1.0, 90),
                   sig("2026-01-03 10:00", "stop_loss", -1.3, -1.0, 30), sig("2026-01-04 10:00", "expired", 0.1, 0.3, 2880)]
        p = smc_report.performance(signals)
        self.assertEqual((p["n"], p["take_profit"], p["stop_loss"], p["expired"]), (4, 1, 2, 1))
        self.assertAlmostEqual(p["winrate"], 1 / 3)
        self.assertAlmostEqual(p["expectancy_gross"], (2.0 - 1.0 - 1.0 + 0.3) / 4)
        self.assertEqual(p["median_minutes"], 60.0)
        self.assertAlmostEqual(p["share_within_60m"], 2 / 4)

    def test_breakeven_cost(self):
        # gemiddelde bruto R 0,1, kosten per 1% per kant = 2 * 100/1/100 = 2R per 1% => 0,05% per kant
        signals = [sig("2026-01-01 10:00", "take_profit", 0.0, 1.1, 10), sig("2026-01-02 10:00", "stop_loss", 0.0, -0.9, 10)]
        p = smc_report.performance(signals)
        self.assertAlmostEqual(p["breakeven_cost_pct"], 0.1 / 2.0, places=6)

    def test_none_without_trades_or_edge(self):
        self.assertIsNone(smc_report.performance([])["breakeven_cost_pct"])
        losing = [sig("2026-01-01 10:00", "stop_loss", -1.3, -1.0, 10)]
        self.assertIsNone(smc_report.performance(losing)["breakeven_cost_pct"])


class FunnelTest(unittest.TestCase):
    def test_counts_by_end_state_and_reasons(self):
        setups = [
            {"id": 1, "signal_id": 1, "invalidated_at": None, "ended_because": None},
            {"id": 2, "signal_id": None, "invalidated_at": "x", "ended_because": "vervallen"},
            {"id": 3, "signal_id": None, "invalidated_at": "x", "ended_because": "doorbraak"},
            {"id": 4, "signal_id": None, "invalidated_at": "x", "ended_because": "tegenrichting"},
            {"id": 5, "signal_id": None, "invalidated_at": None, "ended_because": None},
        ]
        t = pd.Timestamp("2026-01-01", tz="UTC")
        events = [SmcFunnelEvent(t, "ETH", "long", "geen_sweep"), SmcFunnelEvent(t, "ETH", "long", "geen_sweep"),
                  SmcFunnelEvent(t, "ETH", "long", "afgewezen_geen_signaal", "entry_slechter_dan_sniper"),
                  SmcFunnelEvent(t, "ETH", None, "te_weinig_historie"), SmcFunnelEvent(t, "ETH", None, "te_weinig_historie")]
        f = smc_report.funnel_summary(setups, events)
        self.assertEqual((f["gebouwd"], f["signaal"], f["vervallen"], f["doorbroken"], f["tegenrichting"], f["nog_bouwend"]),
                         (5, 1, 1, 1, 1, 1))
        self.assertEqual(f["skip"], {"geen_sweep": 2})
        self.assertEqual(f["te_weinig_historie"], 2)
        self.assertEqual(f["afgewezen_geen_signaal"], {"entry_slechter_dan_sniper": 1})


class FormatTest(unittest.TestCase):
    def test_report_mentions_sections(self):
        signals = [sig("2026-01-01 10:00", "take_profit", 1.7, 2.0, 20), sig("2026-06-01 10:00", "stop_loss", -1.3, -1.0, 30)]
        text = smc_report.format_smc_report(signals, [], [], notes=("pushmeldingen niet nagebootst",))
        events = [SmcFunnelEvent(signals[0].at, "ETH", None, "te_weinig_historie")]
        text = smc_report.format_smc_report(signals, [], events, notes=("pushmeldingen niet nagebootst",))
        self.assertIn("te weinig 30m-historie", text)
        for needle in ("Trechter", "Prestaties", "snelheid", "train", "test", "ETH", "pushmeldingen niet nagebootst"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
