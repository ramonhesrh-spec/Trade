"""Verbergen op Kansen (tabel kans_hidden): per gebruiker een weergavekeuze. De kaart verdwijnt uit de lijst en uit elke teller van die gebruiker
(tabs, totaal, dok, appicoon), staat onderaan zijn tab onder 'Verborgen (N)' en komt terug met Toon weer. Het signaal zelf, de uitkomst, Bewijs
en het overslaan veranderen niet; een andere gebruiker ziet de kaart gewoon."""
from unittest import mock

from app import db, repo, security
from tests.test_web_focus import Base
from web import main


def section(html, key):
    return html.split(f'<section id="tab-{key}"')[1].split("</section>")[0]


def listed(html, key, group):
    """De kaarten die in de lijst van een tab staan (niet de verborgen voorraad eronder)."""
    part = section(html, key).split(f"data-kt-{group}")[1].split("</div>")[0]
    return part


class HideTests(Base):
    def setUp(self):
        super().setUp()
        self.zone_key = "zone:" + str(repo.list_zone_radar_setups()[0]["id"])
        self.zone_dom = "radar-" + self.zone_key.replace(":", "-")

    def hide(self, *keys):
        return self.client.post("/api/kans/verberg", json={"keys": list(keys)})

    def test_verbergen_haalt_de_kaart_uit_de_lijst_en_zet_hem_onder_verborgen(self):
        self.assertIn(f'id="{self.zone_dom}"', listed(self.client.get("/smc").text, "zone_radar", "plans"))
        r = self.hide(self.zone_key)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["hidden"], [self.zone_key])
        html = self.client.get("/smc").text
        self.assertNotIn(f'id="{self.zone_dom}"', listed(html, "zone_radar", "plans"))
        tab = section(html, "zone_radar")
        self.assertIn("Verborgen (1)", tab)
        self.assertIn("Toon weer", tab)
        self.assertIn("Toon alles weer", tab)

    def test_tellers_tellen_de_verborgen_kans_niet(self):
        self.client.get("/smc")                                           # vult de koerscache die de tellers lezen
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 1)
        self.hide(self.zone_key)
        html = self.client.get("/smc").text
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 0)
        self.assertNotIn('class="tab-badge"', html)                      # dok
        tabs = html.split('class="ut-list"')[1].split("</div>")[0]
        self.assertRegex(tabs, r'Zone-radar<span class="ut-num"[^>]*>0</span>')
        self.assertNotIn("in de zone", html.split("data-kansen-total")[1].split("</p>")[0])

    def test_ongedaan_maken_zet_hem_terug(self):
        self.hide(self.zone_key)
        r = self.client.post("/api/kans/toon", json={"keys": [self.zone_key]})
        self.assertEqual(r.status_code, 200)
        html = self.client.get("/smc").text
        self.assertIn(f'id="{self.zone_dom}"', listed(html, "zone_radar", "plans"))
        self.assertNotIn("Verborgen (", section(html, "zone_radar"))

    def test_open_trade_verbergen_raakt_het_signaal_niet(self):
        key = f"signal:{self.smc_open}"
        self.hide(key)
        html = self.client.get("/smc").text
        self.assertNotIn(f'id="radar-signal-{self.smc_open}"', listed(html, "smc", "trades"))
        self.assertIn("Verborgen (1)", section(html, "smc"))
        self.assertIn(self.smc_open, [s["id"] for s in repo.list_open_smc_signals(types=("smc",))])   # nog steeds gevolgd
        self.assertEqual(repo.list_plan_skips(self.ceo_id), [])                                         # verbergen is geen overslaan

    def test_een_leerling_ziet_de_kaart_nog(self):
        self.hide(self.zone_key)
        self.client.get("/smc")
        self.as_student()
        html = self.client.get("/smc").text
        self.assertIn(f'id="{self.zone_dom}"', listed(html, "zone_radar", "plans"))
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 1)

    def test_een_leerling_kan_niets_van_een_ander_terugzetten(self):
        self.hide(self.zone_key)
        self.as_student()
        self.client.post("/api/kans/toon", json={"keys": [self.zone_key]})
        self.assertEqual(repo.list_hidden_kansen(self.ceo_id), {self.zone_key})

    def test_alles_verbergen_in_een_keer(self):
        r = self.hide(self.zone_key, f"signal:{self.smc_open}")
        self.assertEqual(sorted(r.json()["hidden"]), sorted([self.zone_key, f"signal:{self.smc_open}"]))
        self.assertEqual(repo.list_hidden_kansen(self.ceo_id), {self.zone_key, f"signal:{self.smc_open}"})
        self.assertIn(">Geen kansen<", self.client.get("/smc").text)

    def test_twee_keer_verbergen_is_een_rij(self):
        self.hide(self.zone_key)
        self.hide(self.zone_key)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM kans_hidden").fetchone()["n"], 1)

    def test_ongeldige_sleutels(self):
        self.assertEqual(self.hide("bla", "zone:x").status_code, 400)
        self.assertEqual(self.client.post("/api/kans/verberg", content=b"geen json", headers={"content-type": "application/json"}).status_code, 400)
        self.assertEqual(repo.list_hidden_kansen(self.ceo_id), set())

    def test_zonder_inlog_niets(self):
        self.client.cookies.clear()
        r = self.client.post("/api/kans/verberg", json={"keys": [self.zone_key]}, follow_redirects=False)
        self.assertIn(r.status_code, (303, 401))
        self.assertEqual(repo.list_hidden_kansen(self.ceo_id), set())

    def test_formulier_zonder_javascript(self):
        r = self.client.post("/api/kans/verberg", data={"key": self.zone_key}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(repo.list_hidden_kansen(self.ceo_id), {self.zone_key})

    def test_kaart_en_blad_bieden_verberg_en_overslaan(self):
        html = self.client.get("/smc").text
        card = html.split(f'id="{self.zone_dom}"')[1].split("</article>")[0]
        self.assertIn('data-kc-hide', card)
        self.assertIn('aria-label="Verberg BTC short"', card)
        detail = html.split(f'data-kd-item="{self.zone_key}"')[1].split("</section>")[0]
        self.assertIn(">Sla over voor vandaag<", detail)
        self.assertIn(">Verberg<", detail)
        trade = html.split(f'data-kd-item="signal:{self.smc_open}"')[1].split("</section>")[0]
        self.assertIn(">Verberg<", trade)
        self.assertNotIn("Sla over", trade)

    def test_dok_in_het_menu_volgt_de_kijker(self):
        self.client.get("/smc")
        self.hide(self.zone_key)
        req = mock.Mock(cookies={main.SESSION_COOKIE: security.create_session_token(self.ceo_id)})
        self.assertEqual(main._nav_context(req)["nav_counts"]["in_zone"], 0)
        self.assertEqual(main._nav_context(mock.Mock(cookies={}))["nav_counts"]["in_zone"], 1)


class ShareButtonTests(Base):
    def test_elk_detailblad_heeft_een_deelknop_met_de_getallen(self):
        html = self.client.get("/smc").text
        self.assertIn('data-share-for="zone:', html)
        self.assertIn('class="kd-skip kd-share"', html)
        self.assertRegex(html, r'data-share-card=\'\{[^\']*"plain": ?true')
        self.assertRegex(html, r'data-share-card=\'\{[^\']*(Stop|Instap)')
