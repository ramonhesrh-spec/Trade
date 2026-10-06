import json
import unittest
from datetime import datetime, timedelta, timezone

from app import kans_view, setup_chart

T0 = datetime(2026, 3, 2, tzinfo=timezone.utc)


def candle(i, close=100.0):
    return [(T0 + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, close]


FIRED = {"entry": 100.0, "stop": 101.0, "targets": [98.0, 97.0, 96.0], "hits": 2, "closed": True, "at": candle(30)[0],
         "events": [{"at": candle(30)[0], "text": "Limiet geraakt, de trade loopt"}, {"at": candle(32)[0], "text": "T1 geraakt (2.0R)"},
                    {"at": candle(34)[0], "text": "T2 geraakt (3.0R)"}, {"at": candle(36)[0], "text": "Stop op de instap geraakt, break-even"}]}


class KansViewTests(unittest.TestCase):
    def test_event_levels_follow_limit_targets_and_entry(self):
        levels = [(e["text"][:2], e["level"]) for e in kans_view._event_levels(FIRED)]
        self.assertEqual(levels, [("Li", 100.0), ("T1", 98.0), ("T2", 97.0), ("St", 100.0)])      # break-even stop ligt op de instap
        self.assertEqual(kans_view._event_levels({**FIRED, "events": [{"at": candle(31)[0], "text": "Stop geraakt"}]})[0]["level"], 101.0)

    def test_chart_draws_event_dots_and_extends_snapshot_with_new_candles(self):
        setup = {"coin": "BTC", "direction": "short", "kind": "RANGE", "line_a": 100.0, "line_slope": 0.0, "p1_at": candle(2)[0], "break_at": candle(20)[0],
                 "plan": json.dumps({"level": 100.0, "stop": 101.0, "targets": [98.0, 97.0, 96.0], "targets_r": [2.0, 3.0, 4.0],
                                     "candles": [candle(i) for i in range(30)], "fired": FIRED})}
        signal = {"direction": "short", "coin": "BTC", "price": 100.0, "stop_loss": 101.0, "take_profit": 97.0}
        svg = kans_view.chart(signal, setup, [candle(i) for i in range(30, 40)], 99.0)
        self.assertEqual(svg.count('class="sc-event"'), 4)
        self.assertEqual(svg.count('class="sc-body'), 40)                     # 30 uit de momentopname plus 10 nieuwe candles

    def test_timeline_orders_events_and_adds_outcome_for_plain_signals(self):
        signal = {"created_at": candle(5)[0], "auto_outcome": "take_profit", "auto_outcome_at": candle(9)[0]}
        texts = [e["text"] for e in kans_view.timeline(signal, None)]
        self.assertEqual(texts, ["Gemeld", "Doel geraakt"])

    def test_trade_svg_labels_entry_and_goal(self):
        svg = setup_chart.trade_svg([candle(i) for i in range(30)], "long", "ETH", 100.0, 99.0, 102.0, 100.4)
        self.assertIn("Instap 100", svg)
        self.assertIn("Doel 102", svg)


if __name__ == "__main__":
    unittest.main()
