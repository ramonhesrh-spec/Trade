import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security


class WebCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        db.init_db()
        from web import main
        self.main = main
        main._price_cache.clear()
        self.client = TestClient(main.app)
        self.uid = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(self.uid))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()


class PauseRouteTest(WebCase):
    def test_toggle_sets_two_hours_and_a_second_tap_ends_it(self):
        self.assertEqual(self.client.get("/api/push/pauze").json(), {"paused_until": None, "minutes_left": 0, "label": "Pauze"})
        on = self.client.post("/api/push/pauze").json()
        self.assertEqual(on["minutes_left"], 120)
        self.assertEqual(on["label"], "Stil 2:00")
        self.assertIsNotNone(repo.get_user(self.uid)["push_paused_until"])
        off = self.client.post("/api/push/pauze").json()
        self.assertEqual(off["minutes_left"], 0)
        self.assertIsNone(repo.get_user(self.uid)["push_paused_until"])

    def test_button_shows_remaining_time_on_every_page(self):
        r = self.client.get("/bewijs")
        self.assertIn('id="push-pause"', r.text)
        self.assertIn(">Pauze<", r.text)
        self.client.post("/api/push/pauze")
        r = self.client.get("/bewijs")
        self.assertIn("Stil 2:00", r.text)
        self.assertIn('aria-pressed="true"', r.text)
        self.assertIn("pause.js", r.text)


if __name__ == "__main__":
    unittest.main()
