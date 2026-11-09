import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

from app import calendar_alerts, repo
from tests.test_samenval import DbCase

TUESDAY = datetime(2026, 10, 6, 13, 10, tzinfo=timezone.utc)      # 20 minuten voor 9:30 in New York (13:30 UTC)


class CalendarAlertsTest(DbCase):
    def run_alerts(self, now):
        pushed = []

        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            pushed.append((title, body, silent))
        with mock.patch("app.push_notify.send_push", fake_push):
            asyncio.run(calendar_alerts.run(now))
        return pushed

    def test_us_open_is_announced_once_and_silently_with_the_measured_note(self):
        pushed = self.run_alerts(TUESDAY)
        self.assertEqual(len(pushed), 1)
        title, body, silent = pushed[0]
        self.assertIn("Opening VS-beurs", title)
        self.assertIn("Over 20 min", body)
        self.assertIn("1,9x", body)
        self.assertTrue(silent)
        self.assertEqual(self.run_alerts(TUESDAY.replace(minute=15)), [])         # zelfde moment, tweede scan: niets

    def test_nothing_when_no_moment_is_close(self):
        self.assertEqual(self.run_alerts(TUESDAY.replace(hour=6)), [])

    def test_engine_disabled_notice_is_created_once_per_day(self):
        repo.notify_engine_disabled("Markt-script", "detail")
        repo.notify_engine_disabled("Markt-script", "detail")
        rows = repo.list_admin_notifications()
        self.assertEqual([r["title"] for r in rows], ["Markt-script staat uit"])


if __name__ == "__main__":
    unittest.main()
