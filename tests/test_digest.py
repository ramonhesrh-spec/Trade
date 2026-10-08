import unittest
from datetime import datetime, timezone

from app import digest


class DigestTest(unittest.TestCase):
    def test_slot_key_only_in_the_two_day_parts(self):
        self.assertIsNone(digest.slot_key(datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)))        # nacht, lokaal 04:00
        morning = digest.slot_key(datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc))                  # lokaal 09:00
        self.assertTrue(morning.endswith(":8"))
        self.assertEqual(morning, digest.slot_key(datetime(2026, 10, 8, 8, 30, tzinfo=timezone.utc)))
        self.assertTrue(digest.slot_key(datetime(2026, 10, 8, 19, 0, tzinfo=timezone.utc)).endswith(":20"))

    def test_build_names_the_nearest_chance_and_counts(self):
        self.assertIsNone(digest.build([]))
        title, body = digest.build([{"coin": "BNB", "direction": "short", "grade": "A", "dist_pct": 0.4},
                                    {"coin": "SOL", "direction": "long", "grade": "C", "dist_pct": 1.5}])
        self.assertEqual(title, "2 kansen wachten")
        self.assertIn("Het dichtst bij: BNB short, nog 0.4%", body)
        self.assertIn("SOL long: nog 1.5%", body)
        self.assertTrue(digest.build([{"coin": "BNB", "direction": "short", "grade": "A", "dist_pct": 0.4}], "Een stop is een bijsturing.")[1].endswith("Een stop is een bijsturing."))
        self.assertEqual(digest.build([{"coin": "BNB", "direction": "short", "grade": "A", "dist_pct": 0.4}])[0], "1 kans wacht")


if __name__ == "__main__":
    unittest.main()
