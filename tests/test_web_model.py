"""Het HesPulse-model op Kansen: één tab "HesPulse" met de twee momenten op één kaart (scenario ontdekt zonder order, entry beschikbaar als
limietplan), voor iedereen; met MODEL_ONLY_ALERTS geen tab meer voor de andere soorten, behalve hun open trades onder Open. De kaartgrafiek
komt van /api/kaart_svg/model:N."""
import json
from unittest import mock

import pandas as pd

from app import config, db, repo
from tests.test_web_focus import Base, signal
from web import main

NOW = pd.Timestamp.now(tz="UTC")


def scenario(coin="SOL", status="wacht_sweep", entry=False, direction="long"):
    steps = {"steps": [{"stap": "ontdekt", "at": (NOW - pd.Timedelta(hours=3)).isoformat()}], "attempts": [], "range_at": (NOW - pd.Timedelta(days=1)).isoformat()}
    row = {"coin": coin, "direction": direction, "range_id": f"{direction}:{coin}:{status}", "status": status, "range_low": 95.0, "range_high": 110.0,
           "eq": 102.5, "pool_level": 98.0, "candidates": json.dumps([{"kind": "range", "label": "rand van de range", "price": 110.0}]),
           "steps": json.dumps(steps), "discovered_at": (NOW - pd.Timedelta(hours=3)).isoformat(), "detected_at": (NOW - pd.Timedelta(hours=3)).isoformat(),
           "updated_at": NOW.isoformat()}
    sid = repo.insert_model_scenario(row)
    if entry:
        steps["steps"] += [{"stap": "sweep", "at": (NOW - pd.Timedelta(hours=2)).isoformat(), "pool": 98.0, "extreme": 97.5,
                            "prik_at": (NOW - pd.Timedelta(hours=2, minutes=15)).isoformat(), "terug_at": (NOW - pd.Timedelta(hours=2, minutes=15)).isoformat()},
                           {"stap": "shift", "at": (NOW - pd.Timedelta(hours=1)).isoformat(), "top": 101.0, "top_at": (NOW - pd.Timedelta(hours=4)).isoformat(), "label": "CHOCH"},
                           {"stap": "entry", "at": (NOW - pd.Timedelta(minutes=50)).isoformat()}]
        fields = {"status": "afgerond", "steps": json.dumps(steps), "entry_at": (NOW - pd.Timedelta(minutes=50)).isoformat(), "limit_price": 99.5,
                  "stop_loss": 97.0, "take_profit": 110.0, "rr": 4.2, "zone_low": 99.0, "zone_high": 99.5, "target_kind": "range",
                  "target_text": "rand van de range", "ob_overlap": 0, "expires_at": (NOW + pd.Timedelta(hours=5)).isoformat(),
                  "price_at_publish": 100.0, "vulbaar": 1}
        repo.sync_model_scenario(sid, fields, entry_detected_at=(NOW - pd.Timedelta(minutes=45)).isoformat())
    return sid


class ModelTab(Base):
    only = True

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(config, "HESPULSE_MODEL_ENABLED", True), mock.patch.object(config, "MODEL_ONLY_ALERTS", self.only)):
            p.start()
            self.addCleanup(p.stop)
        self.sc = scenario()
        self.entry = scenario("ADA", entry=True)

    def html(self):
        return self.client.get("/smc").text

    def test_both_moments_on_the_model_tab(self):
        html = self.html()
        self.assertIn('id="tab-hespulse_model-tab"', html)
        self.assertIn(f'id="radar-model-{self.sc}"', html)
        self.assertIn(f'id="radar-model-{self.entry}"', html)
        self.assertIn("Wacht op sweep", html)                     # moment A: de stand
        self.assertIn("Wacht op een sweep van de pool onder de koers", html)
        self.assertIn("Nog geen order", html)
        self.assertIn(f'href="/nu/order/model:{self.entry}"', html)  # moment B: de order-checklist
        self.assertIn('data-kc-svg="/api/kaart_svg/model:', html)
        self.assertIn("Scenario ontdekt", html)

    def test_model_tab_opens_first(self):
        self.assertIn('class="ut-tab is-active" id="tab-hespulse_model-tab"', self.html())

    def test_everyone_sees_the_model(self):
        self.as_student()
        html = self.html()
        self.assertIn(f'id="radar-model-{self.entry}"', html)
        self.assertIn("ongetest", html)

    def test_only_the_model_tab_plus_open_trades_of_old_kinds(self):
        open_zone = signal("DOGE", "zone_radar", price=100.0, stop=99.0, take=103.0)
        html = self.html()
        self.assertNotIn('id="tab-structuur-tab"', html)
        self.assertNotIn('class="kc-title">BTC short<', html)        # de wachtende zone-radar-kaart staat er niet meer
        self.assertIn('id="tab-zone_radar-tab"', html)              # wel de tab met de open trade
        self.assertIn(f'id="radar-signal-{open_zone}"', html)

    def test_dock_counts_only_the_model(self):
        self.client.get("/smc")
        forming = main._forming_setups(None)
        self.assertEqual({f["source"] for f in forming}, {"hespulse_model"})


class ModelWithoutOnly(ModelTab):
    only = False

    def test_only_the_model_tab_plus_open_trades_of_old_kinds(self):
        html = self.html()
        self.assertIn('id="tab-zone_radar-tab"', html)
        self.assertIn('class="kc-title">BTC short<', html)
        self.assertIn('id="tab-hespulse_model-tab"', html)

    def test_dock_counts_only_the_model(self):
        self.assertIn("zone_radar", {f.get("source") for f in main._forming_setups(None)})

    def test_model_tab_opens_first(self):
        """Zonder MODEL_ONLY_ALERTS wint zoals altijd de tab met de meeste kansen in de zone (hier de zone-radar)."""
        self.assertIn('class="ut-tab is-active" id="tab-zone_radar-tab"', self.html())


class ModelChart(Base):
    def test_card_svg_for_both_moments(self):
        sc, en = scenario(), scenario("ADA", entry=True)
        start = int((NOW - pd.Timedelta(hours=30)).timestamp())
        rows = [[start + 900 * i, 100.0, 100.5, 99.5, 100.0] for i in range(120)]
        with mock.patch.object(main, "_cached_candles", mock.AsyncMock(return_value=rows)):
            a = self.client.get(f"/api/kaart_svg/model:{sc}")
            b = self.client.get(f"/api/kaart_svg/model:{en}")
            big = self.client.get(f"/api/kaart_svg/model:{en}?groot=1")
        self.assertEqual((a.status_code, b.status_code, big.status_code), (200, 200, 200))
        self.assertIn(">4u range high<", a.text)
        self.assertIn(">evenwicht<", a.text)
        self.assertIn(">1u swing low<", a.text)
        self.assertNotIn(">Limiet", a.text)
        self.assertIn(">Limiet", b.text)
        self.assertIn(">15m FVG<", b.text)
        self.assertIn(">15m CHoCH<", b.text)
        self.assertIn('viewBox="0 0 340 600"', big.text)            # "Groot" in dezelfde stijl
        self.assertIn('viewBox="0 0 316 236"', b.text)
        self.assertEqual(self.client.get("/api/kaart_svg/model:999").status_code, 404)


class ModelChecklist(ModelTab):
    def test_groot_opens_the_movable_chart_with_timeframe_choice(self):
        # CEO 2026-11-02: "je kan de tijdzone niet meer aanpassen en de grafiek kan niet meer bewegen". Groot is weer levelchart.js.
        html = self.html()
        self.assertNotIn("data-kc-big", html)
        self.assertGreaterEqual(html.count("data-lc-expand"), 2)                # scenario en entry
        self.assertIn('"label": "4u range"', html.replace("&#34;", '"'))
        self.assertIn('"label": "15m FVG"', html.replace("&#34;", '"'))

    def test_entry_has_the_order_checklist_and_a_scenario_has_none(self):
        self.assertEqual(self.client.get(f"/nu/order/model:{self.entry}").status_code, 200)
        self.assertEqual(self.client.get(f"/nu/order/model:{self.sc}").status_code, 404)


class ModelProof(ModelTab):
    def test_bewijs_shows_the_measurement_and_comparisons_only_for_the_ceo(self):
        with mock.patch.object(config, "CEO_USERNAME", "ceo"):
            main._ceo_cache.update(at=0.0)
            html = self.client.get("/bewijs").text
            self.assertIn("HesPulse-model, meting", html)
            self.assertIn("V1 vroege limiet op de pool", html)
            self.as_student()
            html = self.client.get("/bewijs").text
        self.assertIn("HesPulse-model, meting", html)
        self.assertNotIn("V1 vroege limiet op de pool", html)


class EntryPointsOnTheCard(ModelTab):
    """Aanvullend besluit CEO 2026-11-03: alle instappunten op één kaart; tik op een punt voor de basis. B0 staat er nooit."""

    def setUp(self):
        super().setUp()
        known = (NOW - pd.Timedelta(minutes=30)).isoformat()
        for code, limit in (("B", 100.5), ("B0", 100.7), ("P", 98.5)):
            repo.insert_model_entry(self.entry, {"code": code, "coin": "ADA", "direction": "long", "known_at": known, "detected_at": known,
                                                 "limit_price": limit, "stop_loss": 97.5, "take_profit": 110.0, "rr": 3.0,
                                                 "expires_at": (NOW + pd.Timedelta(hours=5)).isoformat(), "basis": "{}"})

    def test_detailblad_noemt_elk_punt_met_zijn_basis(self):
        html = self.html()
        self.assertIn("Instappunten", html)
        for name in ("Na sweep", "Lagere top", "POC-limiet"):
            self.assertIn(name, html)
        self.assertNotIn("B0", html)

    def test_grafiek_tekent_de_letters(self):
        start = int((NOW - pd.Timedelta(hours=30)).timestamp())
        rows = [[start + 900 * i, 100.0, 100.5, 99.5, 100.0] for i in range(120)]
        with mock.patch.object(main, "_cached_candles", mock.AsyncMock(return_value=rows)):
            svg = self.client.get(f"/api/kaart_svg/model:{self.entry}").text
        self.assertIn(">A Limiet", svg)
        self.assertIn(">B 100,50<", svg)
        self.assertIn(">P 98,50<", svg)
        self.assertNotIn(">B0 ", svg)
