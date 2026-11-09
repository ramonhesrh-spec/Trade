import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_requires_login(self):
        self.client.cookies.clear()
        self.assertIn(self.client.get("/api/push/pauze", follow_redirects=False).status_code, (302, 303, 401))
        self.assertIn(self.client.post("/api/push/pauze", follow_redirects=False).status_code, (302, 303, 401))

    def test_pause_is_per_user(self):
        self.client.post("/api/push/pauze")
        other = repo.create_user("other", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(other))
        self.assertEqual(self.client.get("/api/push/pauze").json()["minutes_left"], 0)
        self.assertIsNone(repo.get_user(other)["push_paused_until"])

    def test_stale_pause_reads_as_zero_and_a_post_starts_a_fresh_one(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        repo.set_push_pause(self.uid, past)
        state = self.client.get("/api/push/pauze").json()
        self.assertEqual((state["minutes_left"], state["paused_until"]), (0, None))
        self.assertEqual(self.client.post("/api/push/pauze").json()["minutes_left"], 120)

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

    def test_backslash_and_absolute_urls_fall_back(self):
        for bad in ("/\\evil.test", "https://evil.test/", "//evil.test", "/ok\\x", "javascript:alert(1)"):
            repo_alerts = self.post(url=bad)
            self.assertEqual(repo_alerts.status_code, 200)
            self.assertEqual(repo.list_price_alerts(self.uid)[-1]["url"], "/smc", bad)
            with self.main.db.session() as conn:
                conn.execute("DELETE FROM price_alerts")

    def test_fired_alert_cannot_be_deleted(self):
        self.post()
        aid = repo.list_price_alerts(self.uid)[0]["id"]
        repo.mark_price_alert_sent(aid)
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
        r = self.client.get("/smc")                                         # in de tabel van het detailblad
        self.assertIn('class="level-bell"', r.text)
        self.assertIn('data-alarm-price="100.0"', r.text)
        self.assertIn('data-chips-url="/smc#radar-setup-1"', r.text)
        self.assertIn("alarm.js", r.text)


class SystemStatusBadgeTest(WebCase):
    def test_in_zone_counts_forming_setups_with_the_price_in_the_zone(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('XRP', 'long', 99.0, 101.0, 102.0, 97.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))
        self.main._price_cache["XRP"] = (0.0, 100.0)                                       # de radar zette hem al in de cache
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 1)       # koers 100 ligt in 99-101

    def test_status_poll_never_fetches_prices_for_the_badge(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('XRP', 'long', 99.0, 101.0, 102.0, 97.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))
        self.main._price_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_last_price", side_effect=RuntimeError("storing")) as fetch:
            r = self.client.get("/api/system_status")
        self.assertEqual(r.json()["in_zone"], 0)
        self.assertNotIn("XRP", [c.args[0] for c in fetch.call_args_list])


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


class PushBannerTest(WebCase):
    def test_banner_is_on_every_page_and_subscribe_code_loads_once(self):
        r = self.client.get("/vandaag")
        self.assertIn('id="push-banner"', r.text)
        self.assertIn("Meldingen staan uit op dit apparaat.", r.text)
        self.assertIn("push-banner.js", r.text)
        account = self.client.get("/account").text
        self.assertEqual(account.count("push-subscribe.js"), 1)            # anders koppelt de knop twee keer


class SparklineRouteTest(WebCase):
    def frame(self):
        import pandas as pd
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(hours=i)), "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
                              "close": 100.0 + i, "volume": 1.0} for i in range(200)])

    def test_one_fetch_per_coin_and_unknown_coins_are_ignored(self):
        self.main._candle_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", return_value=self.frame()) as fetch:
            data = self.client.get("/api/sparklines?coins=BTC,ETH,BTC,NOPE").json()
            self.client.get("/api/sparklines?coins=BTC")
        self.assertEqual(set(data), {"BTC", "ETH"})
        self.assertEqual(fetch.call_count, 2)                                 # de tweede aanroep komt uit de cache
        self.assertTrue(data["BTC"]["path"].startswith("M"))
        self.assertAlmostEqual(data["BTC"]["change_pct"], round((299.0 - 275.0) / 275.0 * 100, 1))     # 25 slotkoersen is 24 uur

    def test_candle_route_still_works_from_the_shared_cache(self):
        self.main._candle_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", return_value=self.frame()):
            body = self.client.get("/api/radar_candles/BTC?tf=1h&limit=10").json()
        self.assertEqual(len(body["candles"]), 10)

    def test_candle_route_only_accepts_listed_coins(self):
        self.main._candle_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", return_value=self.frame()) as fetch:
            self.assertEqual(self.client.get("/api/radar_candles/ZZZZ?tf=1h").status_code, 404)
        self.assertEqual(fetch.call_count, 0)
        self.assertEqual(self.main._candle_cache, {})

    def test_failing_exchange_gives_no_sparkline_not_an_error(self):
        self.main._candle_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", side_effect=RuntimeError("storing")):
            r = self.client.get("/api/sparklines?coins=BTC")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {})

    def test_requires_login(self):
        self.client.cookies.clear()
        self.assertIn(self.client.get("/api/sparklines?coins=BTC", follow_redirects=False).status_code, (302, 303, 401))


class BewijsCurveTest(WebCase):
    def test_curve_section_shows_per_type_with_excluded_count(self):
        with db.session() as conn:
            for outcome in ("take_profit", "stop_loss", None):
                conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                                take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                                VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', ?, ?, ?)""",
                             (outcome, db.now_iso() if outcome else None, db.now_iso()))
        r = self.client.get("/bewijs")
        self.assertIn("Resultaatcurve per soort", r.text)
        self.assertIn('class="equity-dd"', r.text)
        self.assertIn("1 open of vervallen, niet meegeteld", r.text)


class BewijsViewerTest(WebCase):
    def seed(self):
        with db.session() as conn:
            for trade_type in ("smc", "don55_trend"):
                conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                                take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                                VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, ?, 'stop_loss', ?, ?)""", (trade_type, db.now_iso(), db.now_iso()))

    def test_a_student_sees_no_trial_engine_in_curves_or_hour_grid(self):
        self.seed()
        self.main._ceo_cache.update(at=0.0, id=None)
        student = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        label = self.main.track_record.TYPE_LABELS.get("don55_trend", "don55_trend")
        ceo_page = self.client.get("/bewijs").text
        self.assertIn(f"<strong>{label}</strong>", ceo_page)                     # de CEO ziet de proefmotor wel
        self.client.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(student))
        page = self.client.get("/bewijs").text
        self.assertNotIn(f"<strong>{label}</strong>", page)
        rows = self.main.report_rows(repo.get_user(student))
        self.assertEqual(self.main.track_record.hour_grid(rows, 0.0)["total"], 1)


class BewijsHourGridTest(WebCase):
    def test_hour_grid_section(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                            take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                            VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', 'take_profit', ?, ?)""", (db.now_iso(), db.now_iso()))
        r = self.client.get("/bewijs")
        self.assertIn("Uurkaart", r.text)
        self.assertIn('class="hourmap"', r.text)
        self.assertIn("is-weak", r.text)                                       # één trade is te weinig voor kleur


if __name__ == "__main__":
    unittest.main()
