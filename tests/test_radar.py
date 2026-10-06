import unittest

from app import radar

SETUP = {"id": 7, "coin": "XRP", "direction": "long", "zone_low": 99.0, "zone_high": 100.0,
         "preview_stop_loss": 97.0, "preview_take_profit": 106.0, "created_at": "2026-10-05T10:00:00+00:00"}
SIGNAL = {"id": 3, "coin": "ETH", "direction": "short", "price": 100.0, "stop_loss": 103.0, "take_profit": 94.0,
          "created_at": "2026-10-05T10:00:00+00:00"}


class RadarTests(unittest.TestCase):
    def test_setup_kaart_met_status_afstand_en_ladder(self):
        card = radar.setup_card(SETUP, 102.0)
        self.assertEqual(card["key"], "setup:7")
        self.assertEqual(card["state"], "wacht")
        self.assertAlmostEqual(card["distance_pct"], 2.0)
        self.assertAlmostEqual(card["plan"].rr, 2.0)
        self.assertIn("<svg", str(card["ladder"]))
        self.assertIn("Nu 102.00", str(card["ladder"]))

    def test_status_in_zone_en_zonder_koers(self):
        self.assertEqual(radar.setup_card(SETUP, 99.5)["state"], "in_zone")
        no_price = radar.setup_card(SETUP, None)
        self.assertIsNone(no_price["state"])
        self.assertIsNone(no_price["distance_pct"])
        self.assertEqual(no_price["state_label"], "Koers wordt opgehaald")
        self.assertNotIn("Nu ", str(no_price["ladder"]))

    def test_stop_onder_de_ruisgrens_wordt_gemarkeerd_als_te_klein(self):
        self.assertFalse(radar.setup_card(SETUP, 102.0)["too_tight"])            # stop 3% van de limiet
        tight = dict(SETUP, preview_stop_loss=99.95)                               # stop 0,05% van de limiet
        self.assertTrue(radar.setup_card(tight, 102.0)["too_tight"])

    def test_setup_met_onmogelijk_plan_krijgt_geen_kaart(self):
        bad = dict(SETUP, preview_stop_loss=100.5)
        self.assertIsNone(radar.setup_card(bad, 102.0))

    def test_signaalkaart_met_live_r(self):
        card = radar.signal_card(SIGNAL, 97.0)          # short: koers 3 omlaag = +1R
        self.assertAlmostEqual(card["live_r"], 1.0)
        self.assertEqual(card["state"], "open")
        self.assertAlmostEqual(card["rr"], 2.0)
        self.assertIn("Entry 100.00", str(card["ladder"]))
        self.assertIsNone(radar.signal_card(dict(SIGNAL, stop_loss=None), 97.0))

    def test_live_payload(self):
        cards = [radar.setup_card(SETUP, 102.0), radar.signal_card(SIGNAL, 97.0)]
        payload = radar.live_payload(cards)
        self.assertEqual(set(payload), {"setup:7", "signal:3"})
        self.assertEqual(payload["setup:7"]["state"], "wacht")
        self.assertAlmostEqual(payload["signal:3"]["live_r"], 1.0)
        self.assertTrue(payload["setup:7"]["ladder"].startswith("<svg"))


if __name__ == "__main__":
    unittest.main()
