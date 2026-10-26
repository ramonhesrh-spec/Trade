"""Het Logboek op /signalen (fase 2, R3): de dagtijdlijn met alleen eigen data, de signalenlijst en de weg naar het Journaal."""
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from web import main


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "l.db"))
        self.patch.start()
        db.init_db()
        main._price_cache.clear()
        self.client = TestClient(main.app)
        self.anna = repo.create_user("anna", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.bram = repo.create_user("bram", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.login(self.anna)
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def login(self, uid):
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))

    def signal(self, **kw):
        data = {"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": "zone_radar", "price": 100.0, "stop_loss": 101.0,
                "take_profit": 98.0, "confidence": "x", "technical_confirmed": 1, "hard_gates_ok": 1, **kw}
        return repo.insert_signal(data)

    def lb(self, html):
        return html[html.index('<section class="lb"'):html.index("</section>", html.index('<section class="lb"'))]


class TimelinePageTests(Base):
    def test_zonder_iets_staat_vandaag_er_met_nul(self):
        sec = self.lb(self.client.get("/signalen").text)
        self.assertIn(">Vandaag<", sec)
        self.assertIn('class="lb-total">0 R<', sec)
        self.assertIn("Nog niets vandaag.", sec)

    def test_een_genomen_trade_met_uitkomst_en_replay(self):
        sid = self.signal()
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        jid = repo.create_journal_entry(sid, self.anna, 0)
        repo.update_journal_status(jid, self.anna, "genomen")
        sec = self.lb(self.client.get("/signalen").text)
        self.assertIn("BTC short genomen", sec)
        self.assertIn("BTC short gesloten", sec)
        self.assertIn(">+2,0 R<", sec)
        self.assertIn(f'href="/logboek/replay/{sid}"', sec)
        self.assertIn('class="lb-total pos">+2,0 R<', sec)

    def test_leerlingen_zien_elkaars_logboek_nooit(self):
        sid = self.signal()
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        jid = repo.create_journal_entry(sid, self.anna, 0)
        repo.update_journal_status(jid, self.anna, "genomen")
        repo.record_plan_skip(self.anna, "zone:1", "SOL", "long", db.now_iso())
        repo.open_checklist(self.anna, "zone:2", "ETH", "long", db.now_iso())
        repo.finish_checklist(self.anna, "zone:2", db.now_iso())
        repo.create_journal_entry(sid, self.bram, 0)                      # bram kreeg hetzelfde signaal, maar nam het niet
        self.login(self.bram)
        sec = self.lb(self.client.get("/signalen").text)
        for text in ("BTC short genomen", "SOL long overgeslagen", "ETH long order gezet", "+2,0 R"):
            self.assertNotIn(text, sec)
        self.login(self.anna)
        sec = self.lb(self.client.get("/signalen").text)
        for text in ("BTC short genomen", "SOL long overgeslagen", "ETH long order gezet"):
            self.assertIn(text, sec)

    def test_een_oefentrade_staat_er_nooit(self):
        sid = self.signal(is_practice=1)
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        jid = repo.create_journal_entry(sid, self.anna, 0)
        repo.update_journal_status(jid, self.anna, "genomen")
        sec = self.lb(self.client.get("/signalen").text)
        self.assertNotIn("BTC short", sec)

    def test_tabs_naar_de_signalenlijst_en_het_journaal(self):
        html = self.client.get("/signalen").text
        self.assertIn('class="ut-tab is-active" href="/signalen" aria-current="page">Dag<', html)
        self.assertIn('href="/signalen?weergave=open"', html)
        self.assertIn('href="/account#journaal"', html)
        self.assertIn('id="journaal"', self.client.get("/account").text)

    def test_de_signalenlijst_blijft_werken(self):
        sid = self.signal()
        repo.create_journal_entry(sid, self.anna, 0)
        html = self.client.get("/signalen?weergave=open").text
        self.assertIn('class="signal-card', html)
        self.assertNotIn('<section class="lb"', html)



class ReplayPageTests(Base):
    def setUp(self):
        super().setUp()
        import pandas as pd

        def ohlcv(coin, timeframe="5m", limit=200, since=None):
            self.calls.append((coin, timeframe, limit, since))
            start = since // 1000
            rows = [[(start + i * 300) * 1000, 100.0, 100.2, 99.8, 100.0, 1] for i in range(limit)]
            df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df
        self.calls = []
        main._replay_candles.clear()
        self.ohlcv = mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=ohlcv)
        self.ohlcv.start()

    def tearDown(self):
        self.ohlcv.stop()
        super().tearDown()

    def closed(self, outcome="take_profit", **kw):
        sid = self.signal(**kw)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = '2026-10-25T20:40:00+00:00' WHERE id = ?", (sid,))
        repo.mark_signal_auto_outcome(sid, outcome, "2026-10-25T21:40:00+00:00")
        return sid

    def test_replay_met_candles_niveaus_en_momenten(self):
        sid = self.closed()
        html = self.client.get(f"/logboek/replay/{sid}").text
        self.assertIn("BTC short", html)
        self.assertIn("Replay · 5 min", html)
        self.assertEqual(html.count('class="rp-candle'), 25)
        for label in ("Gevuld", "Doel geraakt", "Speel af"):
            self.assertIn(label, html)
        self.assertIn('class="rp-r" data-rp="r" aria-live="polite">+2,0 R<', html)
        self.assertIn('href="/signalen"', html)
        self.assertEqual(self.calls, [("BTC", "5m", 25, int(datetime_ms("2026-10-25T19:40:00+00:00")))])

    def test_de_candles_van_een_gesloten_venster_worden_een_keer_opgehaald(self):
        sid = self.closed()
        self.client.get(f"/logboek/replay/{sid}")
        self.client.get(f"/logboek/replay/{sid}")
        self.assertEqual(len(self.calls), 1)

    def test_eigen_checklist_wel_die_van_een_ander_niet(self):
        zid = repo.insert_zone_radar_setup({"coin": "BTC", "direction": "short", "tf": "1h", "zone_key": "k", "zone_low": 100.0, "zone_high": 100.5,
                                            "stop_loss": 101.0, "take_profit": 98.0, "rr": 2.0, "atr": 0.5, "target_tf": "4h", "target_low": 98.0,
                                            "target_high": 98.5}, "2026-10-25T18:00:00+00:00")
        sid = repo.fill_zone_radar_setup(zid, {"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": "zone_radar", "price": 100.0,
                                               "stop_loss": 101.0, "take_profit": 98.0, "confidence": "x", "technical_confirmed": 1, "hard_gates_ok": 1})
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = '2026-10-25T20:40:00+00:00' WHERE id = ?", (sid,))
        repo.mark_signal_auto_outcome(sid, "take_profit", "2026-10-25T21:40:00+00:00")
        repo.open_checklist(self.bram, f"zone:{zid}", "BTC", "short", "2026-10-25T20:30:00+00:00")
        repo.finish_checklist(self.bram, f"zone:{zid}", "2026-10-25T20:31:12+00:00")
        html = self.client.get(f"/logboek/replay/{sid}").text
        self.assertIn("Plan actief", html)
        self.assertNotIn("Order gezet", html)
        self.login(self.bram)
        self.assertIn("Order gezet", self.client.get(f"/logboek/replay/{sid}").text)

    def test_open_oefen_of_onbekend_geeft_404(self):
        self.assertEqual(self.client.get(f"/logboek/replay/{self.signal()}").status_code, 404)
        self.assertEqual(self.client.get(f"/logboek/replay/{self.closed(is_practice=1)}").status_code, 404)
        self.assertEqual(self.client.get(f"/logboek/replay/{self.closed(outcome='vervallen')}").status_code, 404)
        self.assertEqual(self.client.get("/logboek/replay/999").status_code, 404)

    def test_beurs_onbereikbaar_zegt_dat(self):
        sid = self.closed()
        self.ohlcv.stop()
        with mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=RuntimeError("weg")):
            html = self.client.get(f"/logboek/replay/{sid}").text
        self.ohlcv.start()
        self.assertIn("niet op te halen", html)


def datetime_ms(value):
    from datetime import datetime
    return datetime.fromisoformat(value).timestamp() * 1000


if __name__ == "__main__":
    unittest.main()
