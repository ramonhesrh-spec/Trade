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
        self.assertIn("--glow-edge: #0c2c2b;", css)
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
        for needle in ['data-utabs="setups"', 'id="tab-klaarstaand"', 'id="tab-trend"', 'id="tab-eerder"', 'class="kl"',
                       "Laatste 24 uur: 3 kansen gezien, 2 beoordeeld", "Alleen sterk en redelijk", "stack-toggle", 'class="mrow"',
                       "Instap 100.0000, stop 99.0000, doel 102.0000", "Geen ruimte."]:
            self.assertIn(needle, html, needle)
        self.assertRegex(html, r'class="hl-num">2</span><span class="hl-unit">klaar')
        self.assertNotIn("·</span>", html[html.index('id="tab-trend"'):html.index('id="tab-eerder"')])

    def test_lege_staat_blijft(self):
        html = self.client.get("/structuur").text
        self.assertIn("Geen plan klaar", html)
        self.assertRegex(html, r'class="hl-num">0</span><span class="hl-unit">klaar')


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
        for needle in ['class="ph"', ">BTC long<", 'class="kl"', "Instap", "R:R"]:
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
