"""De aankondiging in de database en de eenmalige push: het moment (database wint van .env), het verhaal één keer per gebruiker en de push
precies één keer, ook als twee processen tegelijk kijken of na een herstart."""
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import announce, announce_live, config, db, repo, security

AT = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "a.db")),
                        mock.patch.object(config, "ANNOUNCEMENT_AT", "")]
        for p in self.patches:
            p.start()
        db.init_db()
        self.anna = repo.create_user("anna", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.bram = repo.create_user("bram", security.hash_password("wachtwoord-123456"), 0, 1.0)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class MomentTests(Base):
    def test_zonder_iets_is_er_geen_moment(self):
        self.assertIsNone(repo.get_announcement_at())

    def test_env_is_de_startwaarde(self):
        with mock.patch.object(config, "ANNOUNCEMENT_AT", "2026-11-02T18:00"):
            self.assertEqual(repo.get_announcement_at(), AT)

    def test_database_wint_van_env(self):
        repo.set_announcement_at(AT + timedelta(days=1))
        with mock.patch.object(config, "ANNOUNCEMENT_AT", "2026-11-02T18:00"):
            self.assertEqual(repo.get_announcement_at(), AT + timedelta(days=1))

    def test_wissen_wint_ook_van_env(self):
        repo.set_announcement_at(AT)
        repo.clear_announcement_at()
        with mock.patch.object(config, "ANNOUNCEMENT_AT", "2026-11-02T18:00"):
            self.assertIsNone(repo.get_announcement_at())


class StorySeenTests(Base):
    def test_per_gebruiker_en_idempotent(self):
        self.assertFalse(repo.story_seen(self.anna, "v3"))
        repo.mark_story_seen(self.anna, "v3")
        repo.mark_story_seen(self.anna, "v3")
        self.assertTrue(repo.story_seen(self.anna, "v3"))
        self.assertFalse(repo.story_seen(self.bram, "v3"))
        self.assertFalse(repo.story_seen(self.anna, "v4"))


class ClaimTests(Base):
    def test_een_vlag_kan_maar_een_keer_geclaimd_worden(self):
        self.assertTrue(repo.claim_flag("announce_push:v3"))
        self.assertFalse(repo.claim_flag("announce_push:v3"))


class PushTests(Base):
    def run_push(self, now):
        sent = []

        async def fake_send(user_id, title, body, url, silent=False, **kw):
            sent.append((user_id, title, body, url, silent))

        with mock.patch("app.push_notify.send_push", fake_send):
            asyncio.run(announce_live.run(now))
        return sent

    def test_geen_push_zonder_moment_of_ervoor(self):
        self.assertEqual(self.run_push(AT), [])
        repo.set_announcement_at(AT)
        self.assertEqual(self.run_push(AT - timedelta(minutes=1)), [])

    def test_een_push_per_gebruiker_en_daarna_nooit_meer(self):
        repo.set_announcement_at(AT)
        sent = self.run_push(AT + timedelta(minutes=3))
        self.assertEqual(sorted(s[0] for s in sent), [self.anna, self.bram])
        self.assertEqual({s[1:4] for s in sent}, {(announce.PUSH_TITLE, announce.PUSH_BODY, "/nieuw")})
        self.assertEqual(self.run_push(AT + timedelta(minutes=8)), [])

    def test_een_nieuwe_tijd_geeft_geen_tweede_push(self):
        repo.set_announcement_at(AT)
        self.run_push(AT + timedelta(minutes=1))
        repo.set_announcement_at(AT + timedelta(hours=2))
        self.assertEqual(self.run_push(AT + timedelta(hours=2, minutes=1)), [])

    def test_stille_uren_maken_de_push_stil(self):
        repo.update_user_settings(self.anna, quiet_hours_start="00:00", quiet_hours_end="23:59")
        repo.set_announcement_at(AT)
        with mock.patch("app.push_notify.is_quiet_now", side_effect=lambda s, e: bool(s)):
            sent = self.run_push(AT + timedelta(minutes=1))
        self.assertEqual({s[0]: s[4] for s in sent}, {self.anna: True, self.bram: False})

    def test_te_laat_geen_push(self):
        repo.set_announcement_at(AT)
        self.assertEqual(self.run_push(AT + timedelta(days=2)), [])


if __name__ == "__main__":
    unittest.main()


class CycleTests(Base):
    def test_de_snelcyclus_draait_de_aankondiging_ook_met_de_noodrem(self):
        from app import market_scanner
        called = []

        async def fake_run(now=None):
            called.append(True)
            return 0

        with mock.patch.object(announce_live, "run", fake_run), mock.patch.object(repo, "is_market_scan_enabled", return_value=False):
            asyncio.run(market_scanner.scan_smc_fast())
        self.assertEqual(called, [True])
