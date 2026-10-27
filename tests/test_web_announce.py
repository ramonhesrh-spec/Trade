"""De aankondiging op het web: /nieuw zonder inlog in beide fases met een linkvoorbeeld, het verhaal één keer per ingelogde gebruiker na het
moment, en de links op de loginpagina en in het menu zolang de aankondiging loopt."""
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import announce, config, db, repo, security
from web import main

NOW = datetime.now(timezone.utc)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db")),
                        mock.patch.object(config, "ANNOUNCEMENT_AT", "")]
        for p in self.patches:
            p.start()
        db.init_db()
        main._ceo_cache.update(at=0, id=None)
        self.client = TestClient(main.app)
        self.ceo = repo.create_user("ceo", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.mark = repo.create_user("mark", security.hash_password("wachtwoord-123456"), 0, 1.0)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
        main._ceo_cache.update(at=0, id=None)

    def login(self, uid):
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))

    def before(self):
        repo.set_announcement_at(NOW + timedelta(days=2, hours=3))

    def after(self):
        repo.set_announcement_at(NOW - timedelta(minutes=5))


class NieuwPageTests(Base):
    def test_voor_het_moment_een_aftelklok_zonder_inlog(self):
        self.before()
        r = self.client.get("/nieuw")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Peil.", r.text)
        self.assertIn("HesPulse wordt vernieuwd.", r.text)
        self.assertIn('role="timer"', r.text)
        self.assertIn(f'data-target="{repo.get_announcement_at().isoformat()}"', r.text)
        for promise in announce.PROMISES:
            self.assertIn(promise, r.text)
        self.assertNotIn("Het is live.", r.text)
        self.assertNotIn('id="wn-story"', r.text)

    def test_na_het_moment_live_met_knop_naar_login(self):
        self.after()
        r = self.client.get("/nieuw")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Het is live.", r.text)
        self.assertNotIn('role="timer"', r.text)
        for card in announce.CARDS:
            self.assertIn(card["title"], r.text)
        self.assertRegex(r.text, r'<a[^>]*href="/login"[^>]*>Open HesPulse</a>')

    def test_ingelogd_gaat_de_knop_naar_nu(self):
        self.after()
        self.login(self.mark)
        self.assertRegex(self.client.get("/nieuw").text, r'<a[^>]*href="/vandaag"[^>]*>Open HesPulse</a>')

    def test_zonder_tijd_de_live_versie(self):
        r = self.client.get("/nieuw")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Het is live.", r.text)

    def test_linkvoorbeeld_voor_discord_en_whatsapp(self):
        html = self.client.get("/nieuw").text
        for prop in ("og:title", "og:description", "og:image", "og:url"):
            self.assertIn(f'property="{prop}"', html)
        self.assertIn('name="twitter:card" content="summary_large_image"', html)
        image = re.search(r'property="og:image" content="([^"]+)"', html).group(1)
        self.assertTrue(image.startswith("http"), image)                 # chats halen geen relatieve url op
        self.assertTrue(image.split("?")[0].endswith("/static/og/nieuw.png"))
        from PIL import Image
        with Image.open(main.BASE_DIR / "static" / "og" / "nieuw.png") as img:
            self.assertEqual(img.size, (1200, 630))

    def test_geen_externe_afbeeldingen(self):
        html = self.client.get("/nieuw").text
        self.assertIsNone(re.search(r'<img[^>]+src="https?://', html))

    def test_het_aantal_coins_klopt(self):
        self.after()
        self.assertIn(f"{len(config.FIXED_COINS)} coins", self.client.get("/nieuw").text)


class StoryTests(Base):
    def test_na_het_moment_een_keer_per_gebruiker(self):
        self.after()
        self.login(self.mark)
        self.assertIn('id="wn-story"', self.client.get("/account").text)
        r = self.client.post("/api/wat-is-nieuw/gezien")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.post("/api/wat-is-nieuw/gezien").status_code, 200)    # twee keer mag
        self.assertNotIn('id="wn-story"', self.client.get("/account").text)
        self.login(self.ceo)
        self.assertIn('id="wn-story"', self.client.get("/account").text)

    def test_niet_voor_het_moment_en_niet_zonder_tijd(self):
        self.login(self.mark)
        self.assertNotIn('id="wn-story"', self.client.get("/account").text)
        self.before()
        self.assertNotIn('id="wn-story"', self.client.get("/account").text)

    def test_nooit_voor_een_bezoeker_zonder_inlog(self):
        self.after()
        self.assertNotIn('id="wn-story"', self.client.get("/login").text)
        self.assertNotIn('id="wn-story"', self.client.get("/nieuw").text)
        r = self.client.post("/api/wat-is-nieuw/gezien", follow_redirects=False)
        self.assertIn(r.status_code, (303, 401))

    def test_opnieuw_te_openen_via_het_menu(self):
        self.login(self.mark)
        repo.mark_story_seen(self.mark, announce.STORY_VERSION)
        self.assertIn('href="/wat-is-nieuw"', self.client.get("/account").text)
        page = self.client.get("/wat-is-nieuw").text
        self.assertIn('id="wn-story"', page)
        for card in announce.CARDS:
            self.assertIn(card["title"], page)
        self.assertIn("Sla over", page)
        self.assertIn("Aan de slag", page)

    def test_wat_is_nieuw_vraagt_een_inlog(self):
        r = self.client.get("/wat-is-nieuw", follow_redirects=False)
        self.assertEqual(r.headers.get("location"), "/login")


class LinkTests(Base):
    def test_loginpagina_linkt_naar_nieuw_zolang_het_loopt(self):
        self.assertNotIn('href="/nieuw"', self.client.get("/login").text)
        self.before()
        self.assertIn('href="/nieuw"', self.client.get("/login").text)
        repo.set_announcement_at(NOW - timedelta(days=announce.RUN_DAYS, minutes=1))
        self.assertNotIn('href="/nieuw"', self.client.get("/login").text)

    def test_menu_linkt_naar_nieuw_zolang_het_loopt(self):
        self.login(self.mark)
        self.assertNotIn('href="/nieuw"', self.client.get("/account").text)
        self.before()
        self.assertIn('href="/nieuw"', self.client.get("/account").text)


if __name__ == "__main__":
    unittest.main()
