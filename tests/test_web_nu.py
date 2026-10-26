"""Scherm Nu (/vandaag) en de order-checklist (/nu/order/<sleutel>): rust, één kaart in de zone, overslaan en de stappen bij de beurs."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from web import main


def zone(coin, direction, low, high, stop, take, key):
    return repo.insert_zone_radar_setup({"coin": coin, "direction": direction, "tf": "1h", "zone_key": key, "zone_low": low, "zone_high": high,
                                         "stop_loss": stop, "take_profit": take, "rr": 2.0, "atr": 0.5, "target_tf": "4h", "target_low": take,
                                         "target_high": take + 1}, db.now_iso())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "n.db"))
        self.patch.start()
        db.init_db()
        main._price_cache.clear()
        main._price_fetched_at.clear()
        self.client = TestClient(main.app)
        uid = repo.create_user("dirk", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def nu(self, html):
        return html[html.index('<section class="nu'):html.index("</section>", html.index('<section class="nu'))]


class NuPageTests(Base):
    def test_rust_zonder_plannen(self):
        html = self.client.get("/vandaag").text
        sec = self.nu(html)
        self.assertIn('data-nu-mode="rust"', sec)
        self.assertIn("Niets te doen.", sec)
        self.assertIn("Er staat geen plan in de zone. Je krijgt een melding als dat verandert.", sec)
        self.assertIn("Geen plan wacht op zijn zone.", sec)
        for label in ("Plannen", "Open trades", "Gekeken"):
            self.assertIn(label, sec)
        self.assertNotIn("Eerstvolgende</span>", sec)

    def test_rust_met_het_eerstvolgende_plan_en_een_gemeten_afstand(self):
        zone("BTC", "short", 102.0, 103.0, 104.0, 95.0, "1h:bear:a")         # limiet 102, koers 100: nog 1,96%
        zone("SOL", "long", 90.0, 91.0, 89.0, 110.0, "1h:bull:b")            # limiet 91: nog 9,89%
        sec = self.nu(self.client.get("/vandaag").text)
        self.assertIn("Eerstvolgende", sec)
        self.assertIn("BTC · Short", sec)
        self.assertIn(">1,96%<", sec)
        self.assertIn("102,00", sec)
        self.assertRegex(sec, r'class="nu-bar"[^>]*><i data-nu="bar" style="width: 34\.\d%">')
        self.assertRegex(sec, r'Plannen</span><span class="nu-num">2</span>')
        self.assertRegex(sec, r'Gekeken</button>.*?</span></span><span class="nu-num" data-nu="seen">net</span>')

    def test_een_plan_in_de_zone_vult_het_scherm_met_de_checklistknop(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")    # koers 100 staat in de zone
        zone("ETH", "long", 99.0, 100.5, 98.0, 106.0, "1h:bull:b")           # ook in de zone, verder van zijn limiet
        sec = self.nu(self.client.get("/vandaag").text)
        self.assertIn('data-nu-mode="zone"', sec)
        self.assertIn(">In zone<", sec)
        self.assertIn('class="nu-coin">BTC<', sec)
        self.assertIn("De koers staat in de zone", sec)
        self.assertIn(f'href="/nu/order/zone:{zid}"', sec)
        self.assertIn("Zet de order, stap voor stap", sec)
        self.assertIn('<span class="kind-tag is-untested">ongetest</span>', sec)
        for label in ("Stop", "Instap", "Doel · 2,0 R"):
            self.assertIn(label, sec)
        ook = sec[sec.index("Sla over"):]
        self.assertIn("Ook in zone", ook)
        self.assertIn("ETH long", ook)
        self.assertLess(sec.index("Zet de order"), sec.index("Ook in zone"))

    def test_sla_over_onthoudt_het_plan_en_valt_terug_op_rust(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        r = self.client.post("/nu/overslaan", data={"key": f"zone:{zid}"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/vandaag"))
        self.assertIn(f"{main.NU_SKIP_COOKIE}=", r.headers["set-cookie"])
        sec = self.nu(self.client.get("/vandaag").text)
        self.assertIn('data-nu-mode="rust"', sec)
        self.assertIn("Je sloeg BTC short over.", sec)

    def test_ook_in_zone_wisselt_de_kaart(self):
        zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        eid = zone("ETH", "long", 99.0, 100.5, 98.0, 106.0, "1h:bull:b")
        sec = self.nu(self.client.get(f"/vandaag?plan=zone:{eid}").text)
        self.assertIn('class="nu-coin">ETH<', sec)

    def test_alleen_een_open_trade_toont_die_met_live_r(self):
        sid = repo.insert_signal({"coin": "BNB", "direction": "short", "category": "x", "confidence": "hoog", "technical_confirmed": 1, "hard_gates_ok": 1,
                                  "price": 101.0, "stop_loss": 103.0, "take_profit": 95.0, "trade_type": "zone_radar"})
        sec = self.nu(self.client.get("/vandaag").text)
        self.assertIn('data-nu-mode="trade"', sec)
        self.assertIn(">Open trade<", sec)
        self.assertIn("+0,50 R", sec)
        self.assertIn(f'href="/kans/{sid}"', sec)
        self.assertNotIn("Zet de order", sec)

    def test_de_markt_staat_eronder_en_niets_verdwijnt(self):
        html = self.client.get("/vandaag").text
        markt = html[html.index('id="markt"'):]
        for needle in ('data-utabs="vandaag"', 'id="tab-kansen"', 'id="tab-markt"', 'id="tab-agenda"', 'id="tab-score"', "Open kansen nu"):
            self.assertIn(needle, markt, needle)
        self.assertLess(html.index('<section class="nu'), html.index('id="markt"'))

    def test_de_kop_toont_het_merk_en_een_verborgen_titel(self):
        html = self.client.get("/vandaag").text
        kop = html[html.index('class="ph'):html.index('<section class="nu')]
        self.assertIn('class="ph ph-logo"', kop)
        self.assertIn('<h1 class="sr-only">Nu</h1>', kop)


class ChecklistPageTests(Base):
    def test_vier_stappen_met_kopieerknoppen_en_zonder_grootte(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        r = self.client.get(f"/nu/order/zone:{zid}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertNotIn('class="tabbar"', html)                         # volledig scherm, geen dok eronder
        self.assertIn("BTC short", html)
        self.assertEqual(html.count('<li class="ck-step'), 4)
        self.assertEqual(html.count('<i class="ck-seg'), 4)
        for title in ("Open BTC bij je beurs", "Limietprijs", "Stop", "Doel"):
            self.assertIn(title, html)
        self.assertIn('data-ck-copy="100.00"', html)
        self.assertIn('data-ck-copy="102.00"', html)
        self.assertIn('data-ck-copy="96.0000"', html)
        self.assertNotIn("Grootte", html)
        self.assertNotIn("€", html[html.index('class="ck"'):])
        self.assertIn("nog in zone", html)
        self.assertIn("Order staat. Volg hem op Nu", html)
        self.assertIn('href="/vandaag"', html)
        self.assertIn("Terug", html)
        self.assertIn("Sluit", html)

    def test_meerdere_doelen_geven_een_keuze_voor_een_setup(self):
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 99.0, "risk_pct": 1.0, "targets": [102.0, 103.0], "targets_r": [2.0, 3.0], "candles": candles}
        sid = repo.insert_structure_setup({
            "coin": "SOL", "direction": "long", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "B", "reason": "x", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        html = self.client.get(f"/nu/order/structuur:{sid}").text
        self.assertIn("Doel 1 · 2,0 R", html)
        self.assertIn("Doel 2 · 3,0 R", html)
        self.assertIn('data-ck-choice="103.00"', html)
        self.assertIn('data-ck-copy="102.00"', html)
        self.assertIn(f'href="/nu/order/structuur:{sid}"', self.client.get("/structuur").text)

    def test_onbekend_of_vervallen_plan_geeft_404(self):
        self.assertEqual(self.client.get("/nu/order/zone:999").status_code, 404)
        self.assertEqual(self.client.get("/nu/order/iets").status_code, 404)
        zid = zone("BTC", "long", 101.0, 102.0, 100.5, 110.0, "1h:bull:z")    # koers 100 onder de stop: vervallen
        self.assertEqual(self.client.get(f"/nu/order/zone:{zid}").status_code, 404)

    def test_script_kopieert_met_terugval_en_in_try_catch(self):
        src = (main.BASE_DIR / "static" / "order.js").read_text(encoding="utf-8")
        self.assertIn("navigator.clipboard", src)
        self.assertIn('execCommand("copy")', src)
        self.assertIn("try", src)
        self.assertIn("selectNodeContents", src)                          # laatste terugval: het getal geselecteerd laten staan


if __name__ == "__main__":
    unittest.main()
