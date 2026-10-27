"""De aankondiging (app/announce.py): aftelmaths, fases, wanneer het verhaal en de push komen, en de tekst die we beloven."""
import unittest
from datetime import datetime, timedelta, timezone

from app import announce

UTC = timezone.utc
AT = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)          # 18:00 in Amsterdam (wintertijd)


class ParseTests(unittest.TestCase):
    def test_lokale_tijd_wordt_utc_in_de_winter(self):
        self.assertEqual(announce.parse_moment("2026-11-02T18:00"), AT)

    def test_lokale_tijd_wordt_utc_in_de_zomer(self):
        self.assertEqual(announce.parse_moment("2026-07-01T18:00"), datetime(2026, 7, 1, 16, 0, tzinfo=UTC))

    def test_een_tijd_met_offset_blijft_hetzelfde_moment(self):
        self.assertEqual(announce.parse_moment("2026-11-02T17:00:00+00:00"), AT)

    def test_leeg_of_onzin_is_geen_moment(self):
        for raw in (None, "", "  ", "morgen", "2026-13-02T18:00"):
            self.assertIsNone(announce.parse_moment(raw), raw)

    def test_lokale_weergave(self):
        self.assertEqual(announce.fmt_local(AT), "maandag 2 november, 18:00")


class CountdownTests(unittest.TestCase):
    def test_resterende_tijd_in_dagen_uren_minuten_seconden(self):
        now = AT - timedelta(days=2, hours=3, minutes=4, seconds=5)
        self.assertEqual(announce.remaining(AT, now), {"days": 2, "hours": 3, "minutes": 4, "seconds": 5, "total": 183845})

    def test_een_halve_seconde_telt_als_een_hele(self):
        # Zo staat er nooit 00:00:00 terwijl het moment nog niet bereikt is.
        self.assertEqual(announce.remaining(AT, AT - timedelta(milliseconds=500))["seconds"], 1)

    def test_na_het_moment_staat_alles_op_nul(self):
        self.assertEqual(announce.remaining(AT, AT + timedelta(minutes=5)), {"days": 0, "hours": 0, "minutes": 0, "seconds": 0, "total": 0})

    def test_fase_voor_en_na(self):
        self.assertEqual(announce.phase(AT, AT - timedelta(seconds=1)), "before")
        self.assertEqual(announce.phase(AT, AT), "live")
        self.assertEqual(announce.phase(AT, AT + timedelta(days=30)), "live")

    def test_zonder_tijd_is_het_live(self):
        self.assertEqual(announce.phase(None, AT), "live")


class StoryTests(unittest.TestCase):
    def test_verhaal_pas_na_het_moment_en_alleen_ongezien(self):
        self.assertFalse(announce.story_due(AT, AT - timedelta(seconds=1), seen=False))
        self.assertTrue(announce.story_due(AT, AT, seen=False))
        self.assertFalse(announce.story_due(AT, AT + timedelta(hours=1), seen=True))

    def test_zonder_tijd_opent_het_verhaal_nooit_vanzelf(self):
        self.assertFalse(announce.story_due(None, AT, seen=False))

    def test_zes_kaarten_met_korte_kop_en_een_zin(self):
        self.assertIn(len(announce.CARDS), (5, 6))
        for card in announce.CARDS:
            self.assertLessEqual(len(card["title"].split()), 6, card["title"])
            text = card["text"].rstrip(".")
            self.assertNotIn(". ", text, card["text"])           # één zin
            self.assertTrue(card["key"])

    def test_beloftes_drie_of_vier(self):
        self.assertIn(len(announce.PROMISES), (3, 4))

    def test_geen_bewezen_of_winstbelofte(self):
        words = " ".join([c["title"] + " " + c["text"] for c in announce.CARDS] + announce.PROMISES + [announce.LEAD_BEFORE, announce.PUSH_BODY]).lower()
        for banned in ("bewezen", "winst", "gegarandeerd", "verdien", "rendement"):
            self.assertNotIn(banned, words)

    def test_nieuwe_soorten_heten_ongetest(self):
        coins = next(c for c in announce.CARDS if c["key"] == "kansen")
        self.assertIn("ongetest", coins["text"])


class LinkAndPushTests(unittest.TestCase):
    def test_link_naar_nieuw_zolang_de_aankondiging_loopt(self):
        self.assertFalse(announce.link_visible(None, AT))
        self.assertTrue(announce.link_visible(AT, AT - timedelta(days=3)))
        self.assertTrue(announce.link_visible(AT, AT + timedelta(days=announce.RUN_DAYS) - timedelta(seconds=1)))
        self.assertFalse(announce.link_visible(AT, AT + timedelta(days=announce.RUN_DAYS)))

    def test_push_pas_als_het_moment_voorbij_is_en_niet_dagen_later(self):
        self.assertFalse(announce.push_due(None, AT))
        self.assertFalse(announce.push_due(AT, AT - timedelta(seconds=1)))
        self.assertTrue(announce.push_due(AT, AT))
        self.assertTrue(announce.push_due(AT, AT + timedelta(hours=23)))
        # Een tijd die al lang voorbij was toen hij werd gezet, of een proces dat dagen stillag: geen verouderde push.
        self.assertFalse(announce.push_due(AT, AT + timedelta(days=1, seconds=1)))

    def test_pushtekst(self):
        self.assertEqual(announce.PUSH_TITLE, "HesPulse is vernieuwd")
        self.assertEqual(announce.PUSH_URL, "/nieuw")
        self.assertEqual(announce.PUSH_BODY.count(". "), 0)


if __name__ == "__main__":
    unittest.main()
