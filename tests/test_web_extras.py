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


class PriceAlertRouteTest(WebCase):
    def post(self, **body):
        return self.client.post("/api/prijsalarm", json={"coin": "BTC", "price": 105.0, "label": "Doel", "url": "/smc#radar-setup-1", **body})

    def test_create_list_and_delete(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["side"], "above")                       # koers 100, niveau 105
        self.assertIn("15 minuten", r.json()["message"])
        alerts = self.client.get("/api/prijsalarm").json()["alerts"]
        self.assertEqual([(a["coin"], a["price"]) for a in alerts], [("BTC", 105.0)])
        self.assertEqual(self.client.delete(f"/api/prijsalarm/{alerts[0]['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/prijsalarm").json()["alerts"], [])
        self.assertEqual(self.client.delete(f"/api/prijsalarm/{alerts[0]['id']}").status_code, 404)

    def test_rejects_unknown_coin_bad_price_and_foreign_url(self):
        self.assertEqual(self.post(coin="NOPE").status_code, 400)
        self.assertEqual(self.post(price="abc").status_code, 400)
        self.assertEqual(self.post(price=-1).status_code, 400)
        r = self.post(url="https://evil.test/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(repo.list_price_alerts(self.uid)[0]["url"], "/smc")

    def test_coin_is_normalised_and_bad_bodies_are_400(self):
        self.assertEqual(self.post(coin="  btc ").status_code, 200)
        self.assertEqual(repo.list_price_alerts(self.uid)[0]["coin"], "BTC")
        self.assertEqual(self.client.post("/api/prijsalarm", content=b'{"coin": "BTC", "price": Infinity}',
                                          headers={"Content-Type": "application/json"}).status_code, 400)
        self.assertEqual(self.post(price=True).status_code, 400)
        self.assertEqual(self.client.post("/api/prijsalarm", json=[1]).status_code, 400)
        self.assertEqual(self.client.post("/api/prijsalarm", content=b"nope").status_code, 400)

    def test_alerts_are_per_user(self):
        self.post()
        other = repo.create_user("other", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        aid = repo.list_price_alerts(self.uid)[0]["id"]
        self.client.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(other))
        self.assertEqual(self.client.get("/api/prijsalarm").json()["alerts"], [])
        self.assertEqual(self.client.delete(f"/api/prijsalarm/{aid}").status_code, 404)

    def test_requires_login(self):
        self.client.cookies.clear()
        self.assertIn(self.client.get("/api/prijsalarm", follow_redirects=False).status_code, (302, 303, 401))

    def test_cap_on_open_alerts(self):
        from app import price_alerts
        for i in range(price_alerts.MAX_OPEN_PER_USER):
            self.assertEqual(self.post(price=101.0 + i).status_code, 200)
        self.assertEqual(self.post(price=200.0).status_code, 409)

    def test_radar_card_has_a_bell_per_level(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('BTC', 'long', 99.0, 100.0, 101.0, 98.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))
        r = self.client.get("/smc")
        self.assertIn('class="level-bell"', r.text)
        self.assertIn('data-alarm-price="100.0"', r.text)
        self.assertIn("alarm.js", r.text)


class SystemStatusBadgeTest(WebCase):
    def test_in_zone_counts_forming_setups_with_the_price_in_the_zone(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('XRP', 'long', 99.0, 101.0, 102.0, 97.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 1)       # koers 100 ligt in 99-101


class PriceAgeTest(WebCase):
    def setUp(self):
        super().setUp()
        self.main._price_fetched_at.clear()
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('XRP', 'long', 99.0, 101.0, 102.0, 97.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))

    def test_fresh_fetch_gives_a_small_age(self):
        r = self.client.get("/api/radar")
        self.assertLessEqual(int(r.headers["X-Price-Age"]), 1)

    def test_failed_fetch_keeps_the_old_price_but_the_age_grows(self):
        import time
        self.client.get("/api/radar")
        self.main._price_fetched_at["XRP"] = time.time() - 300
        self.main._price_cache["XRP"] = (0.0, 100.0)                         # verlopen: er wordt opnieuw opgehaald
        with mock.patch.object(self.main.exchange, "fetch_last_price", side_effect=RuntimeError("storing")):
            r = self.client.get("/api/radar")
        self.assertGreaterEqual(int(r.headers["X-Price-Age"]), 300)

    def test_dot_carries_the_threshold(self):
        self.assertIn('data-stale-after="120"', self.client.get("/smc").text)
        self.assertIn("X-Price-Age", self.client.get("/api/vandaag").headers)


if __name__ == "__main__":
    unittest.main()
