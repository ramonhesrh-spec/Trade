"""Beheer voor de eigenaar (fase 2, R6): volg-sets, uitnodigingen per code, de leerlingenlijst en het filter op de pushmeldingen."""
import random
import unittest
from datetime import datetime, timedelta, timezone

from app import beheer, push_policy, repo
from tests.test_samenval import DbCase

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


class PureTests(unittest.TestCase):
    def test_coins_lezen(self):
        self.assertEqual(beheer.parse_coins("btc, ETH  sol,btc;link"), ["BTC", "ETH", "SOL", "LINK"])
        self.assertEqual(beheer.parse_coins("btc, <script>, e"), ["BTC"])
        self.assertEqual(beheer.parse_coins(""), [])

    def test_code_zonder_verwarrende_tekens(self):
        code = beheer.new_code(random.Random(1))
        self.assertRegex(code, r"^HES-[A-Z2-9]{4}$")
        self.assertFalse(set(code[4:]) & set("O0I1L"))

    def test_code_normaliseren(self):
        self.assertEqual(beheer.normalize_code(" hes-7q2k "), "HES-7Q2K")

    def test_uitnodiging_bruikbaar(self):
        inv = {"max_uses": 5, "uses": 1, "expires_at": (NOW + timedelta(days=5)).isoformat()}
        self.assertTrue(beheer.invite_usable(inv, NOW))
        self.assertFalse(beheer.invite_usable({**inv, "uses": 5}, NOW))
        self.assertFalse(beheer.invite_usable({**inv, "expires_at": (NOW - timedelta(minutes=1)).isoformat()}, NOW))

    def test_uitnodiging_als_regel(self):
        inv = {"code": "HES-7Q2K", "max_uses": 5, "uses": 1, "expires_at": (NOW + timedelta(days=5, hours=2)).isoformat(), "set_name": "Alts"}
        self.assertEqual(beheer.invite_line(inv, NOW), "Alts · 1 van 5 gebruikt · verloopt over 5 d")
        self.assertEqual(beheer.invite_line({**inv, "set_name": None, "expires_at": (NOW + timedelta(hours=3)).isoformat()}, NOW),
                         "Geen set · 1 van 5 gebruikt · verloopt over 3 u")
        self.assertEqual(beheer.invite_line({**inv, "uses": 5}, NOW), "Alts · 5 van 5 gebruikt · op")
        self.assertEqual(beheer.invite_line({**inv, "expires_at": (NOW - timedelta(days=1)).isoformat()}, NOW), "Alts · 1 van 5 gebruikt · verlopen")

    def test_laatst_gekeken(self):
        self.assertEqual(beheer.seen_text((NOW - timedelta(minutes=12)).isoformat(), NOW), "12 min")
        self.assertEqual(beheer.seen_text((NOW - timedelta(seconds=20)).isoformat(), NOW), "net")
        self.assertEqual(beheer.seen_text((NOW - timedelta(hours=1, minutes=5)).isoformat(), NOW), "1 u")
        self.assertEqual(beheer.seen_text((NOW - timedelta(hours=30)).isoformat(), NOW), "gisteren")
        self.assertEqual(beheer.seen_text((NOW - timedelta(days=6)).isoformat(), NOW), "6 d")
        self.assertIsNone(beheer.seen_text(None, NOW))

    def test_initialen(self):
        self.assertEqual(beheer.initials("mark"), "MA")
        self.assertEqual(beheer.initials("Mark V."), "MV")
        self.assertEqual(beheer.initials("noor_a"), "NA")


class PushFilterTests(unittest.TestCase):
    def test_zonder_set_altijd(self):
        self.assertTrue(push_policy.in_follow_set(None, "DOGE"))

    def test_met_set_alleen_eigen_coins(self):
        self.assertTrue(push_policy.in_follow_set({"BTC", "ETH"}, "BTC"))
        self.assertFalse(push_policy.in_follow_set({"BTC", "ETH"}, "DOGE"))


class RepoTests(DbCase):
    def setUp(self):
        super().setUp()
        self.a = repo.get_user_by_username("a")["id"]
        self.b = repo.create_user("b", "x", 0, 1)

    def test_sets_met_leden(self):
        kern = repo.create_follow_set("Kern", ["BTC", "ETH"])
        repo.set_user_follow_set(self.b, kern)
        sets = repo.list_follow_sets()
        self.assertEqual([(s["name"], s["coins"], s["members"]) for s in sets], [("Kern", ["BTC", "ETH"], 1)])
        self.assertEqual(repo.follow_set_coins(self.b), {"BTC", "ETH"})
        self.assertIsNone(repo.follow_set_coins(self.a))

    def test_dubbele_naam_geeft_none(self):
        repo.create_follow_set("Kern", ["BTC"])
        self.assertIsNone(repo.create_follow_set("Kern", ["ETH"]))

    def test_een_set_weghalen_maakt_leden_vrij(self):
        kern = repo.create_follow_set("Kern", ["BTC"])
        repo.set_user_follow_set(self.b, kern)
        repo.delete_follow_set(kern)
        self.assertIsNone(repo.get_user(self.b)["follow_set_id"])
        self.assertEqual(repo.list_follow_sets(), [])

    def test_registreren_met_code_kent_de_set_toe_en_telt(self):
        alts = repo.create_follow_set("Alts", ["SOL"])
        repo.create_invite("HES-AAAA", alts, 2, (NOW + timedelta(days=7)).isoformat())
        uid = repo.register_user("nieuw", "h", invite_code="HES-AAAA", now_iso=NOW.isoformat())
        self.assertEqual(repo.get_user(uid)["follow_set_id"], alts)
        self.assertEqual(repo.list_invites()[0]["uses"], 1)

    def test_een_volle_of_verlopen_code_registreert_niet(self):
        repo.create_invite("HES-BBBB", None, 1, (NOW + timedelta(days=7)).isoformat())
        self.assertIsNotNone(repo.register_user("een", "h", invite_code="HES-BBBB", now_iso=NOW.isoformat()))
        self.assertIsNone(repo.register_user("twee", "h", invite_code="HES-BBBB", now_iso=NOW.isoformat()))
        self.assertIsNone(repo.get_user_by_username("twee"))
        repo.create_invite("HES-CCCC", None, 3, (NOW - timedelta(days=1)).isoformat())
        self.assertIsNone(repo.register_user("drie", "h", invite_code="HES-CCCC", now_iso=NOW.isoformat()))
        self.assertIsNone(repo.register_user("vier", "h", invite_code="HES-ZZZZ", now_iso=NOW.isoformat()))

    def test_een_bezette_naam_kost_geen_gebruik(self):
        repo.create_invite("HES-DDDD", None, 2, (NOW + timedelta(days=7)).isoformat())
        self.assertIsNone(repo.register_user("a", "h", invite_code="HES-DDDD", now_iso=NOW.isoformat()))
        self.assertEqual(repo.list_invites()[0]["uses"], 0)

    def test_dubbele_code_geeft_none(self):
        repo.create_invite("HES-EEEE", None, 1, NOW.isoformat())
        self.assertIsNone(repo.create_invite("HES-EEEE", None, 1, NOW.isoformat()))


class SendKansPushSetTests(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        self.sent = []

    def send(self, coin):
        import asyncio
        from unittest import mock
        from app import push_notify

        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            self.sent.append(coin)
        with mock.patch("app.push_notify.send_push", fake_push):
            return asyncio.run(push_notify.send_kans_push(self.uid, coin, "long", f"{coin} long", "body", "/kans/1"))

    def test_een_coin_buiten_de_set_wordt_een_rustige_melding(self):
        from app import db
        repo.set_user_follow_set(self.uid, repo.create_follow_set("Kern", ["BTC"]))
        self.assertTrue(self.send("BTC"))
        self.assertFalse(self.send("DOGE"))
        self.assertEqual(self.sent, ["BTC"])
        with db.session() as conn:
            bodies = [r["body"] for r in conn.execute("SELECT body FROM notifications WHERE user_id = ?", (self.uid,))]
        self.assertEqual(len(bodies), 1)
        self.assertIn("niet in je volg-set Kern", bodies[0])

    def test_zonder_set_komt_alles(self):
        self.assertTrue(self.send("DOGE"))


if __name__ == "__main__":
    unittest.main()
