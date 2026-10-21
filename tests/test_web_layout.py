import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from tests import range_seed
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

    def test_utabs_linktabs_zijn_geen_tabs(self):
        html = render('{{ m.utabs([{"key": "a", "label": "Week", "href": "/week"}, {"key": "b", "label": "Maand", "href": "/week?m=1"}], "a") }}')
        self.assertNotIn('role="tab"', html)
        self.assertNotIn("aria-selected", html)
        self.assertNotIn('role="tablist"', html)
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertRegex(html, r'class="ut-tab is-active" href="/week" aria-current="page"')

    def test_utabs_paneeltabs_zijn_echte_tabs_met_id(self):
        html = render('{{ m.utabs([{"key": "a", "label": "Kansen", "href": "#tab-a"}, {"key": "b", "label": "Markt", "href": "#tab-b"}], "a") }}')
        self.assertIn('role="tablist"', html)
        self.assertEqual(html.count('role="tab"'), 2)
        self.assertIn('id="tab-a-tab"', html)
        self.assertIn('aria-selected="true"', html)
        self.assertNotIn("aria-current", html)

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
        for needle in ['class="has-glow"', 'id="fsearch"', 'class="dock"', 'class="tabbar"', 'id="push-pause"', 'id="price-dot"',
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

    def test_kop_toont_het_woordmerk_op_elke_omgezette_pagina(self):
        for pad in ("/vandaag", "/smc", "/bewijs", "/structuur", "/coins/BTC"):
            html = self.client.get(pad).text
            kop = html[html.index('class="ph"'):]
            kop = kop[:kop.index('data-more-toggle')]
            self.assertIn('<span class="ph-brand">HesPulse</span>', kop, pad)

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

    def test_gloed_bovenaan_is_statisch_en_volbleed(self):
        css = open(os.path.join(os.path.dirname(main.__file__), "static", "style.css"), encoding="utf-8").read()
        for token in ("--glow-top-peak:", "--glow-top-mid:", "--glow-top-shoulder:"):
            self.assertIn(token, css)
        blok = css[css.index("html.has-glow {"):]
        blok = blok[:blok.index("}")]
        self.assertIn("--glow-top-peak", blok)
        self.assertIn("background-color: var(--bg)", blok)
        self.assertNotIn("animation", blok)
        self.assertIn("html.has-glow body { background: none; }", css)
        html = self.client.get("/vandaag").text
        self.assertIn("viewport-fit=cover", html)
        self.assertIn('content="black-translucent"', html)

    def test_grafiek_noemt_de_candlegrootte_en_de_tijdzone(self):
        import re
        html = main.templates.env.from_string('{% import "_macros.html" as m %}{{ m.level_chart("ETH", {"label": "x"}) }}{{ m.level_chart("ETH", {"label": "x"}, tf="1h") }}').render()
        self.assertEqual(re.findall(r'data-caption="([^"]+)"', html), ["Candles van 15 minuten · jouw tijd", "Candles van 1 uur · jouw tijd"])
        # Onder de grafiek: wat de vlakken betekenen en een knop (minstens 44px, zie style.css) die hem schermvullend opent.
        self.assertIn("Rood vlak: risico tot je stop", html)
        self.assertIn("Groen vlak: winst tot je doel", html)
        self.assertNotIn("Band: de zone", html)                              # geen zone in deze spec, dan ook geen uitleg ervan
        self.assertEqual(html.count("data-lc-expand"), 2)

    def test_zone_radar_uitleg_staat_op_een_eigen_pagina(self):
        r = self.client.get("/zone-radar")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ongetest", r.text)
        self.assertIn('href="/zone-radar"', self.client.get("/smc").text)

    def test_achtergrond_is_vlak_zonder_raster_of_zwevende_lagen(self):
        css = open(os.path.join(os.path.dirname(main.__file__), "static", "style.css"), encoding="utf-8").read()
        for pad in ("/vandaag", "/login"):
            html = TestClient(main.app).get(pad).text if pad == "/login" else self.client.get(pad).text
            for weg in ("page-ambient", "ambient-glow", "topbar-watermark", "signal-wave"):
                self.assertNotIn(weg, html, pad)
        self.assertNotIn("32px 32px", css)
        self.assertNotIn("ambient", css)
        self.assertNotIn("topbar-watermark", css)

    def test_randkleur_element_voor_statusbalk(self):
        html = self.client.get("/vandaag").text
        self.assertIn('class="glow-edge-tint"', html)
        self.assertIn('content="#0a0e0f"', html)
        css = open(os.path.join(os.path.dirname(main.__file__), "static", "style.css"), encoding="utf-8").read()
        blok = css[css.index(".glow-edge-tint {"):]
        blok = blok[:blok.index("}")]
        self.assertIn("background-color: var(--glow-edge)", blok)
        self.assertIn("position: fixed", blok)
        self.assertIn("-webkit-mask-image", blok)
        self.assertNotIn("radial", blok)
        self.assertIn("--glow-edge: #0c3a42;", css)
        self.assertNotIn("glow-edge-tint", TestClient(main.app).get("/login").text)

    def test_login_blijft_zonder_schil(self):
        html = TestClient(main.app).get("/login").text
        self.assertNotIn("fsearch", html)
        self.assertNotIn("has-glow", html)


class VandaagLayoutTests(BaseShellTests):
    def seed_resolved(self):
        with db.session() as conn:
            for outcome in ("take_profit", "stop_loss"):
                conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                                take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                                VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', ?, ?, ?)""", (outcome, db.now_iso(), db.now_iso()))

    def test_groot_getal_is_geen_weekresultaat_meer_en_weekpagina_blijft_bereikbaar(self):
        self.seed_resolved()
        html = self.client.get("/vandaag").text
        self.assertIn("Open kansen nu", html)
        self.assertNotIn("Laatste 7 dagen, na kosten", html)
        self.assertNotIn('class="hl-spark"', html)
        self.assertNotIn("R vandaag", html)
        self.assertIn('href="/week"', html)
        self.assertIn('href="/bewijs"', html)

    def test_lege_ondertitel_nodigt_uit_tot_wachten(self):
        html = self.client.get("/vandaag").text
        self.assertIn("Je krijgt een melding zodra er een staat.", html[html.index('class="hl"'):html.index('class="kl"')])

    def test_tabs_en_panelen(self):
        from datetime import datetime, timedelta, timezone
        repo.insert_market_script("BTC", "BTC duiding.", "long", "m", [{"direction": "long", "trigger_type": "close_above", "trigger_level": 101.0,
                                  "entry": 100.8, "stop_loss": 99.8, "take_profit": 103.0, "reason": "Break."}], 1,
                                  (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        html = self.client.get("/vandaag").text
        for needle in ['data-utabs="vandaag"', 'data-utabs-panels="vandaag"', 'id="tab-kansen"', 'id="tab-markt"', 'id="tab-agenda"',
                       'id="tab-score"', 'class="mrow-wrap', '<nav class="ut-menu">', ">Mijn week</a>", "data-spark-chg", 'data-vd-price="BTC"']:
            self.assertIn(needle, html, needle)
        self.assertNotIn('class="quick-action"', html)


    def test_coinlogo_met_letters_als_terugval(self):
        from datetime import datetime, timedelta, timezone
        for coin in ("BTC", "ZZQX"):
            repo.insert_market_script(coin, "x", "long", "m", [], 0, (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        html = self.client.get("/vandaag").text
        self.assertRegex(html, r'<span class="coin-av mrow-icon has-logo"[^>]*><img src="/static/coins/btc\.svg\?v=\d+" alt="" width="36" height="36" loading="lazy" decoding="async"')
        zz = html[html.index('<span class="coin-av mrow-icon"'):]
        self.assertTrue(zz.startswith('<span class="coin-av mrow-icon" style="--av: 36px" aria-hidden="true"><span class="coin-av-txt">ZZQX</span>'), zz[:200])
        self.assertNotIn("/static/coins/zzqx.svg", html)        # geen verzoek naar een bestand dat er niet is

    def test_elk_coinlogo_heeft_een_bron(self):
        bronnen = (main.BASE_DIR / "static" / "coins" / "SOURCES.md").read_text(encoding="utf-8")
        self.assertIn("btc", main.COIN_LOGOS)
        for sym in main.COIN_LOGOS:
            self.assertRegex(bronnen, r"[ ,]%s[,\s]" % sym, sym)
        self.assertLessEqual(main.DARK_COIN_LOGOS, main.COIN_LOGOS)


class RadarLayoutTests(BaseShellTests):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            conn.execute(
                """INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                   created_at, updated_at) VALUES ('XRP', 'long', 95.0, 96.0, 101.0, 94.0, 110.0, 1.0, ?, ?)""",
                (db.now_iso(), db.now_iso()))
            conn.execute(
                """INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                   take_profit, trade_type, created_at) VALUES (NULL, 'ETH', 'long', 'x', 'hoog', 1, 100, 97, 106, 'smc', ?)""",
                (db.now_iso(),))

    def test_radar_in_de_nieuwe_indeling(self):
        html = self.client.get("/smc").text
        for needle in ['data-utabs="radar"', 'id="tab-wachten"', 'id="tab-open"', 'id="tab-afgerond"', 'class="mrow"',
                       'data-vd-price="XRP"', 'data-vd-price="ETH"', "data-radar-key", 'data-radar="state"', "r-progress",
                       "Wacht op de zone", "Koers op ", "SMC-radar", "<title>SMC-radar"]:
            self.assertIn(needle, html, needle)
        self.assertRegex(html, r'class="hl-num">1</span><span class="hl-unit">wachten')
        self.assertRegex(html, r"<dt>Open trades</dt>\s*<dd[^>]*><span class=\"kl-num\">1</span>")
        self.assertNotIn('class="radar-head"', html)

    def test_radar_kernregels_en_zoekveld(self):
        html = self.client.get("/smc").text
        self.assertIn('class="kl"', html)
        self.assertIn("Niet meer actief", html)
        self.assertIn('id="fsearch"', html)


class ZoneRadarLayoutTests(BaseShellTests):
    def setUp(self):
        super().setUp()
        repo.insert_zone_radar_setup({"coin": "TIA", "direction": "long", "tf": "1h", "zone_key": "1h:bull:x", "zone_low": 95.0, "zone_high": 96.0,
                                      "stop_loss": 94.5, "take_profit": 104.0, "rr": 5.3, "atr": 0.5, "target_tf": "4h", "target_low": 104.0,
                                      "target_high": 105.0}, db.now_iso())

    def test_zone_radar_kaart_op_de_radar_en_vandaag(self):
        html = self.client.get("/smc").text
        for needle in ['id="radar-zone-1"', 'data-radar-key="zone:1"', '<span class="kind-tag">Zone-radar</span>', '<span class="kind-tag is-untested">ongetest</span>',
                       "Vraagzone op 1u", "Wacht op de zone", 'class="now-line" data-radar="action">Wacht tot de koers 96.0000 bereikt.']:
            self.assertIn(needle, html, needle)
        self.assertIn('"zone:1"', self.client.get("/api/radar").text)
        self.assertIn("Zone-radar", self.client.get("/vandaag").text)


class SetupsLayoutTests(BaseShellTests):
    def seed_waiting(self):
        import json
        from datetime import datetime, timedelta, timezone
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        repo.insert_structure_setup({
            "coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "Schone range.", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        long_plan = {"level": 100.0, "stop": 99.0, "risk_pct": 1.0, "targets": [102.0, 103.0], "targets_r": [2.0, 3.0], "candles": candles}
        repo.insert_structure_setup({
            "coin": "SOL", "direction": "long", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "B", "reason": "Tweede range.", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(long_plan)})
        repo.insert_structure_setup({
            "coin": "ETH", "direction": "long", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "B", "reason": "Geen ruimte.", "features": "{}", "state": "geen_plan", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": None})

    def test_setups_in_de_nieuwe_indeling(self):
        self.seed_waiting()
        with db.session() as conn:
            conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                            take_profit, trade_type, created_at) VALUES (NULL, 'SOL', 'long', 'x', 'hoog', 1, 100, 99, 102, 'trend', ?)""", (db.now_iso(),))
        html = self.client.get("/structuur").text
        for needle in ['data-utabs="setups"', 'id="tab-klaarstaand"', 'id="tab-trend"', 'id="tab-eerder"', 'class="st-meta"',
                       "Laatste 24 uur: 3 kansen gezien, 2 beoordeeld", "Sterk en redelijk</a>", "stack-toggle", 'class="mrow"',
                       "Instap 100.0000, stop 99.0000, doel 102.0000", "Geen ruimte."]:
            self.assertIn(needle, html, needle)
        self.assertRegex(html, r'class="hl-num">2</span><span class="hl-unit">klaar')
        self.assertNotIn("·</span>", html[html.index('id="tab-trend"'):html.index('id="tab-eerder"')])

    def test_tellingen_staan_in_een_stille_regel(self):
        self.seed_waiting()
        html = self.client.get("/structuur").text
        meta = html[html.index('class="st-meta"'):html.index('data-utabs="setups"')]
        self.assertRegex(meta, r"<b>3</b> gezien</span><span><b>2</b> beoordeeld</span><span><b>1</b> zonder plan")
        self.assertNotIn('class="kl"', html[:html.index('data-utabs="setups"')])

    def test_stille_bediening_zonder_gevulde_pillen(self):
        self.seed_waiting()
        html = self.client.get("/structuur").text
        row = html[html.index('class="filter-row"'):html.index('id="stack-bar"')]
        self.assertIn('class="filter-chips"', row)
        self.assertRegex(row, r'<button type="button" class="stack-toggle" id="stack-toggle" aria-pressed="false">Stapel</button>')
        self.assertNotIn("Toon als stapel", html)
        self.assertNotIn('class="chip" id="stack-', html)
        bar = html[html.index('id="stack-bar"'):html.index('class="setup-grid"')]
        self.assertIn(" hidden>", bar[:60])
        for needle in ['id="stack-prev" aria-label="Vorige kaart"', 'id="stack-count"', 'id="stack-next" aria-label="Volgende kaart"',
                       'class="stack-actions" role="group"']:
            self.assertIn(needle, bar, needle)
        self.assertRegex(bar, r'class="stack-act" id="stack-skip">.*Negeer</button>')
        self.assertRegex(bar, r'class="stack-act is-keep" id="stack-keep">.*Bewaar</button>')
        self.assertRegex(bar, r'class="stack-act" id="stack-reset">.*Opnieuw</button>')

    def test_een_kaart_geeft_geen_stapelbediening(self):
        self.seed_waiting()
        html = self.client.get("/structuur?kant=long").text
        self.assertEqual(html.count('class="setup-card'), 1)
        self.assertNotIn('id="stack-toggle"', html)
        self.assertNotIn('id="stack-bar"', html)

    def test_kaartkop_met_logo_en_bewijs_achter_een_tik(self):
        self.seed_waiting()
        html = self.client.get("/structuur").text
        card = html[html.index('class="setup-card'):html.index("</article>")]
        head = card[card.index('class="setup-head"'):card.index("</header>")]
        self.assertIn('class="coin-av setup-av', head)
        self.assertNotIn("dist-ring", card)
        self.assertNotIn('class="proof-line', card)
        self.assertRegex(head, r'class="radar-dir radar-dir-(long|short)">')
        self.assertRegex(head, r'class="setup-grade setup-grade-[abc]" title="Oordeel van de CEO">(Sterk|Redelijk|Zwak)</span>')
        self.assertRegex(head, r'class="proof-tag is-proef"><button type="button" class="kl-term" popovertarget="pt-structuur-s\d+">In proef</button>')
        pop = head[head.index("popover>"):]
        self.assertIn('<a class="proof-pop-link" href="/bewijs">Bekijk Bewijs</a>', pop)

    def test_stap_een_heeft_een_afstandsbalk(self):
        self.seed_waiting()
        with mock.patch.object(main, "_cached_prices", new=mock.AsyncMock(return_value={"BTC": 99.0, "SOL": 101.0})):
            html = self.client.get("/structuur").text
        step = html[html.index('class="vd-step is-now"'):]
        step = step[:step.index("</li>")]
        self.assertRegex(step, r'<span class="muted step-dist"><span class="step-approach" aria-hidden="true"><i style="width: \d+%"></i></span>Nog <span data-vd="distance"')

    def test_lege_staat_blijft(self):
        html = self.client.get("/structuur").text
        self.assertIn("Geen plan klaar", html)
        self.assertRegex(html, r'class="hl-num">0</span><span class="hl-unit">klaar')


class RangeSweepLayoutTests(BaseShellTests):
    def as_leerling(self):
        leerling = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(leerling))
        main._ceo_cache.update(at=0.0)

    def test_de_ceo_ziet_de_kaart_met_stop_als_kop_en_zonder_doel(self):
        range_seed.seed_lab()
        range_seed.seed_setup()
        html = self.client.get("/structuur").text
        card = html[html.index('id="range-sweep-'):html.index("</article>", html.index('id="range-sweep-'))]
        for needle in ["doel kies je zelf", 'class="sc-zone', 'class="sc-range', "sc-limit", "sc-stop", "ongetest", "Zone-retest 2u",
                       "Midden (ref.)", "Overkant (ref.)", "Historische kans (lab, 412 trades)", "+6R", "level-chips", "Zet limietorders: 40% op 101.00 en 60% op 101.50"]:
            self.assertIn(needle, card, needle)
        self.assertRegex(card, r'hl-label"><button[^>]*>Stop</button>')
        self.assertRegex(card, r'class="hl-num">1,68</span><span class="hl-unit">%')            # (103 - 101.3) / 101.3, de gewogen instap
        self.assertIn("kosten", card)
        self.assertNotRegex(card, r"[Dd]oel \d")                                              # geen doelniveau, alleen de referenties
        self.assertIn("geen belofte", card)

    def test_de_score_is_een_beschrijving_en_geen_voorspeller(self):
        range_seed.seed_setup()
        card = self.client.get("/structuur").text
        card = card[card.index('id="range-sweep-'):]
        self.assertIn("score 85 van 100", card)
        self.assertIn("geen bewezen voorspeller", card)
        self.assertIn("Beide randen minstens 4 keer aangeraakt", card)
        self.assertIn("Zone dun", card)

    def test_zonder_labrij_geen_doelkanstabel_en_geen_verzonnen_getal(self):
        range_seed.seed_setup()
        card = self.client.get("/structuur").text
        self.assertNotIn("Historische kans", card)
        self.assertIn('id="range-sweep-', card)

    def test_een_lab_van_een_andere_variant_leent_geen_cijfers(self):
        range_seed.seed_lab()
        range_seed.seed_setup(variant="RS_1H")
        self.assertNotIn("Historische kans", self.client.get("/structuur").text)

    def test_tabs_range_sweep_en_ranges_en_de_ranges_rijen(self):
        range_seed.seed_setup()
        repo.upsert_range_watch({"coin": "SOL", "tf": "2h", "range_high": 104.0, "range_low": 96.0, "first_at": "2026-10-10T00:00:00+00:00",
                                 "found_at": "2026-10-10T04:00:00+00:00", "atr": 1.0})
        repo.upsert_range_watch({"coin": "ETH", "tf": "4h", "range_high": 120.0, "range_low": 80.0, "first_at": "2026-10-09T00:00:00+00:00",
                                 "found_at": "2026-10-09T04:00:00+00:00", "atr": 2.0})
        repo.set_range_watch_state(repo.upsert_range_watch({"coin": "BNB", "tf": "1h", "range_high": 1.0, "range_low": 0.5, "first_at": "2026-10-08T00:00:00+00:00",
                                                           "found_at": "2026-10-08T04:00:00+00:00", "atr": 0.1})[0], "gebroken")
        html = self.client.get("/structuur").text
        self.assertIn('id="tab-ranges"', html)
        self.assertRegex(html, r'href="#tab-range-sweep"[^>]*>Range sweep <i class="ut-count">1</i>')
        self.assertRegex(html, r'href="#tab-ranges"[^>]*>Ranges <i class="ut-count">2</i>')
        panel = html[html.index('id="tab-ranges"'):]
        panel = panel[:panel.index("</section>")]
        self.assertEqual(panel.count('class="mrow"'), 2)                              # de gebroken range hoort niet bij wat gevolgd wordt
        for needle in ["SOL", "ETH", "96.0000 tot 104.00", "tot boven", "2u", "4u"]:
            self.assertIn(needle, panel, needle)
        self.assertNotIn("BNB", panel)
        self.assertLess(panel.index("SOL"), panel.index("ETH"))                       # SOL ligt dichter bij een rand (4%) dan ETH (20%)

    def test_lege_staat_wijst_naar_de_ranges(self):
        html = self.client.get("/structuur").text
        self.assertIn("Geen setup klaar", html)
        self.assertIn('href="#tab-ranges"', html)

    def test_een_leerling_ziet_niets_van_de_range_sweep(self):
        range_seed.seed_lab()
        range_seed.seed_setup()
        repo.upsert_range_watch({"coin": "SOL", "tf": "2h", "range_high": 104.0, "range_low": 96.0, "first_at": "2026-10-10T00:00:00+00:00",
                                 "found_at": "2026-10-10T04:00:00+00:00", "atr": 1.0})
        self.as_leerling()
        for pad in ("/structuur", "/smc", "/vandaag"):
            html = self.client.get(pad).text
            for needle in ("range-sweep-", "Ranges", "Range sweep", "tab-ranges", "doel kies je zelf", "sc-zone"):
                self.assertNotIn(needle, html, f"{pad}: {needle}")

    def test_openbaar_zet_het_voor_iedereen_open(self):
        range_seed.seed_setup()
        self.as_leerling()
        with mock.patch.object(main.rule_live, "CEO_ONLY_TYPES", main.rule_live.ceo_only_types(True)):
            self.assertIn('id="range-sweep-', self.client.get("/structuur").text)

    def test_verlopen_en_weggelopen_staan_niet_op_de_pagina(self):
        range_seed.seed_setup(coin="ARB", hours_left=-1.0)                                            # verlopen
        range_seed.seed_setup(coin="OP", range_low=90.0, range_high=99.0)                             # midden 94,5 ligt onder de koers: een short is niet weggelopen
        range_seed.seed_setup(coin="SOL", direction="long", range_high=100.0, range_low=90.0)         # midden 95 < koers 100: weggelopen voor een long
        range_seed.seed_setup(coin="ETH", stop=99.9)                                                  # koers voorbij de stop
        html = self.client.get("/structuur").text
        self.assertEqual(html.count('id="range-sweep-'), 1)
        self.assertIn("OP", html[html.index('id="range-sweep-'):])

    def test_radar_toont_de_range_sweep_niet_meer(self):
        range_seed.seed_setup()
        html = self.client.get("/smc").text
        self.assertEqual(html.count('id="range-sweep-'), 0)
        self.assertRegex(html, r'class="hl-num">0</span><span class="hl-unit">wachten')


class BewijsLayoutTests(BaseShellTests):
    def seed(self):
        with db.session() as conn:
            for outcome in ("take_profit", "stop_loss", "stop_loss"):
                conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                                take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                                VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', ?, ?, ?)""", (outcome, db.now_iso(), db.now_iso()))
            conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                            take_profit, trade_type, created_at) VALUES (NULL, 'ETH', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', ?)""", (db.now_iso(),))

    def test_totaal_is_het_grote_getal_en_geen_rij(self):
        self.seed()
        user = repo.get_user_by_username("tester")
        summary = main.track_record.summarize(main.report_rows(user), main.config.TRACK_RECORD_COST_PCT)
        total = next(e for e in summary if e["source"] == "alles")
        html = self.client.get("/bewijs").text
        self.assertIn('class="hl-num">%+.2f</span><span class="hl-unit">R per trade' % total["avg_net"], html)
        for needle in ['data-utabs="bewijs"', 'id="tab-soort"', 'id="tab-regels"', 'id="tab-curves"', 'id="tab-uurkaart"', 'class="kl"',
                       "Open of vervallen", "1 winst, 2 verlies", "Resultaatcurve per soort", "Uurkaart", 'class="hourmap"',
                       'class="equity-dd"', "proof-spark", "Nog te weinig data", "die tellen niet mee"]:
            self.assertIn(needle, html, needle)
        rows = html[html.index('id="tab-soort"'):html.index('id="tab-regels"')]
        self.assertEqual(rows.count('class="mrow-wrap'), len(summary) - 1)
        self.assertNotIn("Alle meldingen samen", rows)

    def test_lege_staat(self):
        html = self.client.get("/bewijs").text
        self.assertIn("Nog geen signalen om te meten.", html)


class RangeSweepPageMixin:
    def as_leerling(self):
        leerling = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(leerling))
        main._ceo_cache.update(at=0.0)
        main._proof_cache.update(at=0.0)

    def seed_all(self):
        range_seed.seed_labs()
        self.stopped = range_seed.seed_trade(coin="ARB", stop_hit=True, ref_r=-1.0, closed=True)
        self.won = range_seed.seed_trade(coin="APT", direction="long", ref_r=2.4, reached=3, stop_hit=False, closed=True)
        self.running = range_seed.seed_trade(coin="WLD", direction="long")
        range_seed.seed_setup(coin="AAVE")
        for coin, state in (("OP", "verlopen"), ("LINK", "weggelopen"), ("SOL", "stop_voor_vulling")):
            repo.set_range_sweep_setup_state(range_seed.seed_setup(coin=coin), state)


class RangeSweepBewijsTests(RangeSweepPageMixin, BaseShellTests):
    def test_de_ceo_ziet_stopkwaliteit_lab_naast_live_en_de_eerlijke_telling(self):
        self.seed_all()
        html = self.client.get("/bewijs").text
        sec = html[html.index('id="range-sweep"'):]
        sec = sec[:sec.index("</section>")]
        for needle in ["Range sweep, stopkwaliteit", "ongetest", "Stop geraakt", "+1R vóór de stop", "+6R vóór de stop", "Kosten in R", "Te krappe stops", "niet gemeten",
                       "R gemeten bij de referentie-uitgang", "Geen vast doel", "Stopkwaliteit: geslaagd", "Strenge toets op een voordeel: niet geslaagd", "30 toetsen", "64",
                       "In proef", "2 afgeronde", "1 lopend", "3 niet gevuld", "1 verlopen", "1 weggelopen", "1 stop voor de vulling", "1 wachtend", "55%"]:
            self.assertIn(needle, sec, needle)
        self.assertNotIn("Negatief", sec)                       # de strenge toets alleen is geen reden voor Negatief
        self.assertNotIn("Bewezen", sec.replace("niet bewezen", "").replace("Niets is bewezen", ""))

    def test_de_score_en_de_doelkans_zijn_geen_voorspeller(self):
        self.seed_all()
        sec = self.client.get("/bewijs").text
        sec = sec[sec.index('id="range-sweep"'):]
        self.assertIn("geen voorspeller", sec)
        self.assertIn("historisch", sec)
        self.assertNotRegex(sec, r"kans op winst|win-?kans")

    def test_lopende_trades_staan_ernaast_met_hun_stand_en_tellen_niet_mee(self):
        self.seed_all()
        sec = self.client.get("/bewijs").text
        sec = sec[sec.index('id="range-sweep"'):]
        self.assertRegex(sec, r"1 lopend.{0,200}geen uitkomst")
        total = main.track_record.summarize(main.report_rows(repo.get_user_by_username("tester")), main.config.TRACK_RECORD_COST_PCT)
        entry = next(e for e in total if e["trade_type"] == "range_sweep")
        self.assertEqual((entry["resolved"], entry["open_or_expired"]), (2, 1))

    def test_zonder_trades_een_lege_staat_zonder_verzonnen_getallen(self):
        range_seed.seed_labs()
        sec = self.client.get("/bewijs").text
        sec = sec[sec.index('id="range-sweep"'):]
        self.assertIn("Nog geen gevulde setups", sec)
        self.assertIn("0 afgeronde", sec)

    def test_een_leerling_ziet_niets_van_de_range_sweep_op_bewijs(self):
        self.seed_all()
        self.as_leerling()
        html = self.client.get("/bewijs").text
        for needle in ("range-sweep", "Range sweep", "stopkwaliteit", "referentie-uitgang", "Zone-retest", "range_sweep", "rs_1h", "rz_2h"):
            self.assertNotIn(needle, html, needle)
        self.assertIn("Nog geen signalen om te meten.", html)      # de proeftrades zitten niet in de totalen van een leerling

    def test_openbaar_toont_de_sectie_aan_een_leerling(self):
        self.seed_all()
        self.as_leerling()
        with mock.patch.object(main.rule_live, "CEO_ONLY_TYPES", main.rule_live.ceo_only_types(True)):
            html = self.client.get("/bewijs").text
        self.assertIn("Range sweep, stopkwaliteit", html)

    def test_de_publieke_keten_noemt_de_range_sweep_niet(self):
        self.seed_all()
        self.client.cookies.clear()
        for pad in ("/keten", "/keten.json"):
            text = self.client.get(pad).text
            self.assertNotIn("range_sweep", text, pad)
            self.assertNotIn("Range sweep", text, pad)

    def test_regels_toont_de_range_sweep_niet_als_regel_zonder_motor(self):
        self.seed_all()
        html = self.client.get("/bewijs").text
        others = html[html.index("proof-others"):] if "proof-others" in html else ""
        self.assertNotIn("range_sweep", others)
        self.assertNotIn("Range sweep, stopkwaliteit", others.split("</details>")[0])


class RangeSweepKansPageTests(RangeSweepPageMixin, BaseShellTests):
    def test_de_kanspagina_toont_de_tekening_de_meting_en_de_referentie(self):
        self.seed_all()
        html = self.client.get(f"/kans/{self.stopped}").text
        for needle in ["sc-range", "sc-zone", "sc-stop", "Stop geraakt", "Referentie-uitgang (meelopende stop 3 ATR op 1u): -1,00R", "Jouw trade beslis je zelf.",
                       "Limiet 1 gevuld (40%)", "Limiet 2 gevuld (60%)", "Meting klaar", "ongetest", "Stopafstand", "Kosten in R"]:
            self.assertIn(needle, html, needle)
        self.assertNotIn("Doel geraakt", html)
        self.assertNotIn("raakten het doel", html)
        self.assertNotRegex(html, r"R:R")

    def test_de_bewijsregel_onder_de_kans_is_in_proef_bij_geslaagde_stopkwaliteit_en_mislukt_voordeel(self):
        self.seed_all()
        main._proof_cache.update(at=0.0)
        html = self.client.get(f"/kans/{self.stopped}").text
        line = html[html.index('class="proof-line'):]
        line = line[:line.index("</p>")]
        self.assertIn("<strong>In proef</strong>", line)
        self.assertNotIn("Negatief", line)

    def test_een_gewonnen_referentie_staat_er_niet_als_doel(self):
        self.seed_all()
        html = self.client.get(f"/kans/{self.won}").text
        self.assertIn("Referentie-uitgang (meelopende stop 3 ATR op 1u): +2,40R", html)
        self.assertIn("+3R bereikt vóór de stop", html)
        self.assertNotIn("Doel geraakt", html)
        self.assertNotIn("✓ Referentie", html)

    def test_een_lopende_trade_zegt_loopt_nog_zonder_referentie(self):
        self.seed_all()
        html = self.client.get(f"/kans/{self.running}").text
        self.assertIn("Loopt nog", html)
        self.assertNotIn("Referentie-uitgang (", html)

    def test_een_leerling_krijgt_een_404(self):
        self.seed_all()
        self.as_leerling()
        self.assertEqual(self.client.get(f"/kans/{self.stopped}").status_code, 404)

    def test_openbaar_geeft_de_leerling_de_pagina(self):
        self.seed_all()
        self.as_leerling()
        with mock.patch.object(main.rule_live, "CEO_ONLY_TYPES", main.rule_live.ceo_only_types(True)):
            self.assertEqual(self.client.get(f"/kans/{self.stopped}").status_code, 200)


class ListPagesLayoutTests(BaseShellTests):
    def seed_signal(self):
        user = repo.get_user_by_username("tester")
        sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "x", "confidence": "hoog", "technical_confirmed": 1, "hard_gates_ok": 1, "price": 100.0,
                                  "stop_loss": 99.0, "take_profit": 102.0, "trade_type": "smc"})
        repo.create_journal_entry(sid, user["id"], 10.0)
        return user

    def test_signalen_linktabs_en_menu_met_formulier(self):
        self.seed_signal()
        html = self.client.get("/signalen").text
        self.assertIn('class="ph"', html)
        self.assertRegex(html, r'class="ut-tab[^"]*" href="/signalen\?alles=1"')
        menu = html[html.index('class="ut-menu'):]
        self.assertIn('action="/signalen/verbergen-alles"', menu[:menu.index("</details>")])
        self.assertNotIn("view-toggle", html)

    def test_signalen_alles_heeft_geen_verbergen_formulier(self):
        self.seed_signal()
        html = self.client.get("/signalen?alles=1").text
        self.assertNotIn("verbergen-alles", html)
        self.assertIn('class="ut-tab is-active" href="/signalen?alles=1"', html)

    def test_meldingen_groot_getal_en_hooks_blijven(self):
        user = repo.get_user_by_username("tester")
        repo.create_notification(user["id"], "update", "Nieuw", "Tekst", "/vandaag")
        html = self.client.get("/meldingen").text
        self.assertIn('class="hl-num">1</span><span class="hl-unit">ongelezen', html)
        self.assertIn("data-notification-id", html)
        self.assertIn('action="/meldingen/alles-gelezen"', html)

    def test_week_in_de_nieuwe_indeling(self):
        html = self.client.get("/week?dagen=30").text
        self.assertRegex(html, r'class="ut-tab is-active" href="/week\?dagen=30"[^>]*>1M<')
        for needle in ['class="ph"', "data-share-chart", "laatste 30 dagen", 'class="hl-num"', 'class="kl"', "ceo-headline"]:
            self.assertIn(needle, html, needle)
        self.assertNotIn("kans-outcome", html)


class CoinLayoutTests(BaseShellTests):
    def test_koers_is_het_grote_getal_met_live_haken(self):
        user = repo.get_user_by_username("tester")
        repo.add_coin_if_new("BTC", "crypto")
        html = self.client.get("/coins/BTC").text
        self.assertIn('class="hl-num"', html)
        self.assertIn('id="coin-price"', html)
        self.assertIn('data-symbol="BTC"', html)
        for needle in ['class="ph"', 'data-spark-coin="BTC"', 'data-spark-chg="BTC"', 'class="kl"', "Signalen deze week", "Hoog vertrouwen", "Notitie",
                       '<span class="hl-unit">USDT</span>']:
            self.assertIn(needle, html, needle)
        self.assertNotIn("coin-price-number", html)

    def test_serverkoers_heeft_dezelfde_nl_notatie_als_de_live_js(self):
        repo.add_coin_if_new("BTC", "crypto")
        with mock.patch.object(main.exchange, "fetch_last_price", return_value=67002.99):
            html = self.client.get("/coins/BTC").text
        self.assertIn("67.002,99", html)
        self.assertNotIn("67 002.99", html)
        self.assertEqual([main._nl_price(v) for v in (0.1632, 99.5, 100.0, 1234567.891)], ["0,1632", "99,5000", "100,00", "1.234.567,89"])

    def test_notitie_staat_niet_dubbel_als_de_banner_zichtbaar_is(self):
        repo.add_coin_if_new("BTC", "crypto")
        self.assertIn("<dt>Notitie</dt>", self.client.get("/coins/BTC").text)
        repo.set_coin_note("BTC", "Wachten op de retest")
        html = self.client.get("/coins/BTC").text
        self.assertIn("coin-note-banner", html)
        self.assertNotIn("<dt>Notitie</dt>", html)

    def test_plan_en_risicobedrag_blijven(self):
        import json
        from datetime import datetime, timedelta, timezone
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        repo.insert_structure_setup({"coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "x", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        self.client.post("/settings/risico", data={"risk_eur": "25"}, follow_redirects=False)
        html = self.client.get("/coins/BTC").text
        self.assertIn("Plan voor BTC", html)
        self.assertIn("verlies je ongeveer € 25", html)


class RestLayoutTests(BaseShellTests):
    def test_account(self):
        html = self.client.get("/account").text
        for needle in ['class="ph"', ">Account<", 'class="hl-num"', 'class="kl"',
                       "Nieuwe kansen", "Drempel", "Maximaal aantal pushes per dag"]:
            self.assertIn(needle, html, needle)
        self.assertNotIn("summary-strip", html)

    def test_ceo(self):
        repo.create_user("leerling1", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        html = self.client.get("/ceo").text
        for needle in ['class="ph"', ">De CEO<", 'class="kl"', "Dagen in functie", "Chief Executive Officer", "De leerlingen", "Leerling van de maand", "Aanwezigheid"]:
            self.assertIn(needle, html, needle)

    def test_kans(self):
        sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "x", "confidence": "hoog", "technical_confirmed": 1,
                                  "hard_gates_ok": 1, "price": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "trade_type": "smc"})
        r = self.client.get("/kans/%d" % sid)
        self.assertEqual(r.status_code, 200)
        # Het plan staat in hetzelfde blok als op de Radar (macro level_chips), met bovenaan wat je nu doet.
        for needle in ['class="ph"', ">BTC long<", 'class="level-chips"', "Instap", "R:R", "Trade loopt. Stop 99.0000, doel 102.00."]:
            self.assertIn(needle, r.text, needle)

    def test_uitleg_en_keten_hebben_een_kop(self):
        self.assertIn('class="ph"', self.client.get("/uitleg").text)
        self.assertIn(">Handleiding<", self.client.get("/uitleg").text)
        anon = TestClient(main.app).get("/keten")
        self.assertIn('class="ph"', anon.text)
        self.assertIn(">Ketting<", anon.text)

    def test_meer_blad_en_uitloggen(self):
        for path in ("/account", "/ceo", "/uitleg"):
            html = self.client.get(path).text
            sheet = html[html.index('id="more-sheet"'):]
            self.assertIn('<form action="/logout" method="post" class="more-logout">', sheet, path)
