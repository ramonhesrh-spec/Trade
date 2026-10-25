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


class StoredAgeTest(unittest.TestCase):
    """Leeftijd van een opgeslagen meting (marktcontext): de tijd van de meting zelf, niet van de pagina."""

    def test_age_from_an_iso_timestamp(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(freshness.age_seconds("2026-10-25T11:56:00+00:00", now), 240)
        self.assertEqual(freshness.age_seconds("2026-10-25T11:56:00", now), 240)       # naïef is UTC, zoals db.now_iso het schreef
        self.assertIsNone(freshness.age_seconds(None, now))
        self.assertIsNone(freshness.age_seconds("kapot", now))

    def test_short_age_text(self):
        self.assertEqual(freshness.age_text(20), "net")
        self.assertEqual(freshness.age_text(240), "4 min")
        self.assertEqual(freshness.age_text(3 * 3600 + 100), "3 u")
        self.assertEqual(freshness.age_text(3 * 86400), "3 d")
        self.assertEqual(freshness.age_text(None), "")
