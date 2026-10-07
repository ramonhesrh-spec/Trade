import unittest
from datetime import date

from app import ceo


class CeoTests(unittest.TestCase):
    def test_greeting_differs_for_the_ceo_and_a_student(self):
        self.assertEqual(ceo.greeting(9), "Goedemorgen CEO")
        self.assertEqual(ceo.greeting(14), "Goedemiddag CEO")
        self.assertEqual(ceo.greeting(21), "Goedenavond CEO")
        self.assertEqual(ceo.greeting(3), "De CEO werkt over")
        self.assertEqual(ceo.greeting(9, False, "Sander"), "Goedemorgen leerling Sander")
        self.assertIn("Nog wakker", ceo.greeting(3, False, "Sander"))

    def test_week_headline_follows_the_result(self):
        self.assertEqual(ceo.week_headline(2.0, 5), "Bonus uitgekeerd")
        self.assertEqual(ceo.week_headline(-1.0, 5), "Herstructurering aangekondigd")
        self.assertEqual(ceo.week_headline(0.0, 0), "Geen nieuws is goed nieuws")

    def test_timeline_text_keeps_the_meaning_in_brackets(self):
        self.assertIn("(stop geraakt)", ceo.timeline_text("Stop geraakt"))
        self.assertIn("T2 geraakt (3.0R)", ceo.timeline_text("T2 geraakt (3.0R)"))
        self.assertEqual(ceo.timeline_text("Onbekende regel"), "Onbekende regel")

    def test_money_rains_only_with_a_positive_week_and_is_capped(self):
        self.assertEqual((ceo.rain_count(-2.0), ceo.rain_count(0.0)), (0, 0))
        self.assertEqual(ceo.rain_count(1.0), 8)
        self.assertEqual(ceo.rain_count(500.0), 40)

    def test_quote_is_stable_per_day_and_students_get_titles(self):
        self.assertEqual(ceo.quote_of_the_day(date(2026, 10, 7)), ceo.quote_of_the_day(date(2026, 10, 7)))
        got = ceo.students(["a", "b"], date(2026, 10, 7))
        self.assertEqual([s["name"] for s in got], ["a", "b"])
        self.assertNotEqual(got[0]["title"], got[1]["title"])
        self.assertEqual(sum(1 for s in got if s["star"]), 1)                # precies één leerling van de maand
        self.assertEqual(ceo.students(["a", "b"], date(2026, 10, 25)), got)   # en die wisselt niet binnen de maand
        self.assertEqual(ceo.students([], date(2026, 10, 7)), [])


if __name__ == "__main__":
    unittest.main()
