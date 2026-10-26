"""Beheer op /beheer (fase 2, R6): alleen de eigenaar, sets per leerling, uitnodigingscodes en registreren met of zonder code."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from web import main


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "b.db"))
        self.patch.start()
        db.init_db()
        main._ceo_cache.update(at=0, id=None)
        self.client = TestClient(main.app)
        self.ceo = repo.create_user("ceo", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.mark = repo.create_user("mark", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.lotte = repo.create_user("lotte", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.login(self.ceo)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()
        main._ceo_cache.update(at=0, id=None)

    def login(self, uid):
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))


class OwnerOnlyTests(Base):
    def test_een_leerling_ziet_beheer_niet_en_kan_niets_wijzigen(self):
        self.login(self.mark)
        self.assertEqual(self.client.get("/beheer").status_code, 404)
        self.assertEqual(self.client.post("/beheer/sets", data={"name": "X", "coins": "BTC"}).status_code, 404)
        self.assertEqual(self.client.post(f"/beheer/leerling/{self.lotte}/set", data={"set_id": ""}).status_code, 404)
        self.assertEqual(self.client.post("/beheer/uitnodiging", data={"uses": 1, "days": 7}).status_code, 404)
        self.assertEqual(repo.list_follow_sets(), [])
        self.assertNotIn('href="/beheer"', self.client.get("/account").text)

    def test_de_eigenaar_ziet_beheer_in_het_blad(self):
        self.assertIn('href="/beheer"', self.client.get("/account").text)

    def test_leerlingen_met_set_week_r_en_laatst_gekeken(self):
        kern = repo.create_follow_set("Kern", ["BTC", "ETH"])
        repo.set_user_follow_set(self.mark, kern)
        repo.record_visit(self.mark, datetime.now(timezone.utc) - timedelta(minutes=12))
        html = self.client.get("/beheer").text
        self.assertIn("Leerlingen · 2", html)
        sec = html[html.index('id="leerlingen"'):html.index('id="sets"')]
        self.assertIn(">mark<", sec)
        self.assertIn(">Kern<", sec)
        self.assertIn('class="bh-seen">12 min<', sec)
        self.assertIn('class="bh-r">0,0 R<', sec)
        lotte = sec[sec.index(">lotte<"):]
        self.assertNotIn("bh-seen", lotte[:lotte.index("</summary>")])          # nooit gekeken: geen getal
        self.assertNotIn(">ceo<", sec)

    def test_set_maken_toewijzen_en_weghalen(self):
        self.client.post("/beheer/sets", data={"name": "Alts", "coins": "sol, link avax"})
        alts = repo.list_follow_sets()[0]
        self.assertEqual(alts["coins"], ["SOL", "LINK", "AVAX"])
        self.client.post(f"/beheer/leerling/{self.mark}/set", data={"set_id": str(alts["id"])})
        self.assertEqual(repo.follow_set_coins(self.mark), {"SOL", "LINK", "AVAX"})
        self.client.post(f"/beheer/leerling/{self.mark}/set", data={"set_id": "999"})          # onbekende set: geen set
        self.assertIsNone(repo.follow_set_coins(self.mark))
        r = self.client.post("/beheer/sets", data={"name": "Alts", "coins": "BTC"}, follow_redirects=False)
        self.assertIn("fout=", r.headers["location"])
        self.client.post(f"/beheer/sets/{alts['id']}/verwijder")
        self.assertEqual(repo.list_follow_sets(), [])

    def test_uitnodiging_maken_met_kopieerlink(self):
        kern = repo.create_follow_set("Kern", ["BTC"])
        self.client.post("/beheer/uitnodiging", data={"set_id": str(kern), "uses": 5, "days": 7})
        inv = repo.list_invites()[0]
        self.assertRegex(inv["code"], r"^HES-[A-Z2-9]{4}$")
        self.assertEqual((inv["max_uses"], inv["set_id"]), (5, kern))
        html = self.client.get("/beheer").text
        self.assertIn(f'data-copy="http://testserver/registreer?code={inv["code"]}"', html)
        self.assertIn("Kern · 0 van 5 gebruikt · verloopt over", html)
        self.assertIn("Open uitnodigingen · 1", html)


class RegisterTests(Base):
    def setUp(self):
        super().setUp()
        self.client.cookies.clear()

    def register(self, name, code=""):
        return self.client.post("/registreer", data={"username": name, "password": "wachtwoord-1", "password_confirm": "wachtwoord-1", "code": code},
                                follow_redirects=False)

    def test_open_registratie_zonder_code_blijft_werken(self):
        self.assertEqual(self.register("sanne").status_code, 303)
        self.assertIsNone(repo.get_user_by_username("sanne")["follow_set_id"])

    def test_een_code_kent_de_set_toe(self):
        alts = repo.create_follow_set("Alts", ["SOL"])
        repo.create_invite("HES-AAAA", alts, 1, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        self.assertEqual(self.register("sanne", " hes-aaaa ").status_code, 303)
        self.assertEqual(repo.get_user_by_username("sanne")["follow_set_id"], alts)
        r = self.register("tim", "HES-AAAA")
        self.assertEqual(r.status_code, 400)
        self.assertIn("onbekend, verlopen of al op", r.text)

    def test_met_de_vlag_is_een_code_nodig(self):
        with mock.patch.object(config, "REGISTRATION_REQUIRES_INVITE", True):
            r = self.register("sanne")
            self.assertEqual(r.status_code, 400)
            self.assertIn("uitnodigingscode", r.text)
            self.assertIsNone(repo.get_user_by_username("sanne"))
            repo.create_invite("HES-BBBB", None, 1, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
            self.assertEqual(self.register("sanne", "HES-BBBB").status_code, 303)

    def test_het_formulier_neemt_de_code_uit_de_link_over(self):
        self.assertIn('value="HES-7Q2K"', self.client.get("/registreer?code=hes-7q2k").text)


if __name__ == "__main__":
    unittest.main()
