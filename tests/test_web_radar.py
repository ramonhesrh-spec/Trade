import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security


class WebRadarTests(unittest.TestCase):
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
        with db.session() as conn:
            conn.execute(
                """INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                   created_at, updated_at) VALUES ('XRP', 'long', 99.0, 100.0, 101.0, 98.0, 110.0, 1.0, ?, ?)""",
                (db.now_iso(), db.now_iso()))
            conn.execute(
                """INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                   take_profit, trade_type, created_at) VALUES (NULL, 'ETH', 'long', 'x', 'hoog', 1, 100, 97, 106, 'smc', ?)""",
                (db.now_iso(),))
            for i, outcome in enumerate(["take_profit", "stop_loss", "stop_loss"]):
                conn.execute(
                    """INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                       take_profit, trade_type, auto_outcome, auto_outcome_at, created_at) VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1,
                       100, 99, 102, 'patroon', ?, ?, ?)""", (outcome, db.now_iso(), db.now_iso()))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: {"XRP": 102.0, "ETH": 103.0}[coin])
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_radar_pagina_toont_plan_status_en_live_r(self):
        r = self.client.get("/smc")
        self.assertEqual(r.status_code, 200)
        self.assertIn("SMC-radar", r.text)
        self.assertIn("XRP", r.text)
        self.assertIn("Wacht op de zone", r.text)
        self.assertIn("Zet een limietorder op 100.00", r.text)   # limietprijs = bovenrand van de long-zone, in de drie stappen
        self.assertIn("Wacht tot de koers in de zone", r.text)
        self.assertIn("+1.00R", r.text)                # ETH long entry 100, stop 97, koers 103
        self.assertIn("data-levelchart", r.text)
        self.assertIn("lightweight-charts-4.2.0", r.text)
        self.assertIn("r-progress", r.text)                # voortgang tussen stop en doel bij de open trade
        self.assertIn("Doel +", r.text)

    def test_api_radar_levert_live_data_per_kaart(self):
        r = self.client.get("/api/radar")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        keys = list(data)
        self.assertEqual(len(keys), 2)
        setup = data[[k for k in keys if k.startswith("setup:")][0]]
        self.assertEqual(setup["state"], "wacht")
        self.assertAlmostEqual(setup["distance_pct"], 2.0)
        signal = data[[k for k in keys if k.startswith("signal:")][0]]
        self.assertAlmostEqual(signal["live_r"], 1.0)
        self.assertEqual(signal["chart"]["entry"], 100.0)
        self.assertEqual(signal["chart"]["price"], 103.0)

    def test_koers_cache_en_mislukte_ophaal_houdt_laatste_stand(self):
        self.client.get("/api/radar")
        self.client.get("/api/radar")
        self.assertEqual(self.main.exchange.fetch_last_price.call_count, 2)     # twee coins, één keer opgehaald
        self.main._price_cache["XRP"] = (0.0, 102.0)                              # verlopen
        with mock.patch.object(self.main.exchange, "fetch_last_price", side_effect=RuntimeError("storing")):
            data = self.client.get("/api/radar").json()
        setup = data[[k for k in data if k.startswith("setup:")][0]]
        self.assertEqual(setup["price"], 102.0)

    def test_radar_candles_vorm_en_cache(self):
        import pandas as pd
        main = self.main
        main._candle_cache.clear()
        times = pd.date_range("2026-10-09 00:00", periods=120, freq="15min", tz="UTC")
        df = pd.DataFrame({"timestamp": times, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0})
        with mock.patch.object(main.exchange, "fetch_ohlcv", return_value=df) as fetch:
            r = self.client.get("/api/radar_candles/xrp?tf=15m&limit=96")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual((body["coin"], body["tf"], len(body["candles"])), ("XRP", "15m", 96))
            self.assertEqual(body["candles"][-1], [int(times[-1].timestamp()), 100.0, 101.0, 99.0, 100.5])
            self.assertEqual(body["candles"][0][0], int(times[-96].timestamp()))
            self.client.get("/api/radar_candles/XRP?tf=15m&limit=50")                 # andere limit, zelfde cache-regel
            self.assertEqual(fetch.call_count, 1)
            self.client.get("/api/radar_candles/XRP?tf=1h")
            self.assertEqual(fetch.call_count, 2)
            main._candle_cache[("XRP", "15m")] = (0.0, main._candle_cache[("XRP", "15m")][1])     # verlopen
            self.client.get("/api/radar_candles/XRP?tf=15m")
            self.assertEqual(fetch.call_count, 3)

    def test_radar_candles_valt_terug_op_oude_stand_en_weigert_rommel(self):
        main = self.main
        main._candle_cache.clear()
        main._candle_cache[("XRP", "15m")] = (0.0, [[1, 1.0, 2.0, 0.5, 1.5]])
        with mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=RuntimeError("storing")):
            self.assertEqual(self.client.get("/api/radar_candles/XRP").json()["candles"], [[1, 1.0, 2.0, 0.5, 1.5]])
            self.assertEqual(self.client.get("/api/radar_candles/ETH").status_code, 503)    # niets onthouden
        self.assertEqual(self.client.get("/api/radar_candles/XRP?tf=7m").status_code, 422)
        self.assertEqual(self.client.get("/api/radar_candles/XR-P").status_code, 422)
        anon = TestClient(main.app, follow_redirects=False)
        self.assertIn(anon.get("/api/radar_candles/XRP").status_code, (302, 303, 401, 403))

    def test_bewijs_pagina_met_eerlijke_cijfers(self):
        r = self.client.get("/bewijs")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Chart-patroon", r.text)
        self.assertIn("Nog te weinig data", r.text)    # 3 trades < 30
        self.assertIn("Alle meldingen samen", r.text)
        self.assertIn("proof-spark", r.text)
        self.assertIn("1 winst, 2 verlies", r.text)

    def test_pagina_s_vragen_om_inloggen(self):
        anon = TestClient(self.main.app, follow_redirects=False)
        for path in ("/smc", "/api/radar", "/bewijs"):
            self.assertIn(anon.get(path).status_code, (302, 303, 401, 403), path)

    def test_navigatie_heeft_radar_en_bewijs(self):
        r = self.client.get("/bewijs")
        self.assertIn('>SMC</a>', r.text)
        self.assertIn('>Bewijs</a>', r.text)


if __name__ == "__main__":
    unittest.main()
