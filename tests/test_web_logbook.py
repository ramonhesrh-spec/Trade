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


if __name__ == "__main__":
    unittest.main()
