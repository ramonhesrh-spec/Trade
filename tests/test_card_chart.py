"""De eigen kaartgrafiek van Zone-radar en Zone-sweep op Kansen (app/card_chart.py, setup_chart.zone_svg): de tekenstijl van de galerij, met de
zone als vlak vanaf de ontstaanscandle, markeringen op de candles die ertoe doen en lijnen met naam en prijs rechts."""
import re
import unittest
from datetime import datetime, timezone

from app import card_chart, setup_chart

T0 = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp())
H1 = 3600


def candles(n, start=T0, step=H1, base=100.0):
    return [[start + i * step, base, base + 1.0, base - 1.0, base + 0.3] for i in range(n)]


ZR = {"id": 8, "coin": "BTC", "direction": "short", "tf": "1h", "zone_key": "1h:bear:2026-10-21 05:00:00", "zone_low": 100.5, "zone_high": 101.0,
      "stop_loss": 101.3, "take_profit": 97.0, "rr": 3.0, "target_tf": "4h", "target_low": 96.5, "target_high": 97.0,
      "created_at": "2026-10-22T10:00:00+00:00"}
ZS = {"id": 4, "coin": "SOL", "direction": "long", "tf": "1h", "zone_key": "1h:bull:2026-10-21 03:00:00", "zone_low": 99.0, "zone_high": 99.5,
      "zone_at": "2026-10-21T03:00:00+00:00", "sweep_at": "2026-10-22T08:00:00+00:00", "extreme": 98.6, "placed_at": "2026-10-22T10:00:00+00:00",
      "limit_price": 99.4, "stop_loss": 98.5, "take_profit": 102.0, "rr": 2.9, "target_tf": "1h", "target_low": 102.0, "target_high": 102.4,
      "range_high": 103.0, "range_low": 98.0}


class WindowTests(unittest.TestCase):
    def test_shows_the_origin_candle_with_a_few_before(self):
        rows = candles(200)
        start = card_chart.window(rows, T0 + 150 * H1)
        self.assertEqual(rows[start][0], T0 + (150 - card_chart.LEAD_BARS) * H1)

    def test_at_least_min_bars_for_a_young_zone(self):
        rows = candles(200)
        self.assertEqual(len(rows) - card_chart.window(rows, T0 + 199 * H1), card_chart.MIN_BARS)

    def test_an_old_zone_is_capped_and_clamped_not_dropped(self):
        rows = candles(500)
        self.assertEqual(len(rows) - card_chart.window(rows, T0), card_chart.MAX_BARS)
        self.assertEqual(len(rows) - card_chart.window(rows, None), card_chart.MIN_BARS)

    def test_candle_tf_for_the_cache(self):
        self.assertEqual([card_chart.candle_tf(t) for t in ("1h", "2h", "4h", "x")], ["1h", "1h", "4h", "1h"])


class ZoneRadarSvgTests(unittest.TestCase):
    def setUp(self):
        self.svg = card_chart.zone_radar_svg(ZR, candles(80), 99.8)

    def test_draws_zone_target_zone_marker_and_named_lines(self):
        for part in ('class="sc is-card"', "sc-zone", "sc-zone is-target", "sc-mark", "sc-limit", "sc-stop", "sc-target", "sc-price"):
            self.assertIn(part, self.svg)
        for label in ("Aanbod 1u", "Doelzone 4u", "Limiet 100,50", "Stop 101,30", "Doel 97,00", "Ontstaan"):
            self.assertIn(label, self.svg)
        self.assertNotIn("sc-range", self.svg)                                   # geen range-doos: dat is de range sweep

    def test_live_js_can_move_the_price_line(self):
        self.assertIn('data-chart-coin="BTC"', self.svg)
        self.assertIn('data-level="100.5"', self.svg)

    def test_zone_starts_at_the_origin_candle(self):
        zone = float(re.search(r'<rect class="sc-zone" x="([\d.]+)"', self.svg).group(1))
        mark = float(re.search(r'<circle class="sc-mark" cx="([\d.]+)"', self.svg).group(1))
        self.assertAlmostEqual(zone, mark, delta=0.2)                           # het vlak begint op de candle met de markering
        self.assertGreater(mark, setup_chart.CARD_PAD_L + 3 * 4)                 # niet tegen de linkerrand: er staan candles vóór het ontstaan

    def test_everything_inside_the_viewbox(self):
        for m in re.finditer(r'<rect[^>]* x="(-?[\d.]+)"[^>]* y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"', self.svg):
            x, y, w, h = map(float, m.groups())
            self.assertGreaterEqual(x, -0.1)
            self.assertLessEqual(x + w, setup_chart.CARD_W + 0.1)
            self.assertGreaterEqual(y, -0.1)
            self.assertLessEqual(y + h, setup_chart.CARD_H + 0.1)

    def test_no_candles_no_svg(self):
        self.assertEqual(card_chart.zone_radar_svg(ZR, [], 99.8), "")


class ZoneSweepSvgTests(unittest.TestCase):
    def test_draws_the_prick_and_the_recovery(self):
        svg = card_chart.zone_sweep_svg(ZS, candles(80), 99.9)
        for label in ("Vraag 1u", "Prik", "Herstel", "Limiet 99,40", "Stop 98,50", "Doel 102,00", "Doelzone 1u"):
            self.assertIn(label, svg)
        self.assertEqual(svg.count('class="sc-mark"'), 3)                       # ontstaan, prik, herstel

    def test_without_target_no_goal_line(self):
        svg = card_chart.zone_sweep_svg({**ZS, "take_profit": None, "rr": None, "target_tf": None, "target_low": None, "target_high": None},
                                        candles(80), 99.9)
        self.assertNotIn("Doel", svg)
        self.assertIn("Stop 98,50", svg)


PR = {"id": 3, "coin": "ETH", "direction": "long", "period": "day", "period_start": "2026-10-21T00:00:00+00:00", "level": 99.5,
      "limit_price": 99.5, "stop_loss": 99.0, "take_profit": 102.0, "rr": 5.0, "target_kind": "poc", "target_text": "dag-POC 22 okt",
      "target_tf": None, "target_low": None, "target_high": None, "created_at": "2026-10-23T10:00:00+00:00"}


class PocRadarSvgTests(unittest.TestCase):
    def test_lines_with_name_and_price_and_no_zone(self):
        svg = card_chart.poc_radar_svg(PR, candles(60), 100.4)
        for label in ("Limiet op POC 99,50", "Stop 99,00", "Doel 102,00", "Dag-POC 21 okt"):
            self.assertIn(label, svg)
        self.assertNotIn('class="sc-zone"', svg)
        self.assertEqual(svg.count('class="sc-mark"'), 1)                       # het begin van de periode

    def test_week_poc_and_no_target(self):
        svg = card_chart.poc_radar_svg({**PR, "period": "week", "period_start": "2026-10-12T00:00:00+00:00", "take_profit": None, "rr": None},
                                       candles(60, step=4 * H1, start=T0 - 200 * H1), 100.4)
        self.assertIn("Week-POC week 42", svg)
        self.assertNotIn("Doel", svg)

    def test_chart_tf(self):
        self.assertEqual(card_chart.poc_tf("day"), "1h")
        self.assertEqual(card_chart.poc_tf("week"), "4h")


if __name__ == "__main__":
    unittest.main()
