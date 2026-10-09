import re
import unittest

from app import trade_plan as tp


class LimitPlanTests(unittest.TestCase):
    def test_long_limiet_op_bovenrand_en_rr_vanaf_die_prijs(self):
        plan = tp.limit_plan("long", 99.0, 100.0, 97.0, 106.0)
        self.assertEqual(plan.limit, 100.0)
        self.assertAlmostEqual(plan.rr, 2.0)          # risico 3, winst 6
        self.assertAlmostEqual(plan.risk_pct, 3.0)

    def test_short_limiet_op_onderrand(self):
        plan = tp.limit_plan("short", 100.0, 101.0, 103.0, 94.0)
        self.assertEqual(plan.limit, 100.0)
        self.assertAlmostEqual(plan.rr, 2.0)          # risico 3, winst 6

    def test_ongeldig_als_stop_of_doel_aan_verkeerde_kant(self):
        self.assertIsNone(tp.limit_plan("long", 99.0, 100.0, 100.5, 106.0))   # stop boven de limiet
        self.assertIsNone(tp.limit_plan("long", 99.0, 100.0, 97.0, 99.5))     # doel onder de limiet
        self.assertIsNone(tp.limit_plan("short", 100.0, 101.0, 99.0, 94.0))
        self.assertIsNone(tp.limit_plan("short", 100.0, 101.0, 103.0, 100.5))

    def test_rr_is_beter_dan_met_marktentry_hoger_in_de_zone(self):
        near = tp.limit_plan("long", 99.0, 100.0, 97.0, 106.0)
        market_rr = abs(106.0 - 101.0) / abs(101.0 - 97.0)
        self.assertGreater(near.rr, market_rr)


class StateTests(unittest.TestCase):
    def test_long(self):
        s = lambda p: tp.plan_state("long", 99.0, 100.0, 97.0, p)
        self.assertEqual(s(102.0), "wacht")
        self.assertEqual(s(100.0), "in_zone")
        self.assertEqual(s(99.0), "in_zone")
        self.assertEqual(s(98.5), "door_zone")
        self.assertEqual(s(97.0), "ongeldig")

    def test_short(self):
        s = lambda p: tp.plan_state("short", 100.0, 101.0, 103.0, p)
        self.assertEqual(s(98.0), "wacht")
        self.assertEqual(s(100.0), "in_zone")
        self.assertEqual(s(101.0), "in_zone")
        self.assertEqual(s(102.0), "door_zone")
        self.assertEqual(s(103.0), "ongeldig")

    def test_afstand_en_live_r(self):
        plan = tp.limit_plan("long", 99.0, 100.0, 97.0, 106.0)
        self.assertAlmostEqual(tp.distance_to_limit_pct(plan, 102.0), 2.0)
        short = tp.limit_plan("short", 100.0, 101.0, 103.0, 94.0)
        self.assertAlmostEqual(tp.distance_to_limit_pct(short, 98.0), 2.0)
        self.assertAlmostEqual(tp.live_r("long", 100.0, 97.0, 103.0), 1.0)
        self.assertAlmostEqual(tp.live_r("short", 100.0, 103.0, 103.0), -1.0)
        self.assertIsNone(tp.live_r("long", 100.0, 100.0, 103.0))


class DoelGeraaktTests(unittest.TestCase):
    def test_long_boven_doel_zonder_vulling(self):
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 106.0, take=106.0), "doel_geraakt")
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 110.0, take=106.0), "doel_geraakt")
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 105.0, take=106.0), "wacht")

    def test_short_onder_doel_zonder_vulling(self):
        self.assertEqual(tp.plan_state("short", 100.0, 101.0, 103.0, 94.0, take=94.0), "doel_geraakt")
        self.assertEqual(tp.plan_state("short", 100.0, 101.0, 103.0, 90.0, take=94.0), "doel_geraakt")
        self.assertEqual(tp.plan_state("short", 100.0, 101.0, 103.0, 95.0, take=94.0), "wacht")

    def test_zonder_take_ongewijzigd(self):
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 110.0), "wacht")
        self.assertEqual(tp.plan_state("short", 100.0, 101.0, 103.0, 90.0), "wacht")

    def test_stop_houdt_voorrang_en_zone_blijft_zone(self):
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 96.0, take=106.0), "ongeldig")
        self.assertEqual(tp.plan_state("short", 100.0, 101.0, 103.0, 104.0, take=94.0), "ongeldig")
        # Een doel dat (door een rare invoer) in of onder de zone ligt, maakt de zone niet moot: de order kan gevuld zijn.
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 99.5, take=99.2), "in_zone")
        self.assertEqual(tp.plan_state("long", 99.0, 100.0, 97.0, 98.0, take=98.5), "door_zone")
        self.assertEqual(tp.plan_state("short", 100.0, 101.0, 103.0, 100.5, take=100.2), "in_zone")

    def test_label(self):
        self.assertEqual(tp.STATE_LABELS["doel_geraakt"], "Doel gehaald zonder dat jouw order vulde")


class LadderTests(unittest.TestCase):
    def y_of(self, svg, css):
        return float(re.search(rf'<line class="ladder-line ladder-{css}"[^>]*y1="([\d.]+)"', svg).group(1))

    def test_long_ladder_volgorde_doel_boven_stop_onder(self):
        svg = tp.ladder_svg("long", 97.0, 106.0, 100.0, price=101.5, zone_low=99.0, zone_high=100.0)
        self.assertLess(self.y_of(svg, "take"), self.y_of(svg, "limit"))
        self.assertLess(self.y_of(svg, "limit"), self.y_of(svg, "stop"))
        self.assertIn("Doel 106.00", svg)
        self.assertIn("Stop 97.00", svg)
        self.assertIn("Nu 101.50", svg)
        self.assertIn("ladder-zone", svg)

    def test_short_ladder_hoogste_prijs_bovenaan(self):
        svg = tp.ladder_svg("short", 103.0, 94.0, 100.0)
        self.assertLess(self.y_of(svg, "stop"), self.y_of(svg, "limit"))
        self.assertLess(self.y_of(svg, "limit"), self.y_of(svg, "take"))
        self.assertNotIn("ladder-price", svg)

    def test_entry_vervangt_limiet_en_prijs_buiten_het_bereik_blijft_binnen_de_svg(self):
        svg = tp.ladder_svg("long", 97.0, 106.0, 100.0, price=120.0, entry=100.5)
        self.assertIn("Entry 100.50", svg)
        self.assertNotIn("Limiet", svg)
        for y in re.findall(r'y1="([\d.]+)"', svg):
            self.assertTrue(0 <= float(y) <= 190)

    def test_labels_van_nabije_niveaus_overlappen_niet_en_lijnen_blijven_op_hun_prijs(self):
        svg = tp.ladder_svg("short", 152.3, 140.3, 150.2, price=150.6, zone_low=150.2, zone_high=151.0)
        ys = sorted(float(y) for y in re.findall(r'<text class="ladder-label[^>]*y="([\d.]+)"', svg))
        for a, b in zip(ys, ys[1:]):
            self.assertGreaterEqual(b - a, tp.LABEL_GAP - 0.2)
        self.assertLessEqual(ys[-1], 190)
        # de limietlijn staat nog steeds op de echte prijs: dichter bij de stop dan bij het doel
        self.assertLess(abs(self.y_of(svg, "limit") - self.y_of(svg, "stop")), abs(self.y_of(svg, "limit") - self.y_of(svg, "take")))

    def test_kleine_prijzen_krijgen_vier_decimalen(self):
        svg = tp.ladder_svg("long", 0.0912, 0.101, 0.0950)
        self.assertIn("Stop 0.0912", svg)


if __name__ == "__main__":
    unittest.main()
