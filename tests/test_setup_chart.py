import re
import unittest

from app import setup_chart
from app.replay import rangesweep as rs
from tests.replay.rangesweep_fixtures import frames


class RangeSweepSvgTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        f = rs.build_frames(b15, b1h, b4h)
        self.sweep = rs.find_setups(f, "1h", "sweep", "ob", "slot", use_htf=False)[0][0]
        self.zone = rs.find_setups(f, "1h", "zone", "split", "slot", use_htf=False)[0][0]
        self.candles = [[r.timestamp.isoformat(), r.open, r.high, r.low, r.close] for r in b1h.itertuples()]

    def test_sweep_draws_every_part(self):
        svg = setup_chart.range_sweep_svg(self.candles[-80:], self.sweep, stop=106.7, price=105.0)
        for cls in ("sc-range", "sc-zone", "sc-sweep", "sc-limit", "sc-stop", "sc-target", "sc-price"):
            self.assertIn(cls, svg)
        self.assertIn("Midden (ref.)", svg)
        self.assertIn("Overkant (ref.)", svg)
        self.assertNotIn("Doel", svg)

    def test_zone_retest_has_no_sweep_and_shows_the_split(self):
        svg = setup_chart.range_sweep_svg(self.candles[:140], self.zone, stop=106.2)
        self.assertNotIn("sc-sweep", svg)
        self.assertIn("Limiet 40%", svg)
        self.assertIn("Limiet 60%", svg)

    def test_no_candles_no_svg(self):
        self.assertEqual(setup_chart.range_sweep_svg([], self.sweep, stop=106.7), "")

    def test_single_leg_is_plain_limit_and_zone_is_named_by_family(self):
        svg = setup_chart.range_sweep_svg(self.candles[-80:], self.sweep, stop=106.7)
        self.assertIn("Limiet 106.19", svg)
        self.assertNotIn("Limiet 40%", svg)
        self.assertIn("Order block", svg)
        zone = setup_chart.range_sweep_svg(self.candles[:140], {**self.zone, "direction": "short", "legs": [(1.0, 105.375)]}, stop=106.2)
        self.assertIn("Aanbod", zone)

    def test_long_setup_labels_demand_and_far_edge_is_the_high(self):
        s = {**self.zone, "direction": "long", "legs": [(1.0, 100.6)]}
        svg = setup_chart.range_sweep_svg(self.candles[:140], s, stop=99.8)
        self.assertIn("Vraag", svg)
        self.assertIn(f"Overkant (ref.) {setup_chart._fmt(s['range_high'])}", svg)

    def test_other_zones_are_drawn_muted_and_everything_stays_in_the_viewbox(self):
        zones = [{"low": 99.975, "high": 100.625, "from": self.candles[44][0], "kind": "bull"}]
        svg = setup_chart.range_sweep_svg(self.candles[-80:], self.sweep, stop=106.7, price=105.0, zones=zones)
        self.assertIn("sc-zone is-other", svg)
        for m in re.finditer(r'<rect[^>]* x="(-?[\d.]+)"[^>]* y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg):
            x, y, w, h = map(float, m.groups())
            self.assertGreaterEqual(x, -0.1)
            self.assertLessEqual(x + w, setup_chart.W + 0.1)
            self.assertGreaterEqual(y, -0.1)
            self.assertLessEqual(y + h, setup_chart.H + 0.1)

    def test_setup_from_before_the_shown_candles_is_clamped_not_dropped(self):
        svg = setup_chart.range_sweep_svg(self.candles[150:], self.sweep, stop=106.7)
        self.assertIn("sc-range", svg)


if __name__ == "__main__":
    unittest.main()
