import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security


def scenario_row(**kw):
    row = {"direction": "long", "trigger_type": "close_above", "trigger_level": 101.0, "entry": 100.8, "stop_loss": 99.8,
           "take_profit": 103.0, "reason": "Break boven gisteren hoog."}
    row.update(kw)
    return row


class WebVandaagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        db.init_db()
        from web import main
        self.main = main
        main._price_cache.clear()
        self.client = TestClient(main.app)
        user_id = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(user_id))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_empty_state_is_honest_and_page_works(self):
        r = self.client.get("/vandaag")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Nog geen script geschreven", r.text)
        self.assertIn("De verzamelaar is net gestart", r.text)
        self.assertIn("Geen nieuws van de laatste 12 uur", r.text)
        self.assertIn("vd-timeline", r.text)

    def test_page_shows_script_scenario_liquidations_events_and_score(self):
        now = datetime.now(timezone.utc)
        repo.insert_market_script("BTC", "BTC test onder gisteren hoog.", "long", "m", [scenario_row()], 1,
                                  (now + timedelta(hours=10)).isoformat())
        repo.add_liquidations([("BTC", now.replace(second=0, microsecond=0).isoformat(), 3e6, 1e6, 5)])
        repo.insert_market_event(now.isoformat(), "Binance", "Binance will list SOL", "https://x/1", "SOL", "long", "hoog", "Binance lijst SOL.")
        r = self.client.get("/vandaag")
        self.assertEqual(r.status_code, 200)
        for text in ("BTC test onder gisteren hoog.", "5m-candle sluit boven 101", "Wacht op de voorwaarde", "Limietorder",
                     "4,0M", "Binance lijst SOL.", "1 long-scenario's", "Score: wat HesPulse zelf voorspelde",
                     "Break boven gisteren hoog."):
            self.assertIn(text, r.text, text)

    def test_api_returns_prices_and_scenario_state(self):
        repo.insert_market_script("BTC", "x", "long", "m", [scenario_row()], 0, (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        data = self.client.get("/api/vandaag").json()
        self.assertEqual(data["prices"]["BTC"], 100.0)
        (sc,) = data["scenarios"].values()
        self.assertEqual(sc["state"], "waiting")
        self.assertAlmostEqual(sc["to_trigger_pct"], 1.0)

    def test_login_required_and_nav_and_landing_redirect(self):
        anon = TestClient(self.main.app)
        self.assertIn(anon.get("/vandaag", follow_redirects=False).status_code, (302, 303, 401))
        page = self.client.get("/vandaag").text
        self.assertIn('href="/vandaag"', page)
        self.assertIn(">Journaal<", page)
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/vandaag")


    def test_public_landing_shows_live_vandaag_without_scenarios_and_manifest_opens_on_vandaag(self):
        now = datetime.now(timezone.utc)
        repo.insert_market_script("BTC", "Geheime samenvatting", "long", "m", [scenario_row()], 0, (now + timedelta(hours=10)).isoformat())
        anon = TestClient(self.main.app)
        page = anon.get("/").text
        self.assertIn("Vandaag, live", page)
        self.assertIn("vd-timeline", page)
        self.assertIn("1 long-scenario", page)
        self.assertNotIn("Geheime samenvatting", page)           # scenario's en duiding blijven achter het inloggen
        self.assertNotIn("Limietorder", page)
        self.assertEqual(anon.get("/static/manifest.json").json()["start_url"], "/vandaag")
        self.assertEqual(self.client.get("/dashboard", follow_redirects=False).headers["location"], "/vandaag")


    def test_meldingen_page_groups_by_day_with_chip_and_keeps_line_breaks(self):
        uid = repo.get_user_by_username("tester")["id"]
        repo.create_notification(uid, "update", "Nieuw in HesPulse", "Regel een\nRegel twee", "/vandaag")
        r = self.client.get("/meldingen")
        self.assertEqual(r.status_code, 200)
        for text in ("Vandaag", "Nieuw in HesPulse", "nf-chip chip-new", "Regel een\nRegel twee", "alles gelezen (1)", "zojuist"):
            self.assertIn(text, r.text, text)


if __name__ == "__main__":
    unittest.main()
