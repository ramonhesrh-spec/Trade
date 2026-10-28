"""Prijsweergave (app/price_text.py): komma als decimaalteken en een aantal decimalen dat bij de prijs past; kopiëren met een punt."""
import unittest

from app import price_text as pt


class DecimalsTests(unittest.TestCase):
    def test_twee_vanaf_tien(self):
        self.assertEqual(pt.decimals(80.9234), 2)
        self.assertEqual(pt.decimals(10.0), 2)
        self.assertEqual(pt.decimals(67400.0), 2)

    def test_drie_tussen_een_en_tien(self):
        self.assertEqual(pt.decimals(9.99), 3)
        self.assertEqual(pt.decimals(1.0), 3)

    def test_vier_tussen_een_honderdste_en_een(self):
        self.assertEqual(pt.decimals(0.1702), 4)
        self.assertEqual(pt.decimals(0.01), 4)

    def test_zes_daaronder_maar_altijd_drie_cijfers_die_tellen(self):
        self.assertEqual(pt.decimals(0.0099), 6)
        self.assertEqual(pt.decimals(0.00001234), 7)          # PEPE: zes decimalen gaven 0,000012

    def test_negatief_telt_als_positief(self):
        self.assertEqual(pt.decimals(-80.9), 2)


class TextTests(unittest.TestCase):
    def test_hype_met_komma_en_twee_decimalen(self):
        self.assertEqual(pt.nl(80.92), "80,92")
        self.assertEqual(pt.nl(80.9234), "80,92")

    def test_voorbeelden(self):
        self.assertEqual(pt.nl(2430.0), "2430,00")
        self.assertEqual(pt.nl(2.5), "2,500")
        self.assertEqual(pt.nl(0.1702), "0,1702")
        self.assertEqual(pt.nl(0.00001234), "0,0000123")
        self.assertEqual(pt.nl(0), "0")

    def test_kopie_is_hetzelfde_getal_met_een_punt(self):
        self.assertEqual(pt.plain(80.9234), "80.92")
        self.assertEqual(pt.plain(0.1702), "0.1702")
        for v in (67400.0, 3.14159, 0.05, 0.00001234):
            self.assertEqual(pt.plain(v).replace(".", ","), pt.nl(v))

    def test_nooit_wetenschappelijke_notatie(self):
        self.assertNotIn("e", pt.plain(0.0000001234))
