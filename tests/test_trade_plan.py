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


class ChartSpecTests(unittest.TestCase):
    def test_setup_geeft_getallen_en_leesbare_tekst(self):
        spec = tp.chart_spec("long", 97.0, 106.0, 100.0, price=101.5, zone_low=99.0, zone_high=100.0)
        self.assertEqual({k: spec[k] for k in ("direction", "stop", "take", "limit", "zone_low", "zone_high", "entry", "price")},
                         {"direction": "long", "stop": 97.0, "take": 106.0, "limit": 100.0, "zone_low": 99.0, "zone_high": 100.0,
                          "entry": None, "price": 101.5})
        self.assertEqual(spec["label"], "Long-plan: Doel 106.00, Stop 97.0000, Limiet 100.00, zone 99.0000 tot 100.00, Nu 101.50")

    def test_open_trade_noemt_entry_in_plaats_van_limiet_en_prijs_is_optioneel(self):
        spec = tp.chart_spec("short", 103.0, 94.0, 100.0, entry=100.0)
        self.assertIn("Entry 100.00", spec["label"])
        self.assertNotIn("Limiet", spec["label"])
        self.assertNotIn("Nu", spec["label"])
        self.assertIsNone(spec["price"])
