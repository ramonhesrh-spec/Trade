"""Kansen (/smc) met het detailblad en de order-checklist (/nu/order/<sleutel>): kaarten per soort, overslaan en de stappen bij de beurs."""
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

    def tab(self, html, key):
        start = html.index(f'<section id="tab-{key}"')
        return html[start:html.index("\n</section>", start)]

    def sheet(self, html, key):
        start = html.index(f'data-kd-item="{key}"')
        return html[start:html.index("</section>", start)]


class KansenPageTests(Base):
    """V4: een tab per soort met kaarten (coin en richting, stand, grafiek); een tik opent het detailblad met ladder en getallen."""
    def test_een_tab_per_soort_met_telling(self):
        html = self.client.get("/smc").text
        for key, label in (("structuur", "Structuur"), ("zone_radar", "Zone-radar"), ("zone_sweep", "Zone-sweep")):
            self.assertIn(f'href="#tab-{key}"', html)
            self.assertIn(f'id="tab-{key}"', html)
        self.assertIn("Geen kansen", self.tab(html, "structuur"))
        self.assertIn(">Kansen<", html)

    def test_een_kaart_is_coin_richting_stand_en_grafiek(self):
        zid = zone("BTC", "short", 102.0, 103.0, 104.0, 95.0, "1h:bear:a")
        sec = self.tab(self.client.get("/smc").text, "zone_radar")
        card = sec[sec.index(f'id="radar-zone-{zid}"'):sec.index("</article>")]
        self.assertIn('class="kc-title">BTC short<', card)
        self.assertIn(">Wacht<", card)
        self.assertIn('class="pill is-untested">ongetest<', card)
        self.assertIn('data-kc-svg="/api/kaart_svg/zone:', card)          # de eigen zonetekening, lazy geladen
        self.assertIn("1 kans klaar<", sec)
        for gone in ("coin-av", "24u", "level-copy", "data-copy=", "Nog ", "approach", "Volume"):
            self.assertNotIn(gone, card, gone)

    def test_in_de_zone_eerst_en_die_tab_gaat_open(self):
        far = zone("SOL", "long", 90.0, 91.0, 89.0, 110.0, "1h:bull:b")
        near = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")     # koers 100 staat in de zone
        html = self.client.get("/smc").text
        self.assertIn('class="ut-tab is-active" id="tab-zone_radar-tab"', html)
        self.assertRegex(html, r'href="#tab-zone_radar"[^>]*>Zone-radar<span class="ut-num" data-ut-num>2</span><i class="ut-badge" data-ut-badge>1<')
        sec = self.tab(html, "zone_radar")
        self.assertLess(sec.index(f'id="radar-zone-{near}"'), sec.index(f'id="radar-zone-{far}"'))

    def test_detailblad_met_ladder_getallen_een_keer_en_de_knop(self):
        zid = zone("BTC", "short", 102.0, 103.0, 104.0, 95.0, "1h:bear:a")
        html = self.client.get("/smc").text
        sheet = self.sheet(html, f"zone:{zid}")
        self.assertIn('data-ladder="plan"', sheet)
        for tag in (">Stop<", ">Instap<", ">Doel<"):
            self.assertIn(tag, sheet)
        for copy in ("104.00", "102.00", "95.00"):
            self.assertEqual(sheet.count(f'data-hold-copy="{copy}"'), 1)
        self.assertEqual(sheet.count(">102,00<"), 1)                         # het getal staat één keer: in de tabel, niet op de ladder
        self.assertIn("Houd een getal vast", sheet)
        self.assertIn("Aanbodzone 1u", sheet)
        self.assertIn(">1,96%<", sheet)                                        # gemeten afstand tot de instap
        self.assertIn(f'href="/nu/order/zone:{zid}"', sheet)
        self.assertIn("Zet de order, stap voor stap", sheet)
        self.assertNotIn("102,00", sheet[sheet.index("kd-say"):sheet.index("data-ladder")])     # de zin herhaalt geen getallen

    def test_open_trade_onder_open_met_live_r_en_zonder_actiezin(self):
        sid = repo.insert_signal({"coin": "BNB", "direction": "short", "category": "x", "confidence": "hoog", "technical_confirmed": 1, "hard_gates_ok": 1,
                                  "price": 101.0, "stop_loss": 103.0, "take_profit": 95.0, "trade_type": "zone_radar"})
        html = self.client.get("/smc").text
        sec = self.tab(html, "zone_radar")
        self.assertLess(sec.index(">Open</h3>"), sec.index(f'id="radar-signal-{sid}"'))
        sheet = self.sheet(html, f"signal:{sid}")
        self.assertIn('data-ladder="trade"', sheet)
        self.assertIn("+0,50 R", sheet)
        self.assertNotIn("Trade loopt", sheet)
        self.assertNotIn("kd-say", sheet)
        self.assertIn(f'href="/kans/{sid}"', sheet)
        self.assertNotIn("Zet de order", sheet)

    def test_scripts_voor_blad_en_ladder(self):
        html = self.client.get("/smc").text
        for js in ("ladder.js", "kaarten.js", "levelchart.js", "radar.js"):
            self.assertIn(js, html)

    def test_sla_over_blijft_op_kansen_staan_maar_gemarkeerd(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        r = self.client.post("/nu/overslaan", data={"key": f"zone:{zid}"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/smc"))
        self.assertIn(f"{main.NU_SKIP_COOKIE}=", r.headers["set-cookie"])
        sec = self.tab(self.client.get("/smc").text, "zone_radar")
        self.assertIn('class="kc-skipped">overgeslagen<', sec)

    def test_oude_structuurpagina_stuurt_door_naar_de_tab(self):
        r = self.client.get("/structuur", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/smc?tab=structuur")         # zonder hash: het anker van de melding blijft staan
        html = self.client.get("/smc?tab=structuur").text
        self.assertIn('class="ut-tab is-active" id="tab-structuur-tab"', html)


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
        self.assertIn('data-ck-copy="96.00"', html)
        self.assertNotIn("Grootte", html)
        self.assertNotIn("€", html[html.index('class="ck"'):])
        self.assertIn("nog in zone", html)
        self.assertIn("Order staat. Terug naar Kansen", html)
        self.assertIn('href="/smc"', html)
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
        self.assertIn(f'href="/nu/order/structuur:{sid}"', self.client.get("/smc").text)

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


class PlanLogWebTests(Base):
    """R1 en R2: overslaan en de checklist komen per gebruiker in de database, naast de cookie."""
    def uid(self):
        return repo.get_user_by_username("dirk")["id"]

    def test_overslaan_schrijft_een_rij_met_coin_en_richting(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        self.client.post("/nu/overslaan", data={"key": f"zone:{zid}"}, follow_redirects=False)
        rows = repo.list_plan_skips(self.uid())
        self.assertEqual([(r["plan_key"], r["coin"], r["direction"]) for r in rows], [(f"zone:{zid}", "BTC", "short")])

    def test_een_onbekende_sleutel_wordt_niet_bewaard(self):
        self.client.post("/nu/overslaan", data={"key": "iets"}, follow_redirects=False)
        self.assertEqual(repo.list_plan_skips(self.uid()), [])

    def test_overgeslagen_op_een_ander_toestel_telt_ook_hier(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        repo.record_plan_skip(self.uid(), f"zone:{zid}", "BTC", "short", db.now_iso())
        sec = self.tab(self.client.get("/smc").text, "zone_radar")          # geen cookie op dit toestel
        self.assertIn('class="kc-skipped">overgeslagen<', sec)

    def test_de_checklist_bewaart_openen_en_afronden(self):
        zid = zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")
        html = self.client.get(f"/nu/order/zone:{zid}").text
        self.assertIn(f'data-ck-done-url="/nu/order/zone:{zid}/klaar"', html)
        run = repo.list_checklist_runs(self.uid())[0]
        self.assertEqual((run["plan_key"], run["coin"], run["direction"], run["done_at"]), (f"zone:{zid}", "BTC", "short", None))
        r = self.client.post(f"/nu/order/zone:{zid}/klaar")
        self.assertEqual(r.json(), {"ok": True})
        self.assertIsNotNone(repo.list_checklist_runs(self.uid())[0]["done_at"])
        self.assertEqual(self.client.post(f"/nu/order/zone:{zid}/klaar").json(), {"ok": False})

    def test_afronden_met_een_onbekende_sleutel_geeft_404(self):
        self.assertEqual(self.client.post("/nu/order/iets/klaar").status_code, 404)

    def test_het_script_meldt_het_afronden_een_keer(self):
        src = (main.BASE_DIR / "static" / "order.js").read_text(encoding="utf-8")
        self.assertIn("data-ck-done-url", src)
        self.assertIn("keepalive", src)


if __name__ == "__main__":
    unittest.main()
