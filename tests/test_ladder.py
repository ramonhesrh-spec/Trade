"""De prijsladder (app/ladder.py): boven is duurder, onder goedkoper; elk niveau op zijn echte plek, de afstand als gemeten waarde."""
import unittest

from app import ladder


class BoundsTests(unittest.TestCase):
    def test_marge_boven_en_onder_over_alle_niveaus(self):
        hi, lo = ladder.bounds([100.0, 110.0, None, 105.0], margin=0.1)
        self.assertAlmostEqual(hi, 111.0)
        self.assertAlmostEqual(lo, 99.0)

    def test_een_enkel_niveau_krijgt_toch_een_schaal(self):
        hi, lo = ladder.bounds([50.0])
        self.assertGreater(hi, 50.0)
        self.assertLess(lo, 50.0)

    def test_zonder_niveaus_geen_schaal(self):
        with self.assertRaises(ValueError):
            ladder.bounds([None])


class YTests(unittest.TestCase):
    def test_boven_is_duurder(self):
        self.assertEqual(ladder.y_pct(110.0, 110.0, 100.0), 0.0)
        self.assertEqual(ladder.y_pct(100.0, 110.0, 100.0), 100.0)
        self.assertAlmostEqual(ladder.y_pct(107.5, 110.0, 100.0), 25.0)

    def test_buiten_de_schaal_blijft_de_lijn_op_de_rand(self):
        self.assertEqual(ladder.y_pct(130.0, 110.0, 100.0), 0.0)
        self.assertEqual(ladder.y_pct(90.0, 110.0, 100.0), 100.0)


class SpreadTests(unittest.TestCase):
    def test_tags_die_elkaar_raken_schuiven_uit_elkaar_in_dezelfde_volgorde(self):
        out = ladder.spread([40.0, 42.0, 80.0], 6.0)
        self.assertEqual(out[2], 80.0)
        self.assertGreaterEqual(out[1] - out[0], 6.0 - 1e-9)
        self.assertLess(out[0], out[1])

    def test_ver_uit_elkaar_blijft_staan(self):
        self.assertEqual(ladder.spread([10.0, 50.0, 90.0], 6.0), [10.0, 50.0, 90.0])

    def test_blijft_binnen_de_ladder(self):
        out = ladder.spread([1.0, 2.0], 6.0)
        self.assertGreaterEqual(min(out), 0.0)
        self.assertLessEqual(max(out), 100.0)
        self.assertGreaterEqual(out[1] - out[0], 6.0 - 1e-9)


class BuildTests(unittest.TestCase):
    def short(self, price=99.0, **kw):
        # Short: stop boven, zone 101..102 met limiet 101, doel onder.
        return ladder.build("short", stop=104.0, entry=101.0, targets=[(95.0, 2.0)], price=price, zone_low=101.0, zone_high=102.0, **kw)

    def test_niveaus_staan_op_hun_echte_plek_en_volgorde(self):
        lad = self.short()
        names = [ln["name"] for ln in lad["lines"]]
        self.assertEqual(names, ["Stop", "Instap", "Doel"])
        ys = {ln["name"]: ln["y"] for ln in lad["lines"]}
        self.assertLess(ys["Stop"], ys["Instap"])           # short: stop boven de instap
        self.assertLess(ys["Instap"], ys["Doel"])
        for ln in lad["lines"]:
            self.assertAlmostEqual(ln["y"], ladder.y_pct(ln["value"], lad["hi"], lad["lo"]))
        self.assertEqual([ln["tone"] for ln in lad["lines"]], ["loss", "entry", "win"])

    def test_tekst_met_komma_en_kopie_met_punt(self):
        stop = self.short()["lines"][0]
        self.assertEqual(stop["text"], "104,00")
        self.assertEqual(stop["copy"], "104.00")
        hype = ladder.build("long", stop=78.5, entry=80.9234, targets=[(86.0, 2.0)], price=81.0)
        self.assertEqual([ln["text"] for ln in hype["lines"]], ["86,00", "80,92", "78,50"])      # niet 80,9234 of 80,9200

    def test_meerdere_doelen_krijgen_een_nummer(self):
        lad = ladder.build("long", stop=90.0, entry=100.0, targets=[(110.0, 1.0), (120.0, 2.0)], price=101.0)
        self.assertEqual([ln["name"] for ln in lad["lines"]], ["Doel 2", "Doel 1", "Instap", "Stop"])

    def test_zone_is_een_vlak_tussen_laag_en_hoog(self):
        lad = self.short()
        z = lad["zone"]
        self.assertAlmostEqual(z["top"], ladder.y_pct(102.0, lad["hi"], lad["lo"]))
        self.assertAlmostEqual(z["top"] + z["height"], ladder.y_pct(101.0, lad["hi"], lad["lo"]))

    def test_afstandsbalk_loopt_van_de_dichtstbijzijnde_zonerand_naar_de_koers(self):
        lad = self.short(price=99.0)
        g = lad["gap"]
        self.assertAlmostEqual(g["top"], ladder.y_pct(101.0, lad["hi"], lad["lo"]))
        self.assertAlmostEqual(g["top"] + g["height"], ladder.y_pct(99.0, lad["hi"], lad["lo"]))
        self.assertFalse(lad["in_zone"])

    def test_in_de_zone_verdwijnt_de_balk(self):
        lad = self.short(price=101.5)
        self.assertTrue(lad["in_zone"])
        self.assertEqual(lad["gap"]["height"], 0.0)

    def test_koers_boven_de_zone_balk_van_de_bovenrand(self):
        lad = ladder.build("long", stop=90.0, entry=100.0, targets=[(120.0, 2.0)], price=104.0, zone_low=99.0, zone_high=100.0)
        g = lad["gap"]
        self.assertAlmostEqual(g["top"], ladder.y_pct(104.0, lad["hi"], lad["lo"]))
        self.assertAlmostEqual(g["top"] + g["height"], ladder.y_pct(100.0, lad["hi"], lad["lo"]))

    def test_zonder_zone_telt_de_instap_als_rand(self):
        lad = ladder.build("long", stop=90.0, entry=100.0, targets=[(120.0, 2.0)], price=104.0)
        self.assertIsNone(lad["zone"])
        self.assertAlmostEqual(lad["gap"]["top"] + lad["gap"]["height"], ladder.y_pct(100.0, lad["hi"], lad["lo"]))

    def test_de_schaal_omvat_stop_doel_zone_en_koers(self):
        lad = self.short(price=97.0)
        for v in (104.0, 95.0, 102.0, 97.0):
            self.assertTrue(lad["lo"] < v < lad["hi"], v)

    def test_zonder_koers_geen_lijn_en_geen_balk(self):
        lad = self.short(price=None)
        self.assertIsNone(lad["price"])
        self.assertIsNone(lad["gap"])

    def test_tags_overlappen_niet(self):
        lad = ladder.build("short", stop=101.2, entry=101.0, targets=[(100.9, 0.5)], price=99.0)
        tags = sorted(ln["tag_y"] for ln in lad["lines"])
        for a, b in zip(tags, tags[1:]):
            self.assertGreaterEqual(b - a, ladder.TAG_GAP - 1e-9)

    def test_een_trade_heeft_geen_zone_en_geen_balk(self):
        lad = ladder.build("long", stop=90.0, entry=100.0, targets=[(120.0, 2.0)], price=104.0, trade=True)
        self.assertIsNone(lad["zone"])
        self.assertIsNone(lad["gap"])
        self.assertEqual([ln["name"] for ln in lad["lines"]], ["Doel", "Instap", "Stop"])


class DistanceTests(unittest.TestCase):
    def test_zelfde_formule_als_ladder_js_en_trade_plan(self):
        self.assertAlmostEqual(ladder.distance_pct("short", 100.0, 98.0), 2.0)
        self.assertAlmostEqual(ladder.distance_pct("long", 100.0, 102.0), 2.0)
        from app import trade_plan as tp
        for direction, low, high, stop, take in (("long", 99.0, 100.0, 98.0, 110.0), ("short", 100.0, 101.0, 102.0, 90.0)):
            plan = tp.limit_plan(direction, low, high, stop, take)
            for price in (97.0, 100.5, 104.0):
                self.assertAlmostEqual(ladder.distance_pct(direction, plan.limit, price), tp.distance_to_limit_pct(plan, price))


class StaleTests(unittest.TestCase):
    def test_alleen_ouder_dan_30_seconden(self):
        self.assertEqual(ladder.stale_text(None), "")
        self.assertEqual(ladder.stale_text(30), "")
        self.assertEqual(ladder.stale_text(45), "Koers 45 s oud")
        self.assertEqual(ladder.stale_text(150), "Koers 2 min oud")
        self.assertEqual(ladder.stale_text(7300), "Koers 2 u oud")


if __name__ == "__main__":
    unittest.main()


class CollisionTests(unittest.TestCase):
    """De koers heeft een eigen kolom links, de tags staan rechts: tekst botst nooit, ook niet als de koers precies op een niveau staat."""
    def tag_px(self, lad):
        return sorted(ln["tag_y"] * ladder.HEIGHT_PX / 100 for ln in lad["lines"])

    def assert_clean(self, lad):
        tags = self.tag_px(lad)
        for a, b in zip(tags, tags[1:]):
            self.assertGreaterEqual(b - a, ladder.TAG_PX - 1e-6)
        for t in tags:                                            # een tag past binnen de ladder, half boven en half onder zijn plek
            self.assertGreaterEqual(t, ladder.TAG_PX / 2 - 1e-6)
            self.assertLessEqual(t, ladder.HEIGHT_PX - ladder.TAG_PX / 2 + 1e-6)
        p = lad["price"]
        self.assertEqual(p["column"], "left")
        self.assertTrue(all(ln["column"] == "right" for ln in lad["lines"]))
        label = p["label_y"] * ladder.HEIGHT_PX / 100
        self.assertGreaterEqual(label, ladder.PRICE_PX / 2 - 1e-6)
        self.assertLessEqual(label, ladder.HEIGHT_PX - ladder.PRICE_PX / 2 + 1e-6)

    def test_koers_precies_op_de_instap(self):
        lad = ladder.build("long", stop=95.0, entry=100.0, targets=[(110.0, 2.0)], price=100.0, zone_low=99.0, zone_high=100.0)
        entry = next(ln for ln in lad["lines"] if ln["name"] == "Instap")
        self.assertAlmostEqual(lad["price"]["y"], entry["y"])        # de lijn staat op zijn prijs, het label in zijn eigen kolom
        self.assert_clean(lad)

    def test_koers_net_boven_de_stop(self):
        self.assert_clean(ladder.build("long", stop=95.0, entry=100.0, targets=[(110.0, 2.0)], price=95.05, zone_low=99.0, zone_high=100.0))

    def test_koers_voorbij_het_doel(self):
        lad = ladder.build("short", stop=104.0, entry=101.0, targets=[(95.0, 2.0)], price=90.0)
        self.assert_clean(lad)
        self.assertGreater(lad["price"]["y"], next(ln["y"] for ln in lad["lines"] if ln["name"] == "Doel"))

    def test_twee_tags_binnen_twaalf_pixels(self):
        lad = ladder.build("short", stop=101.2, entry=101.0, targets=[(95.0, 1.0)], price=99.0)
        ys = sorted(ln["y"] * ladder.HEIGHT_PX / 100 for ln in lad["lines"])
        self.assertLess(ys[1] - ys[0], 12)                            # stop en instap liggen dichter dan 12px bij elkaar
        self.assert_clean(lad)

    def test_drie_tags_tegen_de_rand(self):
        self.assert_clean(ladder.build("long", stop=99.99, entry=100.0, targets=[(100.01, 1.0)], price=150.0))

    def test_label_van_de_koers_blijft_binnen_de_ladder(self):
        lad = ladder.build("long", stop=95.0, entry=100.0, targets=[(110.0, 2.0)], price=200.0)
        self.assertAlmostEqual(lad["price"]["label_y"], ladder.label_y(lad["price"]["y"]))
        self.assert_clean(lad)
