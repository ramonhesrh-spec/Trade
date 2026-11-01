"""Onderdeel A: Bewijs toont per focus-soort bruto én netto R, met de kostenregel van track_record (kosten per rondreis gedeeld door de
stopafstand) en de kostenvoet uit config.TRACK_RECORD_COST_PCT in de uitleg. Het Logboek blijft bruto en zegt dat erbij."""
import unittest
from unittest import mock

from app import config, track_record
from tests.test_web_focus import Base, signal


def row(outcome, price=100.0, stop=99.0, take=102.0, trade_type="zone_radar"):
    return {"price": price, "stop_loss": stop, "take_profit": take, "auto_outcome": outcome, "trade_type": trade_type, "message_id": None,
            "created_at": "2026-10-30T10:00:00+00:00", "auto_outcome_at": "2026-10-30T12:00:00+00:00"}


class CostSummaryTest(unittest.TestCase):
    def test_summary_carries_gross_and_net_totals_and_the_cost_per_trade(self):
        rows = [row("take_profit"), row("stop_loss")]
        entry = next(e for e in track_record.summarize(rows, 0.06) if e["trade_type"] == "zone_radar")
        self.assertAlmostEqual(entry["gross_total"], 1.0)                 # +2R en -1R
        self.assertAlmostEqual(entry["net_total"], 1.0 - 2 * 0.06)        # 0,06% kosten op een stop van 1% = 0,06R per trade
        self.assertAlmostEqual(entry["avg_cost_r"], 0.06)

    def test_no_resolved_trade_has_no_cost(self):
        entry = next(e for e in track_record.summarize([row(None)], 0.06) if e["trade_type"] == "zone_radar")
        self.assertIsNone(entry["gross_total"])
        self.assertIsNone(entry["avg_cost_r"])

    def test_cost_text_names_the_rate_and_the_stop_distance(self):
        self.assertEqual(track_record.cost_text(0.06), "netto na 0,06% kosten per rondreis, omgerekend naar R met de stopafstand")


class BewijsShowsGrossAndNetTest(Base):
    def test_a_focus_type_shows_gross_and_net_side_by_side(self):
        signal("SOL", "zone_radar", "take_profit")
        signal("SOL", "zone_radar", "stop_loss")
        with mock.patch.object(config, "TRACK_RECORD_COST_PCT", 0.06):
            html = self.client.get("/bewijs").text
        self.assertIn("Bruto per trade", html)
        self.assertIn("+0,50R", html)                                     # (2 - 1) / 2
        self.assertIn("Netto per trade", html)
        self.assertIn("+0,44R", html)                                     # 0,50 - 0,06
        self.assertIn("Kosten per trade", html)
        self.assertIn("netto na 0,06% kosten per rondreis, omgerekend naar R met de stopafstand", html)

    def test_the_logbook_says_its_r_is_gross(self):
        html = self.client.get("/signalen").text
        self.assertIn("bruto, zonder kosten", html)


if __name__ == "__main__":
    unittest.main()
