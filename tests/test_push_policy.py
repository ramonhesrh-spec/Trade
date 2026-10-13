import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import config, db, push_notify, push_policy, repo
from tests.test_samenval import DbCase

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def push(coin, direction, hours_ago):
    return {"coin": coin, "direction": direction, "at": (NOW - timedelta(hours=hours_ago)).isoformat()}


class DecideTest(unittest.TestCase):
    def test_opposite_direction_on_the_same_coin_is_held_back_for_six_hours(self):
        ok, reason = push_policy.decide([push("BTC", "long", 2)], "BTC", "short", None, NOW)
        self.assertFalse(ok)
        self.assertIn("Tegenstrijdig", reason)
        self.assertTrue(push_policy.decide([push("BTC", "long", 7)], "BTC", "short", None, NOW)[0])      # lang genoeg geleden
        self.assertTrue(push_policy.decide([push("BTC", "long", 2)], "ETH", "short", None, NOW)[0])      # andere coin
        self.assertTrue(push_policy.decide([push("BTC", "long", 2)], "BTC", "long", None, NOW)[0])       # zelfde richting

    def test_daily_budget_defaults_to_six_and_zero_switches_it_off(self):
        many = [push(f"C{i}", "long", 3) for i in range(6)]
        self.assertFalse(push_policy.decide(many, "NEW", "long", None, NOW)[0])
        self.assertTrue(push_policy.decide(many[:5], "NEW", "long", None, NOW)[0])
        self.assertTrue(push_policy.decide(many, "NEW", "long", 20, NOW)[0])
        self.assertTrue(push_policy.decide(many, "NEW", "long", 0, NOW)[0])


class SendKansPushTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        self.sent = []

    def send(self, coin, direction):
        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            self.sent.append((coin, direction, title))
        with mock.patch("app.push_notify.send_push", fake_push):
            return asyncio.run(push_notify.send_kans_push(self.uid, coin, direction, f"{coin} {direction}", "body", "/kans/1"))

    def notifications(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT type, title, body FROM notifications WHERE user_id = ?", (self.uid,))]

    def test_conflicting_direction_becomes_a_quiet_notification_not_a_push(self):
        self.assertTrue(self.send("BTC", "long"))
        self.assertFalse(self.send("BTC", "short"))
        self.assertEqual([s[:2] for s in self.sent], [("BTC", "long")])
        note = self.notifications()[0]
        self.assertEqual(note["type"], "kans")
        self.assertIn("Tegenstrijdig", note["body"])                         # niets verdwijnt: het staat op de meldingenpagina
        self.assertTrue(self.send("BTC", "long"))                            # dezelfde richting blijft gewoon komen

    def test_budget_is_per_user_and_adjustable(self):
        repo.set_push_budget(self.uid, 2)
        self.assertTrue(self.send("BTC", "long"))
        self.assertTrue(self.send("ETH", "long"))
        self.assertFalse(self.send("SOL", "long"))
        self.assertIn("Dagbudget", self.notifications()[0]["body"])
        repo.set_push_budget(self.uid, 0)                                    # 0 zet het budget uit
        self.assertTrue(self.send("SUI", "long"))


class SettingsRouteTest(DbCase):
    def test_budget_setting_is_saved_and_invalid_values_reset_it(self):
        uid = repo.get_user_by_username("a")["id"]
        repo.set_push_budget(uid, 5)
        self.assertEqual(repo.get_user(uid)["push_budget"], 5)
        repo.set_push_budget(uid, None)
        self.assertIsNone(repo.get_user(uid)["push_budget"])


class PauseRuleTest(unittest.TestCase):
    def test_minutes_left_rounds_up_and_ends_at_zero(self):
        self.assertEqual(push_policy.pause_minutes_left(None, NOW), 0)
        self.assertEqual(push_policy.pause_minutes_left("", NOW), 0)
        self.assertEqual(push_policy.pause_minutes_left("onzin", NOW), 0)
        self.assertEqual(push_policy.pause_minutes_left(push_policy.pause_until(NOW).isoformat(), NOW), 120)
        self.assertEqual(push_policy.pause_minutes_left((NOW + timedelta(seconds=30)).isoformat(), NOW), 1)
        self.assertEqual(push_policy.pause_minutes_left((NOW - timedelta(minutes=1)).isoformat(), NOW), 0)
        naive = (NOW + timedelta(minutes=10)).replace(tzinfo=None).isoformat()          # oude rijen zonder tijdzone gelden als UTC
        self.assertEqual(push_policy.pause_minutes_left(naive, NOW), 10)

    def test_text(self):
        self.assertEqual(push_policy.pause_text(0), "Pauze")
        self.assertEqual(push_policy.pause_text(120), "Stil 2:00")
        self.assertEqual(push_policy.pause_text(43), "Stil 0:43")


class PauseSendTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        repo.upsert_push_subscription(self.uid, "https://push.test/1", "p256", "auth")
        self.sent = []
        for patcher in (mock.patch.object(config, "VAPID_PRIVATE_KEY", "sleutel"),
                        mock.patch.object(push_notify, "_send_one", lambda sub, payload: self.sent.append(payload))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def pause(self, minutes):
        repo.set_push_pause(self.uid, (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat())

    def test_pause_holds_back_every_push_until_it_ends(self):
        self.pause(120)
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(self.sent, [])
        repo.set_push_pause(self.uid, None)
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(len(self.sent), 1)

    def test_expired_pause_lets_pushes_through(self):
        self.pause(-1)
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(len(self.sent), 1)

    def test_paused_chance_becomes_quiet_notification_and_does_not_use_the_budget(self):
        self.pause(60)
        self.assertFalse(asyncio.run(push_notify.send_kans_push(self.uid, "BTC", "long", "BTC long", "body", "/kans/1")))
        self.assertEqual(self.sent, [])
        with db.session() as conn:
            body = conn.execute("SELECT body FROM notifications WHERE user_id = ?", (self.uid,)).fetchone()["body"]
        self.assertIn("pauze", body)
        self.assertEqual(repo.list_recent_pushes(self.uid, "2000-01-01T00:00:00+00:00"), [])

    def test_column_exists_and_migration_is_idempotent(self):
        with db.session() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        self.assertIn("push_paused_until", cols)
        db.init_db()                                                             # tweede keer: idempotent

    def test_badge_travels_in_the_payload_only_when_given(self):
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x", badge=3))
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(self.sent[0]["badge"], 3)
        self.assertNotIn("badge", self.sent[1])


if __name__ == "__main__":
    unittest.main()
