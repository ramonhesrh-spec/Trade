"""De POC-radar in de app: een eigen tab 'POC-radar' op Kansen met kaarten onder de sleutel poc:N, de kaartgrafiek via /api/kaart_svg/poc:N,
de kanspagina, een eigen rij op Bewijs, het Logboek, de order-checklist, en CEO-only zolang POC_RADAR_PUBLIC uit staat. Overal 'ongetest'."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, focus, kansen, nu, repo, rule_live, security, today, track_record

NOW = datetime.now(timezone.utc)
DAY = (NOW - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)


def card_row(**kw):
    row = {"coin": "XRP", "direction": "long", "period": "day", "period_start": DAY.isoformat(), "level_key": f"day:{DAY.isoformat()}",
           "level": 100.3, "limit_price": 100.3, "stop_loss": 99.8, "take_profit": 104.0, "rr": 7.4, "atr": 2.0, "target_kind": "poc",
           "target_text": "dag-POC 1 okt", "target_tf": None, "target_low": None, "target_high": None,
           "expires_at": (NOW + timedelta(days=2)).isoformat()}
    row.update(kw)
    return row


class WebPocRadarTests(unittest.TestCase):
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
        self.price = {"XRP": 101.0}
        p = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: self.price.get(coin, 1.0))
        p.start()
        self.addCleanup(p.stop)

    def login(self, uid):
        self.client.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(uid))

    def add_card(self, **kw):
        return repo.insert_poc_radar_setup(card_row(**kw), (NOW - timedelta(minutes=45)).isoformat())

    def fill(self, setup_id, take=104.0):
        from app import poc_radar as pr
        row = {**card_row(take_profit=take), "id": setup_id}
        measure = None if take is not None else {"entry": 100.3, "stop": 99.8, "filled_at": NOW.isoformat(), "checked_until": NOW.isoformat()}
        return repo.fill_poc_radar_setup(setup_id, pr.signal_row(row, 100.3), [self.ceo, self.student], measure)

    def test_eigen_tab_met_de_kaart_en_lazy_grafiek(self):
        sid = self.add_card()
        text = self.client.get("/smc").text
        self.assertIn('id="tab-poc_radar-tab"', text)
        panel = text.split('<section id="tab-poc_radar"')[1].split("</section>\n")[0]
        self.assertIn(f'id="radar-poc-{sid}"', panel)
        self.assertIn(f"/api/kaart_svg/poc:{sid}", panel)
        self.assertIn("POC-radar", text.split('id="tab-poc_radar-tab"')[1][:200])
        sheet = text.split(f'data-kd-item="poc:{sid}"')[1].split("</section>")[0]
        self.assertIn(">POC-radar<", sheet)
        self.assertIn('data-hold-copy="100.30"', sheet)
        self.assertIn("Naakte dag-POC", sheet)
        self.assertIn(f"/nu/order/poc:{sid}", text)
        self.assertEqual(self.client.get(f"/nu/order/poc:{sid}").status_code, 200)

    def test_kaart_svg(self):
        sid = self.add_card()
        t0 = int((DAY - timedelta(days=1)).timestamp())
        rows = [[t0 + i * 3600, 101.0, 101.5, 100.5, 101.2] for i in range(80)]
        with mock.patch.object(self.main, "_cached_candles", mock.AsyncMock(return_value=rows)) as cached:
            r = self.client.get(f"/api/kaart_svg/poc:{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Limiet op POC 100,30", r.text)
        self.assertEqual(cached.call_args.args[1], "1h")
        self.assertEqual(self.client.get("/api/kaart_svg/poc:999").status_code, 404)

    def test_leerling_ziet_niets_als_hij_niet_openbaar_is(self):
        sid = self.add_card()
        signal_id = self.fill(self.add_card(coin="ADA", level_key="day:2026-01-01T00:00:00+00:00"))
        with mock.patch.object(rule_live, "CEO_ONLY_TYPES", rule_live.ceo_only_types(True, True, False)):
            self.login(self.student)
            self.assertNotIn(f"radar-poc-{sid}", self.client.get("/smc").text)
            self.assertEqual(self.client.get(f"/kans/{signal_id}").status_code, 404)
            self.assertEqual(self.client.get(f"/api/kaart_svg/poc:{sid}").status_code, 404)
            self.login(self.ceo)
            self.assertIn(f"radar-poc-{sid}", self.client.get("/smc").text)

    def test_kanspagina_ongetest_en_zonder_doel_de_referentie(self):
        signal_id = self.fill(self.add_card(take_profit=None, rr=None, target_kind=None, target_text=None), take=None)
        repo.set_trade_result(signal_id, -1.0, NOW.isoformat())
        repo.mark_signal_auto_outcome(signal_id, "stop_loss", NOW.isoformat())
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen beurs")):
            text = self.client.get(f"/kans/{signal_id}").text
        self.assertIn('<span class="kind-tag">POC-radar</span>', text)
        self.assertIn("kind-tag is-untested", text)
        self.assertIn("Referentie-uitgang", text)

    def test_bewijs_heeft_een_eigen_rij(self):
        signal_id = self.fill(self.add_card())
        repo.mark_signal_auto_outcome(signal_id, "stop_loss", NOW.isoformat())
        text = self.client.get("/bewijs").text
        self.assertIn("POC-radar (ongetest)", text)
        self.assertNotIn("Bewezen", text.split("POC-radar (ongetest)")[1][:400])

    def test_logboek_kent_de_poc_radar(self):
        sid = self.add_card()
        signal_id = self.fill(sid)
        self.assertEqual(repo.plans_for_keys([f"poc:{sid}"])[f"poc:{sid}"]["signal_id"], signal_id)
        self.assertEqual(repo.plan_for_signal(signal_id)["key"], f"poc:{sid}")
        since = (NOW - timedelta(days=1)).isoformat()
        self.assertEqual(len(repo.list_plan_moments(since)), 1)
        self.assertEqual(repo.list_plan_moments(since, include_poc=False), [])

    def test_namen_en_sleutels(self):
        self.assertEqual(today.SIGNAL_LABELS["poc_radar"], "POC-radar gevuld")
        self.assertEqual(track_record.TYPE_LABELS["poc_radar"], "POC-radar (ongetest)")
        self.assertEqual(kansen.LABELS["poc_radar"], "POC-radar")
        self.assertIn("poc_radar", kansen.ORDER)
        self.assertIn("poc_radar", nu.UNTESTED_SOURCES)
        self.assertEqual(nu.parse_skip("poc:3,zone:4"), frozenset({"poc:3", "zone:4"}))
        self.assertIn("poc_radar", focus.FOCUS_TYPES)


if __name__ == "__main__":
    unittest.main()
