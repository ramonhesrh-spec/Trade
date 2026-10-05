import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import config, db, repo, signal_processor
from tests.test_samenval import DbCase


class InfoOnlyTest(DbCase):
    def fanout(self, signal_type):
        sid = self.insert_signal()
        pushed = []

        async def fake_push(user_id, title, body, url, silent=False):
            pushed.append(title)

        with mock.patch.object(signal_processor.push_notify, "send_push", fake_push):
            asyncio.run(signal_processor.fanout_confirmed_signal(
                sid, "BTC", "long", 100.0, 99.0, 102.0, 100.0, "titel", lambda *a: "body", signal_type=signal_type))
        return pushed

    def test_info_only_type_gets_journal_entry_but_no_push(self):
        with mock.patch.object(config, "SIGNAL_TYPE_INFO_ONLY", {"smc"}):
            self.assertEqual(self.fanout("smc"), [])
            with db.session() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0], 1)

    def test_other_types_still_push(self):
        with mock.patch.object(config, "SIGNAL_TYPE_INFO_ONLY", {"patroon"}):
            self.assertEqual(self.fanout("smc"), ["titel"])


if __name__ == "__main__":
    unittest.main()
