import unittest
from datetime import datetime, timedelta, timezone

from app import notifications_view as nv

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def row(minutes_ago, type="update", read=0, i=1):
    return {"id": i, "type": type, "title": "t", "body": "b", "url": "/x", "is_read": read,
            "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


class ViewTest(unittest.TestCase):
    def test_relative_time(self):
        self.assertEqual(nv.relative_time(NOW - timedelta(seconds=30), NOW), "zojuist")
        self.assertEqual(nv.relative_time(NOW - timedelta(minutes=5), NOW), "5 min geleden")
        self.assertEqual(nv.relative_time(NOW - timedelta(hours=3, minutes=10), NOW), "3 uur geleden")
        self.assertRegex(nv.relative_time(NOW - timedelta(days=3), NOW), r"^\d\d-\d\d, \d\d:\d\d$")

    def test_groups_by_day_newest_first_with_chips_and_unread(self):
        groups = nv.group_notifications([row(60 * 30, i=1), row(10, i=2, read=1), row(60 * 24 * 3, "quality_report", i=3)], NOW)
        self.assertEqual([g["label"] for g in groups][:2], ["Vandaag", "Gisteren"])
        self.assertEqual(groups[0]["items"][0]["id"], 2)
        self.assertEqual(groups[0]["items"][0]["unread"], False)
        self.assertEqual(groups[1]["items"][0]["chip"], "Nieuw")
        self.assertEqual(groups[2]["items"][0]["chip"], "Rapport")

    def test_unknown_type_and_empty(self):
        self.assertEqual(nv.group_notifications([row(5, "iets_nieuws")], NOW)[0]["items"][0]["chip"], "Melding")
        self.assertEqual(nv.group_notifications([], NOW), [])


if __name__ == "__main__":
    unittest.main()
