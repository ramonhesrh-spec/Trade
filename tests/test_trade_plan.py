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


class StripTests(unittest.TestCase):
    def pct(self, html, cls, prop="left"):
        return float(re.search(rf'class="strip-{cls}"[^>]*style="[^"]*{prop}:([\d.]+)%', html).group(1))

    def now_pct(self, html):
        return float(re.search(r'data-strip="dot" style="left:([\d.]+)%', html).group(1))

    def test_long_posities_stop_links_doel_rechts(self):
        h = tp.strip_html("long", 97.0, 106.0, 100.0, price=101.5)
        self.assertAlmostEqual(self.pct(h, "tick"), 33.3, places=1)
        self.assertAlmostEqual(self.now_pct(h), 50.0, places=1)
        self.assertLess(h.index("strip-box-stop"), h.index("strip-box-instap"))
        self.assertLess(h.index("strip-box-instap"), h.index("strip-box-take"))

    def test_short_heeft_dezelfde_volgorde_met_omgekeerde_prijzen(self):
        h = tp.strip_html("short", 103.0, 94.0, 100.0, price=98.5)
        self.assertAlmostEqual(self.pct(h, "tick"), 33.3, places=1)
        self.assertAlmostEqual(self.now_pct(h), 50.0, places=1)
        self.assertLess(h.index("103.00"), h.index("100.00"))
        self.assertLess(h.index("100.00"), h.index("94.00"))

    def test_koers_voorbij_doel_en_stop_blijft_aan_de_rand_met_label(self):
        h = tp.strip_html("long", 97.0, 106.0, 100.0, price=120.0)
        self.assertEqual(self.now_pct(h), 100.0)
        self.assertIn("voorbij doel", h)
        h = tp.strip_html("long", 97.0, 106.0, 100.0, price=90.0)
        self.assertEqual(self.now_pct(h), 0.0)
        self.assertIn("voorbij stop", h)
        h = tp.strip_html("short", 103.0, 94.0, 100.0, price=110.0)
        self.assertEqual(self.now_pct(h), 0.0)
        self.assertIn("voorbij stop", h)
        self.assertIn("Nu 110.00", h)

    def test_binnen_het_bereik_geen_voorbij_label(self):
        self.assertNotIn("voorbij", tp.strip_html("long", 97.0, 106.0, 100.0, price=101.0))

    def test_zone_alleen_als_hij_breed_genoeg_is(self):
        wide = tp.strip_html("long", 97.0, 106.0, 100.0, zone_low=98.0, zone_high=100.0)
        self.assertIn("strip-zone", wide)
        self.assertAlmostEqual(self.pct(wide, "zone", "width"), 22.2, places=1)
        thin = tp.strip_html("long", 80.0, 120.0, 100.0, zone_low=99.9, zone_high=100.0)
        self.assertNotIn("strip-zone", thin)
        self.assertNotIn("stroke-dasharray", thin)

    def test_entry_of_limiet_als_label(self):
        self.assertIn("limiet", tp.strip_html("long", 97.0, 106.0, 100.0))
        h = tp.strip_html("long", 97.0, 106.0, 100.5, price=101.0, entry=100.5)
        self.assertIn("entry", h)
        self.assertNotIn("limiet", h)
        self.assertIn("100.50", h)
        self.assertIn("Nu 101.00  ·  +0,1R", h)      # (101 - 100.5) / 3.5 = 0.14

    def test_risico_en_rr_regel_met_decimaalkomma(self):
        h = tp.strip_html("long", 99.6, 101.12, 100.0)
        self.assertIn("Risico 0,40%  ·  Doel 2,8R", h)

    def test_volledige_prijzen_in_tekst_en_aria_label(self):
        h = tp.strip_html("long", 81449.89, 82700.82, 81777.0, price=82875.17, zone_low=81740.01, zone_high=81777.0)
        for text in ("81449.89", "81777.00", "82700.82", "Nu 82875.17"):
            self.assertIn(text, h)
        self.assertRegex(h, r'aria-label="Stop 81449.89, instap 81777.00[^"]*doel 82700.82, koers 82875.17')

    def test_geen_prijs_geen_stip(self):
        h = tp.strip_html("short", 103.0, 94.0, 100.0)
        self.assertNotIn("strip-dot", h)
        self.assertNotIn("Nu ", h)

    def test_gedegenereerd_valt_terug_op_drie_vakken_zonder_balk(self):
        for args in ((100.0, 106.0, 100.0), (97.0, 100.0, 100.0), (100.0, 100.0, 100.0), (97.0, 99.0, 100.0)):
            h = tp.strip_html("long", args[0], args[1], args[2], price=101.0, zone_low=99.0, zone_high=100.0)
            self.assertNotIn("strip-bar", h)
            self.assertNotIn("strip-dot", h)
            self.assertNotIn("Risico", h)
            self.assertEqual(h.count("strip-box "), 3)
            self.assertNotIn("nan", h.lower())
            self.assertNotIn("inf", h.lower())

    def test_kleine_prijzen_krijgen_vier_decimalen(self):
        h = tp.strip_html("long", 0.0912, 0.101, 0.0950)
        self.assertIn("0.0912", h)


if __name__ == "__main__":
    unittest.main()
