import unittest

from app import freshness


class FreshnessTest(unittest.TestCase):
    def test_oldest_age_over_the_shown_coins(self):
        fetched = {"BTC": 1000.0, "ETH": 900.0, "SOL": 10.0}
        self.assertEqual(freshness.oldest_age(fetched, ["BTC", "ETH"], 1030.5), 130)
        self.assertEqual(freshness.oldest_age(fetched, ["BTC"], 1030.5), 30)

    def test_no_measurement_is_none_not_zero(self):
        self.assertIsNone(freshness.oldest_age({}, ["BTC"], 5.0))
        self.assertIsNone(freshness.oldest_age({"BTC": 1.0}, [], 5.0))

    def test_threshold_is_two_minutes(self):
        self.assertEqual(freshness.STALE_AFTER_S, 120)
