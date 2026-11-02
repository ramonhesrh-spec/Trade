"""Minder meldingen (CEO, 2026-11-02): een nieuwe kaart is stil en telt niet, alleen een vulling is luid, elke luide push telt in het dagbudget
(standaard 8), boven het budget wordt een vulling een stille melding op de meldingenpagina, vullingen in één scancyclus komen als één push en
een uitkomst telt niet."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import db, market_scanner, push_notify, push_policy, repo
from tests.test_review_fixes import TakenTradeCase, _bars
from tests.test_samenval import DbCase

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
SINCE = "2000-01-01T00:00:00+00:00"


def push(coin, direction, hours_ago, counts=1):
    return {"coin": coin, "direction": direction, "at": (NOW - timedelta(hours=hours_ago)).isoformat(), "counts": counts}


class PolicyTest(unittest.TestCase):
    def test_default_budget_is_eight(self):
        self.assertEqual(push_policy.DEFAULT_BUDGET, 8)

    def test_every_loud_push_counts_also_a_repeat_on_the_same_coin(self):
        repeats = [push("DOGE", "long", 3), push("DOGE", "long", 4)]
        self.assertEqual(push_policy.used(repeats), 2)
        full = [push("DOGE", "long", h) for h in range(1, 9)]
        self.assertFalse(push_policy.decide(full, "DOGE", "long", None, NOW)[0])

    def test_a_bundle_counts_once(self):
        bundle = [push("SOL", "long", 1, 1), push("ETH", "short", 1, 0), push("ADA", "long", 1, 0)]
        self.assertEqual(push_policy.used(bundle), 1)

    def test_bundle_text(self):
        title, body = push_policy.bundle_text([("SOL", "long"), ("ETH", "short"), ("ADA", "long")])
        self.assertEqual(title, "3 kansen gevuld")
        self.assertIn("SOL long, ETH short, ADA long", body)


class Case(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        self.sent = []

        async def fake_push(user_id, title, body, url, silent=False, tag=None, badge=None):
            self.sent.append({"user": user_id, "title": title, "body": body, "url": url, "silent": silent})
        p = mock.patch.object(push_notify, "send_push", fake_push)
        p.start()
        self.addCleanup(p.stop)

    def notes(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT type, title, body, url FROM notifications WHERE user_id = ? ORDER BY id", (self.uid,))]

    def used(self):
        return push_policy.used(repo.list_recent_pushes(self.uid, SINCE))

    def fill(self, coin, direction="long"):
        return asyncio.run(push_notify.send_kans_push(self.uid, coin, direction, f"{coin} {direction} gevuld", "body", f"/kans/{coin}"))


class NewCardTest(Case):
    def test_new_card_is_a_silent_push_that_does_not_count_and_is_on_the_page(self):
        asyncio.run(push_notify.send_new_card(self.uid, "BTC", "long", "BTC long wacht", "plan", "/smc#radar-zone-1", tag="zone-radar-1"))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0]["silent"])
        self.assertEqual(self.used(), 0)
        self.assertEqual([(n["type"], n["url"]) for n in self.notes()], [("kans", "/smc#radar-zone-1")])

    def test_new_card_outside_the_follow_set_has_no_push_but_is_on_the_page(self):
        repo.set_user_follow_set(self.uid, repo.create_follow_set("Kern", ["BTC"]))
        asyncio.run(push_notify.send_new_card(self.uid, "DOGE", "long", "DOGE long wacht", "plan", "/smc#radar-zone-2"))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.notes()), 1)

    def test_new_card_during_a_pause_has_no_push_but_is_on_the_page(self):
        repo.set_push_pause(self.uid, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        asyncio.run(push_notify.send_new_card(self.uid, "BTC", "long", "BTC long wacht", "plan", "/smc#radar-zone-3"))
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.notes()), 1)


class FillBudgetTest(Case):
    def test_every_loud_push_counts(self):
        self.fill("BTC")
        self.fill("BTC")
        self.assertEqual(self.used(), 2)

    def test_ninth_fill_is_a_silent_notification_on_the_page(self):
        coins = ["BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "LINK", "SUI"]
        for coin in coins:
            self.assertTrue(self.fill(coin))
        self.assertTrue(all(not s["silent"] for s in self.sent))
        self.assertFalse(self.fill("AVAX"))
        self.assertEqual(len(self.sent), 9)
        self.assertTrue(self.sent[-1]["silent"])
        self.assertEqual(self.used(), 8)
        note = self.notes()[-1]
        self.assertEqual(note["title"], "AVAX long gevuld")
        self.assertIn("Dagbudget van 8", note["body"])


class BundleTest(Case):
    def test_three_fills_in_one_cycle_are_one_loud_push_that_counts_once(self):
        async def cycle():
            for coin, direction in (("SOL", "long"), ("ETH", "short"), ("ADA", "long")):
                await push_notify.send_kans_push(self.uid, coin, direction, f"{coin} {direction} gevuld", "body", f"/kans/{coin}")
        with mock.patch.object(market_scanner, "_scan_smc_fast", cycle), mock.patch.object(repo, "beat", lambda *a, **k: None):
            asyncio.run(market_scanner.scan_smc_fast())
        self.assertEqual(len(self.sent), 1)
        p = self.sent[0]
        self.assertEqual(p["title"], "3 kansen gevuld")
        self.assertIn("SOL long, ETH short, ADA long", p["body"])
        self.assertEqual(p["url"], "/smc")
        self.assertFalse(p["silent"])
        self.assertEqual(self.used(), 1)

    def test_a_single_fill_in_a_cycle_keeps_its_own_push(self):
        async def cycle():
            await push_notify.send_kans_push(self.uid, "SOL", "long", "SOL long gevuld", "body", "/kans/7")
        with mock.patch.object(market_scanner, "_scan_smc_fast", cycle), mock.patch.object(repo, "beat", lambda *a, **k: None):
            asyncio.run(market_scanner.scan_smc_fast())
        self.assertEqual([(p["title"], p["url"]) for p in self.sent], [("SOL long gevuld", "/kans/7")])
        self.assertEqual(self.used(), 1)

    def test_a_bundle_over_the_budget_is_silent_and_every_fill_is_on_the_page(self):
        repo.set_push_budget(self.uid, 1)
        self.fill("BTC")

        async def cycle():
            for coin in ("SOL", "ETH"):
                await push_notify.send_kans_push(self.uid, coin, "long", f"{coin} long gevuld", "body", f"/kans/{coin}")
        with mock.patch.object(market_scanner, "_scan_smc_fast", cycle), mock.patch.object(repo, "beat", lambda *a, **k: None):
            asyncio.run(market_scanner.scan_smc_fast())
        self.assertEqual(len(self.sent), 2)
        self.assertTrue(self.sent[-1]["silent"])
        self.assertEqual(self.used(), 1)
        self.assertEqual([n["title"] for n in self.notes()], ["SOL long gevuld", "ETH long gevuld"])


class MigrationTest(DbCase):
    def test_an_old_push_log_gets_counts_and_old_rows_count_once(self):
        with db.session() as conn:
            conn.execute("DROP TABLE push_log")
            conn.execute("CREATE TABLE push_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, at TEXT NOT NULL, coin TEXT NOT NULL, direction TEXT NOT NULL)")
            conn.execute("INSERT INTO push_log (user_id, at, coin, direction) VALUES (1, ?, 'BTC', 'long')", (datetime.now(timezone.utc).isoformat(),))
        db.init_db()
        db.init_db()
        self.assertEqual(push_policy.used(repo.list_recent_pushes(1, SINCE)), 1)


class OutcomeTest(TakenTradeCase):
    def test_an_outcome_push_does_not_count_and_comes_once(self):
        self._taken(minutes_ago=40)
        uid = repo.list_users()[0]["id"]
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        frame = _bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 100.2, 98.5, 99.0)])
        self._run(frame)
        self._run(frame)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(repo.list_recent_pushes(uid, SINCE), [])


if __name__ == "__main__":
    unittest.main()
