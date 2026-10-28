"""De zone-sweep in de app: een kaart op Plannen (Radar) met eigen sleutel, de kanspagina, een eigen rij op Bewijs, Nu, het Logboek, en
CEO-only zolang ZONE_SWEEP_PUBLIC uit staat. Overal 'ongetest'."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, rule_live, security, today

NOW = datetime.now(timezone.utc)


def card_row(**kw):
    row = {"coin": "XRP", "direction": "long", "variant": "ZS_1H", "stop_name": "wick_025", "tf": "1h",
           "zone_key": f"1h:bull:{(NOW - timedelta(hours=30)).replace(minute=0, second=0, microsecond=0).isoformat()}",
           "zone_low": 99.7, "zone_high": 100.3, "zone_at": (NOW - timedelta(hours=30)).isoformat(), "sweep_at": (NOW - timedelta(hours=2)).isoformat(),
           "extreme": 99.2, "placed_at": (NOW - timedelta(minutes=50)).isoformat(), "expires_at": (NOW + timedelta(hours=23)).isoformat(),
           "ref_price": 100.6, "range_high": 104.6, "range_low": 99.2, "atr_t": 1.0, "limit_price": 100.3, "stop_loss": 98.95,
           "take_profit": 104.0, "rr": 2.74, "target_tf": "1h", "target_low": 104.0, "target_high": 104.6, "prik_atr": 0.5, "herstel_bars": 1}
    row.update(kw)
    return row


class WebZoneSweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for p in (mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db")), mock.patch.object(config, "CEO_USERNAME", "")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init_db()
        from web import main
        self.main = main
        main._price_cache.clear()
        main._ceo_cache.update(at=0.0, id=None)
        main._proof_cache.update(at=0.0)
        self.client = TestClient(main.app)
        self.ceo = repo.create_user("ceo", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.student = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.login(self.ceo)
        self.price = {"XRP": 101.0, "ADA": 0.5}
        p = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: self.price.get(coin, 1.0))
        p.start()
        self.addCleanup(p.stop)

    def login(self, uid):
        self.client.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(uid))

    def add_card(self, **kw):
        return repo.insert_zone_sweep_setup(card_row(**kw), (NOW - timedelta(minutes=45)).isoformat())

    def fill(self, setup_id, take=104.0):
        from app import zone_sweep as zsw
        row = {**card_row(take_profit=take), "id": setup_id}
        measure = None if take is not None else {"entry": 100.3, "stop": 98.95, "filled_at": NOW.isoformat(), "checked_until": NOW.isoformat()}
        return repo.fill_zone_sweep_setup(setup_id, zsw.signal_row(row, 100.3), [self.ceo, self.student], measure)

    def test_plannen_toont_de_kaart_met_eigen_sleutel(self):
        sid = self.add_card()
        text = self.client.get("/smc").text
        self.assertIn(f'id="radar-zsweep-{sid}"', text)
        card = text.split(f'id="radar-zsweep-{sid}"')[1].split("</article>")[0]
        self.assertIn('class="kc-title">XRP long<', card)
        self.assertIn("ongetest", card)
        self.assertIn("data-levelchart", card)
        self.assertIn(f'id="radar-zsweep-{sid}"', text.split('<section id="tab-zone_sweep"')[1].split("</section>\n")[0])
        sheet = text.split(f'data-kd-item="zsweep:{sid}"')[1].split("</section>")[0]
        self.assertIn('data-hold-copy="100.30"', sheet)                 # de limiet staat in de tabel van het blad
        self.assertIn(">Zone-sweep<", sheet)

    def test_kaart_zonder_doel(self):
        sid = self.add_card(take_profit=None, rr=None, target_tf=None, target_low=None, target_high=None)
        sheet = self.client.get("/smc").text.split(f'data-kd-item="zsweep:{sid}"')[1].split("</section>")[0]
        self.assertNotIn(">Doel<", sheet)                               # geen doel op de ladder en niet in de tabel
        self.assertNotIn("Doel ·", sheet)
        self.assertIn(">Stop<", sheet)

    def test_leerling_ziet_niets_als_hij_niet_openbaar_is(self):
        sid = self.add_card()
        signal_id = self.fill(self.add_card(coin="ADA", zone_key="1h:bull:2026-01-01T00:00:00+00:00"))
        with mock.patch.object(rule_live, "CEO_ONLY_TYPES", rule_live.ceo_only_types(True, False)):
            self.login(self.student)
            self.assertNotIn(f'radar-zsweep-{sid}', self.client.get("/smc").text)
            self.assertEqual(self.client.get(f"/kans/{signal_id}").status_code, 404)
            self.login(self.ceo)
            self.assertIn(f'radar-zsweep-{sid}', self.client.get("/smc").text)
            self.assertEqual(self.client.get(f"/kans/{signal_id}").status_code, 200)

    def test_kanspagina_met_doel(self):
        signal_id = self.fill(self.add_card())
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen beurs")):
            r = self.client.get(f"/kans/{signal_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<span class="kind-tag">Zone-sweep</span>', r.text)
        self.assertIn("kind-tag is-untested", r.text)
        self.assertIn("Doel", r.text)

    def test_kanspagina_zonder_doel_toont_de_referentie(self):
        signal_id = self.fill(self.add_card(take_profit=None, rr=None, target_tf=None, target_low=None, target_high=None), take=None)
        repo.set_trade_result(signal_id, 1.4, NOW.isoformat())
        repo.mark_signal_auto_outcome(signal_id, "take_profit", NOW.isoformat())
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen beurs")):
            text = self.client.get(f"/kans/{signal_id}").text
        self.assertIn("Referentie-uitgang", text)
        self.assertNotIn("Doel geraakt", text)

    def test_bewijs_heeft_een_eigen_rij(self):
        signal_id = self.fill(self.add_card())
        repo.mark_signal_auto_outcome(signal_id, "stop_loss", NOW.isoformat())
        text = self.client.get("/bewijs").text
        self.assertIn("Zone-sweep (ongetest)", text)
        self.assertNotIn("Bewezen", text.split("Zone-sweep (ongetest)")[1][:400])

    def test_na_de_labrun_status_volgens_de_stoptoets(self):
        repo.set_rule_lab("zone_sweep_stop", True, {"variant": "ZS_2H", "stop_name": "wick_025"}, db.now_iso())
        repo.set_rule_lab("zone_sweep", False, {"variant": "ZS_2H"}, db.now_iso())
        text = self.client.get("/bewijs").text
        rules = text.split("Status per regel")[1]
        card = rules.split("Zone-sweep (ongetest)")[1][:600]
        self.assertIn("In proef", card)
        self.assertNotIn("Negatief", card)
        self.assertNotIn("Zone-sweep 2u", rules.split("Andere geteste regels")[-1] if "Andere geteste regels" in rules else "")

    def test_kansen_toont_een_zone_sweep_in_de_zone(self):
        self.price["XRP"] = 100.1
        sid = self.add_card()
        text = self.client.get("/smc").text
        self.assertIn('class="ut-tab is-active" id="tab-zone_sweep-tab"', text)
        self.assertIn("· limietplan", text)
        self.assertIn(f"/nu/order/zsweep:{sid}", text)
        self.assertEqual(self.client.get(f"/nu/order/zsweep:{sid}").status_code, 200)

    def test_logboek_kent_de_zone_sweep(self):
        sid = self.add_card()
        signal_id = self.fill(sid)
        self.assertEqual(repo.plans_for_keys([f"zsweep:{sid}"])[f"zsweep:{sid}"]["signal_id"], signal_id)
        self.assertEqual(repo.plan_for_signal(signal_id)["key"], f"zsweep:{sid}")
        since = (NOW - timedelta(days=1)).isoformat()
        self.assertEqual(len(repo.list_plan_moments(since)), 1)
        self.assertEqual(repo.list_plan_moments(since, include_zone_sweep=False), [])

    def test_signaallabel(self):
        self.assertEqual(today.SIGNAL_LABELS["zone_sweep"], "Zone-sweep gevuld")


if __name__ == "__main__":
    unittest.main()
