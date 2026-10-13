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

    def test_login_blijft_zonder_schil(self):
        html = TestClient(main.app).get("/login").text
        self.assertNotIn("fsearch", html)
        self.assertNotIn("top-glow", html)
