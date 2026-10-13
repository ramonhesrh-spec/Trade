import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from web import main


def render(src: str, **ctx) -> str:
    env = main.templates.env
    return env.from_string('{% import "_macros.html" as m %}' + src).render(**ctx)


class LayoutMacroTests(unittest.TestCase):
    def test_headline_toont_getal_eenheid_en_toon(self):
        html = render('{{ m.headline("Resultaat", "+1,20", "R", delta="+0,40R vandaag", tone="pos") }}')
        self.assertIn('class="hl-num"', html)
        self.assertIn('>+1,20</span><span class="hl-unit">R</span>', html)
        self.assertIn('class="hl-delta pos"', html)

    def test_headline_zet_attributen_op_het_getal(self):
        html = render('{{ m.headline("Koers", "1", attrs={"id": "coin-price", "data-symbol": "BTC"}) }}')
        self.assertIn('id="coin-price"', html)
        self.assertIn('data-symbol="BTC"', html)

    def test_keylines_uitleg_via_popover(self):
        html = render('{{ m.keylines([{"label": "Winrate", "value": "52", "unit": "%", "explain": "Alleen doel en stop."}], "bw") }}')
        self.assertIn('popovertarget="bw-1"', html)
        self.assertIn('id="bw-1" popover', html)
        self.assertIn('class="kl-term"', html)

    def test_utabs_paneeltab_heeft_aria_controls(self):
        html = render('{{ m.utabs([{"key": "a", "label": "Kansen", "href": "#tab-a"}, {"key": "b", "label": "Markt", "href": "/x"}], "a") }}')
        self.assertIn('aria-controls="tab-a"', html)
        self.assertIn('class="ut-tab is-active"', html)
        self.assertEqual(html.count("aria-controls"), 1)

    def test_market_row_live_hooks(self):
        html = render('{{ m.market_row("BTC", "BTC", chip="long", chip_tone="pos", price_coin="BTC", chg_coin="BTC", el="summary") }}')
        self.assertTrue(html.strip().startswith('<summary class="mrow"'))
        self.assertIn('data-vd-price="BTC"', html)
        self.assertIn('data-spark-chg="BTC" data-spark-short', html)

    def test_geen_em_dash_in_nieuwe_macros(self):
        src = (main.BASE_DIR / "templates" / "_macros.html").read_text()
        new = src.split("===== Indeling", 1)[1]
        self.assertNotIn("—", new)
        self.assertNotIn("–", new)


class BaseShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        db.init_db()
        main._price_cache.clear()
        self.client = TestClient(main.app)
        user_id = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(user_id))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_vandaag_heeft_de_schil(self):
        html = self.client.get("/vandaag").text
        for needle in ['class="top-glow"', 'id="fsearch"', 'class="dock"', 'class="tabbar"', 'id="push-pause"', 'id="price-dot"',
                       'id="system-status"', 'id="cmdk"', 'id="more-sheet"', 'id="push-banner"', ">SMC</a>", ">Bewijs</a>",
                       "data-more-toggle"]:
            self.assertIn(needle, html, needle)

    def test_pagina_met_page_title_krijgt_ph_en_geen_topbar_flow(self):
        from fastapi import Depends
        from fastapi.responses import HTMLResponse

        tpl = main.templates.env.from_string('{% extends "base.html" %}{% block page_title %}Proef{% endblock %}{% block content %}x{% endblock %}')

        def proef(request: main.Request, user: dict = Depends(main.require_login)):
            return HTMLResponse(tpl.render(request=request, user=user, **main._nav_context(request)))

        main.app.add_api_route("/__proef_ph", proef)
        try:
            html = self.client.get("/__proef_ph").text
        finally:
            main.app.router.routes.pop()
        self.assertIn('class="ph"', html)
        self.assertIn('class="topbar"', html)
        self.assertNotIn("topbar-flow", html)

    def test_meer_blad_bevat_het_uitlogformulier(self):
        html = self.client.get("/vandaag").text
        sheet = html[html.index('id="more-sheet"'):]
        sheet = sheet[:sheet.index("<footer")]
        self.assertIn('<form action="/logout" method="post" class="more-logout">', sheet)
        self.assertIn("Uitloggen", sheet)

    def test_zoekveld_alleen_op_vandaag_en_radar(self):
        for pad in ("/vandaag", "/smc"):
            html = self.client.get(pad).text
            self.assertIn('id="fsearch"', html, pad)
            self.assertIn('<body class="has-fsearch">', html, pad)
        for pad in ("/bewijs", "/structuur"):
            html = self.client.get(pad).text
            self.assertNotIn('id="fsearch"', html, pad)
            self.assertNotIn("has-fsearch", html, pad)
            self.assertIn('class="dock"', html, pad)
            self.assertIn('id="cmdk"', html, pad)

    def test_login_blijft_zonder_schil(self):
        html = TestClient(main.app).get("/login").text
        self.assertNotIn("fsearch", html)
        self.assertNotIn("top-glow", html)


class VandaagLayoutTests(BaseShellTests):
    def seed_resolved(self):
        with db.session() as conn:
            for outcome in ("take_profit", "stop_loss"):
                conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                                take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                                VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', ?, ?, ?)""", (outcome, db.now_iso(), db.now_iso()))

    def test_groot_getal_is_het_weekresultaat_van_de_weekpagina(self):
        self.seed_resolved()
        user = repo.get_user_by_username("tester")
        week = main.track_record.week_summary(main.report_rows(user), main.config.TRACK_RECORD_COST_PCT)
        html = self.client.get("/vandaag").text
        self.assertIn('class="hl-num">%+.1f</span>' % week["net_r"], html)
        self.assertIn("proof-spark", html[html.index('class="hl-spark"'):])
        self.assertIn("%+.1f" % week["net_r"], self.client.get("/week").text)

    def test_zonder_afgeronde_trades_staat_er_geen_verzonnen_delta(self):
        html = self.client.get("/vandaag").text
        self.assertIn("Nog niets afgerond", html)

    def test_tabs_en_panelen(self):
        from datetime import datetime, timedelta, timezone
        repo.insert_market_script("BTC", "BTC duiding.", "long", "m", [{"direction": "long", "trigger_type": "close_above", "trigger_level": 101.0,
                                  "entry": 100.8, "stop_loss": 99.8, "take_profit": 103.0, "reason": "Break."}], 1,
                                  (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        html = self.client.get("/vandaag").text
        for needle in ['data-utabs="vandaag"', 'data-utabs-panels="vandaag"', 'id="tab-kansen"', 'id="tab-markt"', 'id="tab-agenda"',
                       'id="tab-score"', 'class="mrow-wrap', "quick-actions", "data-spark-chg", 'data-vd-price="BTC"']:
            self.assertIn(needle, html, needle)
        self.assertNotIn('class="quick-action"', html)
