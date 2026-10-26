"""Weekterugblik (app/week_review.py): één gemeten getal, acht weken, de getallen eronder en hoogstens één telbare observatie."""
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app import week_review as wr

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)            # zondag, week 43 (19-25 oktober)


def t(at, r):
    return {"at": at, "r": r}


class ReviewTests(unittest.TestCase):
    def test_lege_week_is_nul_en_heeft_geen_observatie(self):
        v = wr.review([], [], NOW, TZ)
        self.assertEqual(v["label"], "Week 43 · 19–25 oktober")
        self.assertEqual((v["total"], v["total_text"]), (0.0, "0,0 R"))
        self.assertEqual(v["counts_text"], "Nog geen afgeronde trade deze week")
        self.assertEqual(v["stats"], [])
        self.assertIsNone(v["observation"])
        self.assertEqual(len(v["weeks"]), 8)
        self.assertTrue(v["weeks"][-1]["current"])

    def test_week_r_aantallen_en_getallen_eronder(self):
        trades = [t("2026-10-20T10:00:00+00:00", 2.0), t("2026-10-21T10:00:00+00:00", -1.0), t("2026-10-25T21:30:00+00:00", 1.5),
                  t("2026-10-18T21:30:00+00:00", 3.0)]                     # zondag 18 okt 23:30 lokaal: vorige week
        skips = [{"at": "2026-10-22T10:00:00+00:00", "outcome": None, "r": None}]
        v = wr.review(trades, skips, NOW, TZ)
        self.assertEqual(v["total_text"], "+2,5 R")
        self.assertEqual(v["counts_text"], "3 trades · 2 gewonnen · 1 verloren · 1 overgeslagen")
        self.assertEqual([(s["label"], s["value"]) for s in v["stats"]], [("Gem. per trade", "+0,83 R"), ("Grootste verlies", "−1,0 R")])
        self.assertEqual(v["weeks"][-1]["value"], 2.5)
        self.assertEqual(v["weeks"][-2]["value"], 3.0)
        self.assertEqual((v["weeks"][-1]["name"], v["weeks"][0]["name"]), ("w43", "w36"))
        self.assertEqual(v["eight_total_text"], "+5,5 R")

    def test_zonder_verlies_geen_grootste_verlies(self):
        v = wr.review([t("2026-10-20T10:00:00+00:00", 2.0)], [], NOW, TZ)
        self.assertEqual([s["label"] for s in v["stats"]], ["Gem. per trade"])
        self.assertEqual(v["counts_text"], "1 trade · 1 gewonnen · 0 verloren")

    def test_volgens_plan_staat_er_nooit_want_het_is_niet_meetbaar(self):
        v = wr.review([t("2026-10-20T10:00:00+00:00", -1.0)], [], NOW, TZ)
        self.assertNotIn("Volgens plan", [s["label"] for s in v["stats"]])

    def test_observatie_alleen_uit_overgeslagen_plannen_met_uitkomst(self):
        skips = [{"at": "2026-10-20T10:00:00+00:00", "outcome": "take_profit", "r": 1.0},
                 {"at": "2026-10-21T10:00:00+00:00", "outcome": "take_profit", "r": 2.0},
                 {"at": "2026-10-22T10:00:00+00:00", "outcome": "stop_loss", "r": -1.0},
                 {"at": "2026-10-23T10:00:00+00:00", "outcome": None, "r": None},
                 {"at": "2026-10-12T10:00:00+00:00", "outcome": "take_profit", "r": 5.0}]     # vorige week telt niet
        v = wr.review([], skips, NOW, TZ)
        self.assertEqual(v["observation"], "2 van je 3 overgeslagen plannen met een uitkomst haalden hun doel. Samen +3,0 R die je niet nam.")

    def test_geen_doel_gehaald_zegt_dat_zonder_bedrag(self):
        v = wr.review([], [{"at": "2026-10-22T10:00:00+00:00", "outcome": "stop_loss", "r": -1.0}], NOW, TZ)
        self.assertEqual(v["observation"], "Je ene overgeslagen plan met een uitkomst raakte zijn stop.")

    def test_staven_neutraal_deze_week_in_accent_met_hoogte_naar_verhouding(self):
        trades = [t("2026-10-20T10:00:00+00:00", 2.0), t("2026-10-13T10:00:00+00:00", -1.0)]
        weeks = wr.review(trades, [], NOW, TZ)["weeks"]
        cur, prev = weeks[-1], weeks[-2]
        self.assertTrue(cur["current"])
        self.assertFalse(prev["current"])
        self.assertGreater(cur["height_pct"], prev["height_pct"])
        self.assertEqual((cur["value_text"], prev["value_text"]), ("+2,0", "−1,0"))
        self.assertTrue(prev["negative"])
        self.assertEqual(weeks[0]["value_text"], "0")


if __name__ == "__main__":
    unittest.main()
