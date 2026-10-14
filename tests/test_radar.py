import unittest
from datetime import datetime, timezone

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
        self.assertEqual(today.open_chances([], [], [radar.setup_card(SETUP, 107.0)], [], {}, datetime.now(timezone.utc)), [])

    def test_vervallen_en_doorgelopen_plannen_staan_niet_onder_wachten(self):
        stopped = radar.setup_card(SETUP, 90.0)         # voorbij de stop
        self.assertEqual(stopped["state"], "ongeldig")
        self.assertEqual(radar.waiting_cards([stopped]), [])
        self.assertEqual([c["key"] for c in radar.moot_cards([stopped])], ["setup:7"])
        self.assertEqual(radar.waiting_count([SETUP], {"XRP": 90.0}), 0)

    def test_live_payload(self):
        cards = [radar.setup_card(SETUP, 102.0), radar.signal_card(SIGNAL, 97.0)]
        payload = radar.live_payload(cards)
        self.assertEqual(set(payload), {"setup:7", "signal:3"})
        self.assertEqual(payload["setup:7"]["state"], "wacht")
        self.assertAlmostEqual(payload["signal:3"]["live_r"], 1.0)
        self.assertEqual(payload["setup:7"]["chart"]["price"], 102.0)

    def test_kaarten_hebben_kopieerbare_niveaus(self):
        card = radar.setup_card(SETUP, 102.0)
        self.assertEqual([c["text"] for c in card["levels"]], ["100.00", "97.0000", "106.00"])
        self.assertEqual(radar.setup_card(SETUP, 107.0)["levels"], [])           # doel al gehaald: niets meer te kopiëren
        self.assertEqual([c["value"] for c in radar.signal_card(SIGNAL, 99.0)["levels"]], [100.0, 103.0, 94.0])

    def test_afstandsbalk_volgt_de_afstand_tot_de_limiet(self):
        card = radar.setup_card(SETUP, 102.0)                                # 2% van de limiet 100
        self.assertAlmostEqual(card["approach_pct"], 100 - 2 / 3 * 100)
        self.assertIsNone(radar.setup_card(SETUP, None)["approach_pct"])
        self.assertIsNone(radar.signal_card(SIGNAL, 99.0)["approach_pct"])
        payload = radar.live_payload([card])
        self.assertAlmostEqual(payload["setup:7"]["approach_pct"], card["approach_pct"])

    def test_ongeldig_plan_verbergt_de_afstandsbalk(self):
        card = radar.setup_card(SETUP, 96.0)                                 # long, koers onder de stop 97
        self.assertEqual(card["state"], "ongeldig")
        self.assertIsNone(card["approach_pct"])
        self.assertIsNone(radar.live_payload([card])["setup:7"]["approach_pct"])

    def test_in_zone_count_telt_alleen_setups_met_koers_in_de_zone(self):
        other = {**SETUP, "id": 8, "coin": "ETH"}
        self.assertEqual(radar.in_zone_count([SETUP, other], {"XRP": 99.5, "ETH": 102.0}), 1)
        self.assertEqual(radar.in_zone_count([SETUP], {}), 0)                    # zonder koers niets beloven

    def test_in_zone_count_slaat_setups_zonder_limietplan_over(self):
        bad = {**SETUP, "preview_stop_loss": 101.0}                              # stop aan de verkeerde kant: geen kaart op de radar
        self.assertIsNone(radar.setup_card(bad, 99.5))
        self.assertEqual(radar.in_zone_count([bad], {"XRP": 99.5}), 0)


class SparkTests(unittest.TestCase):
    def test_path_spans_the_box_oldest_left(self):
        path = radar.spark_path([1.0, 3.0, 2.0], width=104, height=24)
        self.assertEqual(path, "M2.0,22.0 L52.0,2.0 L102.0,12.0")

    def test_flat_series_is_a_middle_line_and_short_series_is_empty(self):
        self.assertEqual(radar.spark_path([5.0, 5.0], width=104, height=24), "M2.0,12.0 L102.0,12.0")
        self.assertEqual(radar.spark_path([5.0]), "")

    def test_spark_has_change_over_the_period(self):
        s = radar.spark([100.0, 103.0, 102.0])
        self.assertAlmostEqual(s["change_pct"], 2.0)
        self.assertEqual(s["change_text"], "+2,0% 24u")
        self.assertIsNone(radar.spark([100.0]))
        self.assertIsNone(radar.spark([0.0, 1.0]))

    def test_spark_weigert_niet_eindige_koersen(self):
        for bad in (float("nan"), float("inf")):
            self.assertIsNone(radar.spark([100.0, bad, 101.0]))

    def test_spark_afgerond_nul_krijgt_geen_teken_en_geen_kleur(self):
        for last in (100.04, 99.96):
            s = radar.spark([100.0, last])
            self.assertEqual(s["change_text"], "0,0% 24u")
            self.assertEqual(s["change_pct"], 0)
        self.assertEqual(radar.spark([100.0, 99.0])["change_text"], "-1,0% 24u")

    def test_spark_venster_is_vijfentwintig_slotkoersen(self):
        self.assertEqual(radar.SPARK_HOURS, 24)


if __name__ == "__main__":
    unittest.main()
