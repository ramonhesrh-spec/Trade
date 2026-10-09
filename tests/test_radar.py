import unittest

from app import radar

SETUP = {"id": 7, "coin": "XRP", "direction": "long", "zone_low": 99.0, "zone_high": 100.0,
         "preview_stop_loss": 97.0, "preview_take_profit": 106.0, "created_at": "2026-10-05T10:00:00+00:00"}
SIGNAL = {"id": 3, "coin": "ETH", "direction": "short", "price": 100.0, "stop_loss": 103.0, "take_profit": 94.0,
          "created_at": "2026-10-05T10:00:00+00:00"}


class RadarTests(unittest.TestCase):
    def test_setup_kaart_met_status_afstand_en_grafiekgegevens(self):
        card = radar.setup_card(SETUP, 102.0)
        self.assertEqual(card["key"], "setup:7")
        self.assertEqual(card["state"], "wacht")
        self.assertAlmostEqual(card["distance_pct"], 2.0)
        self.assertAlmostEqual(card["plan"].rr, 2.0)
        self.assertIn("Nu 102.00", card["chart"]["label"])
        self.assertEqual(card["chart"]["price"], 102.0)
        self.assertEqual((card["chart"]["zone_low"], card["chart"]["zone_high"]), (SETUP["zone_low"], SETUP["zone_high"]))

    def test_status_in_zone_en_zonder_koers(self):
        self.assertEqual(radar.setup_card(SETUP, 99.5)["state"], "in_zone")
        no_price = radar.setup_card(SETUP, None)
        self.assertIsNone(no_price["state"])
        self.assertIsNone(no_price["distance_pct"])
        self.assertEqual(no_price["state_label"], "Koers wordt opgehaald")
        self.assertNotIn("Nu ", no_price["chart"]["label"])

    def test_setup_met_onmogelijk_plan_krijgt_geen_kaart(self):
        bad = dict(SETUP, preview_stop_loss=100.5)
        self.assertIsNone(radar.setup_card(bad, 102.0))

    def test_signaalkaart_met_live_r(self):
        card = radar.signal_card(SIGNAL, 97.0)          # short: koers 3 omlaag = +1R
        self.assertAlmostEqual(card["live_r"], 1.0)
        self.assertEqual(card["state"], "open")
        self.assertAlmostEqual(card["rr"], 2.0)
        self.assertIn("Entry 100.00", card["chart"]["label"])
        self.assertEqual(card["chart"]["entry"], 100.0)
        self.assertIsNone(radar.signal_card(dict(SIGNAL, stop_loss=None), 97.0))

    def test_doel_gehaald_zonder_vulling_is_een_stille_kaart(self):
        card = radar.setup_card(SETUP, 107.0)
        self.assertEqual(card["state"], "doel_geraakt")
        self.assertEqual(card["state_label"], "Doel gehaald zonder dat jouw order vulde")
        self.assertEqual(card["steps"], [])
        self.assertIsNone(card["chart"])
        self.assertIsNone(card["distance_pct"])
        short = dict(SETUP, direction="short", zone_low=100.0, zone_high=101.0, preview_stop_loss=103.0, preview_take_profit=94.0)
        self.assertEqual(radar.setup_card(short, 93.0)["state"], "doel_geraakt")

    def test_groepering_en_telling_sluiten_doel_geraakt_uit(self):
        moot = radar.setup_card(SETUP, 107.0)
        waiting = radar.setup_card(dict(SETUP, id=8), 102.0)
        in_zone = radar.setup_card(dict(SETUP, id=9), 99.5)
        self.assertEqual([c["key"] for c in radar.waiting_cards([moot, waiting, in_zone])], ["setup:8", "setup:9"])
        self.assertEqual([c["key"] for c in radar.moot_cards([moot, waiting, in_zone])], ["setup:7"])
        self.assertEqual(radar.waiting_count([SETUP, dict(SETUP, id=8)], {"XRP": 107.0}), 0)
        self.assertEqual(radar.waiting_count([SETUP, dict(SETUP, id=8, coin="ETH")], {"XRP": 107.0}), 1)
        self.assertEqual(radar.waiting_count([SETUP], {}), 1)

    def test_doel_gehaald_telt_niet_mee_voor_dichtstbijzijnde_kans(self):
        from app import today
        self.assertIsNone(today.nearest_chance([], [], [radar.setup_card(SETUP, 107.0)]))

    def test_live_payload(self):
        cards = [radar.setup_card(SETUP, 102.0), radar.signal_card(SIGNAL, 97.0)]
        payload = radar.live_payload(cards)
        self.assertEqual(set(payload), {"setup:7", "signal:3"})
        self.assertEqual(payload["setup:7"]["state"], "wacht")
        self.assertAlmostEqual(payload["signal:3"]["live_r"], 1.0)
        self.assertEqual(payload["setup:7"]["chart"]["price"], 102.0)


if __name__ == "__main__":
    unittest.main()
