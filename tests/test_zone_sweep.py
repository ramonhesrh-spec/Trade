"""Zone-sweep als kaart (app/zone_sweep.py): de setup van de detector (app/replay/zonesweep.py) met de stop wick_025, een doel op de rand van de
eerstvolgende tegenovergestelde actieve zone (zone_radar), minstens 2R, anders zonder doel. Synthetische candles in de stijl van
tests/replay/test_zonesweep.py."""
import unittest

import pandas as pd

from app import nu, radar, zone_radar as zr, zone_sweep as zsw
from app.replay import zonesweep as zs
from tests.replay.test_zonesweep import DRIFT, FLAT, PRIK_HERSTEL, UP, ZONE, make_frames

# Een aanbodzone hoog in de grafiek (groene candle 104,0-104,6, daarna een val): het doel van een long uit de vraagzone 99,7-100,3.
HIGH = [(104.0, 104.5, 103.5, 104.0)] * 20 + [(104.0, 104.6, 104.0, 104.5), (104.5, 104.5, 100.0, 100.2)]


def rows_with_target(after=UP):
    return HIGH + [FLAT] * 40 + ZONE + DRIFT + [PRIK_HERSTEL] + after


def rows_without_target(after=UP):
    return [FLAT] * 62 + ZONE + DRIFT + [PRIK_HERSTEL] + after


def setup_and_zones(rows):
    frames = make_frames(rows)
    s = zs.find_setups(frames, "1h", "zone", False)[0][0]
    now = s["placed_at"] + pd.Timedelta(minutes=5)
    return s, zsw.zone_levels(frames, now)


class CardRowTest(unittest.TestCase):
    def test_long_with_a_target_on_the_opposite_zone(self):
        s, zones = setup_and_zones(rows_with_target())
        row = zsw.card_row("BTC", "ZS_1H", s, zones)
        self.assertEqual((row["coin"], row["direction"], row["variant"], row["tf"]), ("BTC", "long", "ZS_1H", "1h"))
        self.assertEqual(row["zone_key"], f"1h:bull:{s['zone_at'].isoformat()}")
        self.assertAlmostEqual(row["limit_price"], 100.3)
        self.assertAlmostEqual(row["stop_loss"], zs.final_stop(s, "wick_025"))
        self.assertEqual(row["stop_name"], "wick_025")
        self.assertAlmostEqual(row["take_profit"], 104.0)
        self.assertAlmostEqual(row["rr"], (104.0 - 100.3) / (100.3 - row["stop_loss"]))
        self.assertEqual((row["target_tf"], row["target_low"], row["target_high"]), ("1h", 104.0, 104.6))
        self.assertEqual(row["placed_at"], s["placed_at"].isoformat())
        self.assertEqual(row["expires_at"], (s["placed_at"] + pd.Timedelta(hours=24)).isoformat())

    def test_without_an_opposite_zone_the_card_has_no_target(self):
        s, zones = setup_and_zones(rows_without_target())
        row = zsw.card_row("BTC", "ZS_1H", s, zones)
        self.assertIsNone(row["take_profit"])
        self.assertIsNone(row["rr"])
        self.assertIsNone(row["target_tf"])

    def test_a_target_under_2r_is_dropped_not_replaced(self):
        s, zones = setup_and_zones(rows_without_target())
        near = zr.ZoneLevel("1h", "bear", 101.0, 101.4, 1.0, "1h:bear:x")
        far = zr.ZoneLevel("4h", "bear", 110.0, 111.0, 1.0, "4h:bear:y")
        row = zsw.card_row("BTC", "ZS_1H", s, zones + [near, far])
        # Alleen de eerstvolgende zone telt: valt die onder 2R, dan geen doel, niet doorzoeken tot er een past.
        self.assertIsNone(row["take_profit"])


class CardTest(unittest.TestCase):
    def row(self, **kw):
        base = {"id": 7, "coin": "BTC", "direction": "long", "variant": "ZS_2H", "tf": "2h", "zone_key": "2h:bull:2026-10-20T08:00:00+00:00",
                "zone_low": 99.7, "zone_high": 100.3, "limit_price": 100.3, "stop_loss": 98.9, "take_profit": 104.0, "rr": 2.6,
                "target_tf": "1h", "target_low": 104.0, "target_high": 104.6, "created_at": "2026-10-27T10:05:00+00:00",
                "placed_at": "2026-10-27T10:00:00+00:00"}
        return {**base, **kw}

    def test_radar_card_has_its_own_key_and_plan(self):
        card = radar.setup_card(zsw.radar_setup(self.row()), 101.0)
        self.assertEqual(card["key"], "zsweep:7")
        self.assertEqual((card["plan"].limit, card["plan"].take), (100.3, 104.0))
        self.assertEqual(card["state"], "wacht")
        self.assertEqual(card["chart"]["zone"]["tf"], "2h")
        self.assertEqual(card["chart"]["zone"]["label"], "Vraagzone 2u")
        self.assertIsNotNone(card["chart"]["zone"]["origin"])
        self.assertEqual(card["chart"]["zone"]["target_label"], "Doelzone 1u")

    def test_limit_inside_the_zone_is_the_plan_limit(self):
        card = radar.setup_card(zsw.radar_setup(self.row(limit_price=100.1)), 100.2)
        self.assertEqual(card["plan"].limit, 100.1)

    def test_card_without_target_shows_entry_and_stop_only(self):
        card = radar.setup_card(zsw.radar_setup(self.row(take_profit=None, rr=None, target_tf=None, target_low=None, target_high=None)), 101.0)
        self.assertIsNotNone(card)
        self.assertIsNone(card["plan"].take)
        self.assertIsNone(card["plan"].rr)
        self.assertEqual([lv["key"] for lv in card["levels"]], ["entry", "stop"])
        self.assertIn("geen doel", card["steps"][2]["title"])
        self.assertNotIn("rr", card["steps"][2])
        self.assertIsNone(card["chart"]["take"])
        self.assertNotIn("Doel", card["chart"]["label"])
        self.assertNotIn("doel", card["action"])

    def test_nu_and_checklist_without_target(self):
        card = radar.setup_card(zsw.radar_setup(self.row(take_profit=None, rr=None)), 100.2)
        item = nu.item_for([card], "zsweep:7")
        self.assertEqual((item["trade_type"], item["untested"]), ("zone_sweep", True))
        self.assertEqual([r["label"] for r in item["rows"]], ["Instap", "Stop"])
        steps = nu.checklist(item)
        self.assertIsNone(steps[3]["value"])
        self.assertIn("kies je zelf", steps[3]["sub"])
        self.assertTrue(nu.SKIP_KEY.match("zsweep:7"))

    def test_nu_with_target(self):
        card = radar.setup_card(zsw.radar_setup(self.row()), 100.2)
        item = nu.item_for([card], "zsweep:7")
        self.assertEqual(item["targets"], [(104.0, card["plan"].rr)])


class AnnounceTest(unittest.TestCase):
    def test_dead_plans_are_not_announced(self):
        row = {"direction": "long", "zone_low": 99.7, "zone_high": 100.3, "stop_loss": 98.9, "take_profit": 104.0}
        self.assertTrue(zsw.alive(row, 101.0))
        self.assertTrue(zsw.alive(row, 100.0))                     # in de zone: de limiet vult meteen
        self.assertFalse(zsw.alive(row, 98.5))                     # voorbij de stop
        self.assertFalse(zsw.alive(row, 104.2))                    # doel al gehaald
        self.assertTrue(zsw.alive({**row, "take_profit": None}, 104.2))
        self.assertTrue(zsw.alive(row, None))                      # zonder koers is er niets dat het plan ongeldig maakt


class TextTest(unittest.TestCase):
    def test_new_card_body_names_limit_stop_target_and_untested(self):
        row = {"direction": "long", "tf": "1h", "zone_low": 99.7, "zone_high": 100.3, "limit_price": 100.3, "stop_loss": 98.9,
               "take_profit": 104.0, "rr": 2.6, "target_tf": "1h"}
        body = zsw.new_card_body(row)
        self.assertIn("Limiet 100.30", body)
        self.assertIn("Stop 98.9000", body)
        self.assertIn("Doel 104.00", body)
        self.assertIn("Ongetest", body)
        no_target = zsw.new_card_body({**row, "take_profit": None, "rr": None, "target_tf": None})
        self.assertIn("geen doel", no_target)
        self.assertNotIn("Take", no_target)


if __name__ == "__main__":
    unittest.main()
