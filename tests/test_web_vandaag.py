import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, rule_live, security


def scenario_row(**kw):
    row = {"direction": "long", "trigger_type": "close_above", "trigger_level": 101.0, "entry": 100.8, "stop_loss": 99.8,
           "take_profit": 103.0, "reason": "Break boven gisteren hoog."}
    row.update(kw)
    return row


class WebVandaagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        db.init_db()
        from web import main
        self.main = main
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

    def test_ring_counts_chance_pushes_of_the_last_24_hours(self):
        uid = repo.get_user_by_username("tester")["id"]
        now = datetime.now(timezone.utc)
        repo.record_push(uid, "BTC", "long", now.isoformat())
        repo.record_push(uid, "ETH", "long", (now - timedelta(hours=30)).isoformat())     # buiten het venster
        r = self.client.get("/vandaag")
        self.assertIn("1 van 6 meldingen in 24 uur", r.text)
        self.assertIn('stroke-dashoffset="83.3"', r.text)

    def test_setups_page_shows_waiting_structure_setup_with_chart(self):
        import json
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        sid = repo.insert_structure_setup({
            "coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "Schone range.", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        r = self.client.get("/structuur")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'id="structuur-{sid}"', r.text)
        self.assertIn("Laatste 24 uur: 1 kans gezien, 1 beoordeeld", r.text)
        live = self.client.get("/api/kansen").json()
        self.assertIn(str(sid), live["structuur"])                         # live afstand per wachtend plan
        self.assertIn("te gaan", r.text)
        self.assertIn("sc-limit", r.text)
        self.assertIn('data-live-coin="BTC"', r.text)                      # live.js volgt de koers van de beurt
        self.assertIn("Schone range.", r.text)

    def test_setups_filter_shows_only_a_and_b_on_request(self):
        import json
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        for coin, grade in (("BTC", "A"), ("ETH", "C")):
            repo.insert_structure_setup({
                "coin": coin, "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
                "line_slope": 0.0, "atr": 0.5, "grade": grade, "reason": f"Reden {grade}.", "features": "{}", "state": "waiting",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        both = self.client.get("/structuur").text
        self.assertIn("Reden A.", both)
        self.assertIn("Reden C.", both)
        only = self.client.get("/structuur?alleen=ab").text
        self.assertIn("Reden A.", only)
        self.assertNotIn("Reden C.", only)

    def test_kansen_tab_telt_wat_het_paneel_toont_of_zegt_waar_de_rest_staat(self):
        import json
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        for coin in ("BTC", "ETH", "SOL"):
            repo.insert_structure_setup({
                "coin": coin, "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
                "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "Reden.", "features": "{}", "state": "waiting",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        text = self.client.get("/vandaag").text
        self.assertEqual(text.count('class="setup-card'), 3)              # geen afkapping: alles wat geteld wordt staat er
        self.assertRegex(text, r'<dt>.*?Kansen open.*?</dt>\s*<dd[^>]*><span class="kl-num">3</span>')
        self.assertIn('<i class="ut-count">3</i>', text)

    def test_tabbar_filters_and_empty_state_invite_the_user(self):
        text = self.client.get("/vandaag").text
        self.assertIn('class="tabbar"', text)                              # onderbalk met tabs voor de telefoon
        self.assertIn('<nav class="ut-menu">', text)                      # drie-puntjesmenu met Mijn week, Beste setups en Instellingen
        self.assertNotIn("quick-actions", text)
        self.assertIn("Geen plan klaar", self.client.get("/structuur").text)   # lege staat met uitleg en een knop
        self.assertIn("Alleen sterk en redelijk", self.client.get("/structuur?kant=short").text)

    def test_grade_c_card_is_muted_and_shows_facts_not_a_verdict(self):
        import json
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        repo.insert_structure_setup({
            "coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "C", "reason": "Te weinig ruimte.", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        text = self.client.get("/structuur").text
        self.assertIn("is-weak", text)
        self.assertNotIn("De CEO twijfelt", text)                          # geen gevoel van een model, maar controlepunten en bewijs
        self.assertIn("Zwak", text)
        self.assertIn("Lijn of range minstens 3 keer aangeraakt", text)
        self.assertIn("In proef", text)                                    # bewijsregel met de proefbalk
        self.assertEqual(text.count("Te weinig ruimte."), 1)               # de toelichting staat één keer

    def test_coin_page_shows_masthead_price_and_waiting_structure_plan(self):
        import json
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        repo.insert_structure_setup({
            "coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "Schone range.", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        r = self.client.get("/coins/BTC")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id="coin-price"', r.text)
        self.assertIn("100.00", r.text)
        self.assertIn("Plan voor BTC", r.text)
        self.assertIn("Zet een limietorder op", r.text)
        self.assertEqual(self.client.get("/api/price/BTC").json(), {"price": 100.0})
        self.assertNotIn("Plan voor ETH", self.client.get("/coins/ETH").text)
        self.assertNotIn("verlies je ongeveer", r.text)                   # zonder ingevuld bedrag geen eurobedrag
        self.client.post("/settings/risico", data={"risk_eur": "25"}, follow_redirects=False)
        self.assertIn("verlies je ongeveer € 25", self.client.get("/coins/BTC").text)
        self.client.post("/settings/risico", data={"risk_eur": "abc"}, follow_redirects=False)
        self.assertNotIn("verlies je ongeveer", self.client.get("/coins/BTC").text)

    def test_coin_menu_lists_coins_on_every_page(self):
        repo.add_coin_if_new("BTC", "crypto")
        for path in ("/vandaag", "/structuur", "/bewijs", "/smc", "/meldingen"):
            self.assertIn('href="/coins/BTC"', self.client.get(path).text, path)

    def test_empty_state_is_honest_and_page_works(self):
        r = self.client.get("/vandaag")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Nog geen script geschreven", r.text)
        self.assertIn("De verzamelaar is net gestart", r.text)
        self.assertIn("Geen nieuws van de laatste 12 uur", r.text)
        self.assertIn("vd-timeline", r.text)

    def test_board_counts_open_chances_of_every_kind_not_only_structure_plans(self):
        r = self.client.get("/vandaag")
        self.assertIn("Er staat niets open", r.text)
        self.assertIn("Geen open kansen. Je krijgt een melding zodra er een staat.", r.text)
        self.assertNotIn('class="ut-count"', r.text)                      # geen badge met 0
        signal = {"message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "trend", "pattern_name": "Trend-pullback",
                  "price": 100.0, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None, "atr": None,
                  "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Trend-pullback",
                  "reason": "test", "stop_loss": 99.0, "take_profit": 102.0, "context_note": None, "is_practice": 0, "plain_explanation": None,
                  "suggested_entry_low": None, "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None}
        repo.insert_signal(signal)
        text = self.client.get("/vandaag").text
        self.assertIn("Trend · Open, gemeld", text)                       # een soort zonder kaart krijgt een compacte rij
        self.assertNotIn("Er staat niets open", text)
        self.assertNotIn("Geen open kansen", text)
        self.assertNotIn("jaar candles", text)

    def seed_chances(self):
        """Een gemengde stand: een geldig plan, een verlopen plan, een plan voorbij zijn stop, meldingen van een leerling-soort en een CEO-soort."""
        import json
        now = datetime.now(timezone.utc)
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]

        def structure(coin, hours, stop=101.0):
            plan = {"level": 100.0, "stop": stop, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
            repo.insert_structure_setup({
                "coin": coin, "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
                "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "Reden.", "features": "{}", "state": "waiting",
                "expires_at": (now + timedelta(hours=hours)).isoformat(), "plan": json.dumps(plan)})
        structure("BTC", 3)
        structure("ETH", -1)                    # verlopen, de engine heeft hem nog niet omgezet
        structure("SOL", 3, stop=99.5)          # koers (100) staat al voorbij de stop
        base = {"message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "trend", "pattern_name": "x",
                "price": 100.0, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None, "atr": None,
                "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "x",
                "reason": "test", "stop_loss": 99.0, "take_profit": 102.0, "context_note": None, "is_practice": 0, "plain_explanation": None,
                "suggested_entry_low": None, "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None}
        repo.insert_signal(dict(base, trade_type="rejectie"))
        repo.insert_signal(dict(base, trade_type=rule_live.RULE), chain_it=False)
        repo.insert_signal(dict(base, trade_type="trend", stop_loss=100.5))      # voorbij de stop
        repo.insert_market_script("ETH", "x", "long", "m", [scenario_row()], 0, (now - timedelta(hours=1)).isoformat())     # script verlopen

    def count_and_rows(self):
        import re
        text = self.client.get("/vandaag").text
        shown = text.count('class="setup-card') + len(re.findall(r'<a class="mrow"', text))
        count = int(re.search(r'Kansen open.*?<span class="kl-num">(\d+)</span>', text, re.S).group(1))
        return text, count, shown

    def test_count_equals_rendered_rows_for_a_leerling_and_the_ceo_sees_the_proefsoort(self):
        self.seed_chances()
        _, count, shown = self.count_and_rows()                           # tester is de eerst aangemaakte gebruiker, dus de CEO
        self.assertEqual((count, shown), (3, 3))                          # BTC-plan, rejectie en de proefsoort; verlopen en doorgelopen niet
        leerling = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(leerling))
        self.main._ceo_cache.update(at=0.0)
        text, count, shown = self.count_and_rows()
        self.assertEqual((count, shown), (2, 2))
        self.assertIn("Rejectie", text)
        self.assertNotIn("Proefmotor", text)
        self.assertIn('<i class="ut-count">2</i>', text)

    def test_het_eerst_aan_de_beurt_komt_uit_dezelfde_lijst(self):
        self.seed_chances()
        text = self.client.get("/vandaag").text
        self.assertIn('<span class="kl-num">BTC short', text.split("Het eerst aan de beurt")[1])
        self.assertNotIn("ETH short", text.split("Het eerst aan de beurt")[1].split("</dl>")[0])

    def test_nav_badges_follow_the_same_validity(self):
        self.seed_chances()
        self.client.get("/vandaag")                                       # warmt de koerscache, die het menu leest
        text = self.client.get("/bewijs").text
        self.assertRegex(text, r'<span>Setups</span>\s*<i class="tab-badge">1</i>')        # alleen het geldige BTC-plan, niet verlopen of voorbij de stop

    def test_coin_page_shows_the_signal_a_notification_links_to_even_when_it_is_old(self):
        base = {"message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "trend", "pattern_name": "Trend-pullback",
                "price": 100.0, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None, "atr": None,
                "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Trend-pullback",
                "reason": "test", "stop_loss": 99.0, "take_profit": 102.0, "context_note": None, "is_practice": 0, "plain_explanation": None,
                "suggested_entry_low": None, "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None}
        ids = [repo.insert_signal(dict(base)) for _ in range(5)]
        plain = self.client.get("/coins/BTC").text
        self.assertNotIn(f'id="signal-{ids[0]}"', plain)               # de pagina toont maar de laatste paar
        linked = self.client.get(f"/coins/BTC?signal={ids[0]}").text
        self.assertIn(f'id="signal-{ids[0]}"', linked)
        from app import push_notify
        self.assertEqual(push_notify.signal_url("BTC", ids[0]), f"/kans/{ids[0]}")
        page = self.client.get(f"/kans/{ids[0]}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Wat er gebeurde", page.text)
        self.assertIn("Persbericht uitgegeven", page.text)
        self.assertEqual(self.client.get("/kans/999999").status_code, 404)
        self.assertIn("?tf=5m", page.text)                                  # tijdsknoppen onder de grafiek
        self.assertEqual(self.client.get(f"/kans/{ids[0]}?tf=zomaar").status_code, 200)

    def test_chain_page_is_public_verifies_and_kans_page_shows_the_fingerprint(self):
        sig_id = repo.insert_signal({"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": "rejectie", "price": 100.0, "stop_loss": 101.0,
                                     "take_profit": 98.0, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "Rejectie", "reason": "x"})
        from fastapi.testclient import TestClient
        from web.main import app
        anon = TestClient(app)                                              # zonder login
        page = anon.get("/keten")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Ketting klopt", page.text)
        rows = anon.get("/keten.json").json()
        self.assertEqual(rows[-1]["signal_id"], sig_id)
        self.assertIn(rows[-1]["hash"][:16], self.client.get(f"/kans/{sig_id}").text)

    def test_push_budget_form_saves_and_rejects_nonsense(self):
        me = repo.get_user_by_username("tester")["id"]
        self.client.post("/settings/meldingen", data={"budget": "6"}, follow_redirects=False)
        self.assertEqual(repo.get_user(me)["push_budget"], 6)
        self.client.post("/settings/meldingen", data={"budget": "veel"}, follow_redirects=False)
        self.assertIsNone(repo.get_user(me)["push_budget"])                    # ongeldig: terug naar de standaard
        self.client.post("/settings/meldingen", data={"budget": "0"}, follow_redirects=False)
        self.assertEqual(repo.get_user(me)["push_budget"], 0)                  # 0 zet het budget uit
        self.assertIn("Maximaal aantal pushes per dag", self.client.get("/account").text)

    def test_static_files_are_cached_by_version_and_pages_are_compressed(self):
        page = self.client.get("/vandaag", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(page.headers.get("content-encoding"), "gzip")
        import re
        href = re.search(r'href="(/static/style\.css\?v=\d+)"', page.text).group(1)         # versie = wijzigingstijd, dus een nieuw bestand krijgt een nieuwe URL
        self.assertIn("immutable", self.client.get(href).headers["cache-control"])
        self.assertNotIn("immutable", self.client.get("/static/style.css").headers["cache-control"])   # kale URL blijft kort in de cache

    def test_visits_count_page_views_not_api_polls_and_only_the_ceo_sees_them(self):
        repo.create_user("leerling2", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.get("/vandaag")
        self.client.get("/api/kansen")
        stats = repo.visit_stats(datetime.now(timezone.utc))
        me = repo.get_user_by_username("tester")["id"]
        self.assertEqual(stats[me]["active_days"], 1)
        self.assertGreaterEqual(stats[me]["views"], 1)
        before = stats[me]["views"]
        self.client.get("/api/kansen")
        self.assertEqual(repo.visit_stats(datetime.now(timezone.utc))[me]["views"], before)
        page = self.client.get("/ceo").text
        self.assertIn("Aanwezigheid", page)
        self.assertIn("leerling2", page)

    def test_ceo_page_shows_the_boss_and_students_and_marks_roles(self):
        repo.create_user("leerling1", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        page = self.client.get("/ceo").text
        self.assertIn("Chief Executive Officer", page)
        self.assertIn("tester", page)                                     # de eerst aangemaakte gebruiker is de CEO
        self.assertIn("leerling1", page)                                  # en de rest staat bij de leerlingen
        self.assertIn("De leerlingen", page)
        self.assertIn("Leerling van de maand", page)
        self.assertNotIn("Winrate", page)                                 # geen handelscijfers op de CEO-pagina
        self.assertIn("CEO tester", self.client.get("/vandaag").text)     # de CEO ziet zichzelf als CEO
        self.assertIn("Goede", self.client.get("/vandaag").text)

    def test_week_page_shows_totals_and_share_button(self):
        r = self.client.get("/week")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Jouw week", r.text)
        self.assertIn("Nog geen afgeronde kansen deze week", r.text)
        self.assertIn("data-share-chart", r.text)
        self.assertIn("share-btn", r.text)
        self.assertIn('href="/week?dagen=30"', r.text)                     # tijdsknoppen onder het kopje
        self.assertIn("laatste 30 dagen", self.client.get("/week?dagen=30").text)
        self.assertIn("laatste 7 dagen", self.client.get("/week?dagen=999").text)     # onbekende periode valt terug op een week

    def test_page_shows_script_scenario_liquidations_events_and_score(self):
        now = datetime.now(timezone.utc)
        repo.insert_market_script("BTC", "BTC test onder gisteren hoog.", "long", "m", [scenario_row()], 1,
                                  (now + timedelta(hours=10)).isoformat())
        repo.add_liquidations([("BTC", now.replace(second=0, microsecond=0).isoformat(), 3e6, 1e6, 5)])
        repo.insert_market_event(now.isoformat(), "Binance", "Binance will list SOL", "https://x/1", "SOL", "long", "hoog", "Binance lijst SOL.")
        r = self.client.get("/vandaag")
        self.assertEqual(r.status_code, 200)
        for text in ("BTC test onder gisteren hoog.", "5m-candle sluit boven 101", "Wacht op de voorwaarde", "Zet een limietorder op", "Wacht tot: 5m-candle sluit boven 101", "te gaan",
                     "4,0M", "Binance lijst SOL.", "1 long-scenario's", "Score: wat HesPulse zelf voorspelde",
                     "Break boven gisteren hoog."):
            self.assertIn(text, r.text, text)

    def test_copy_chips_render_for_a_scenario(self):
        repo.insert_market_script("BTC", "x", "long", "m", [scenario_row()], 1, (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        r = self.client.get("/vandaag")
        self.assertIn('data-chips-coin="BTC"', r.text)
        self.assertIn('data-copy="100.80"', r.text)

    def test_api_returns_prices_and_scenario_state(self):
        repo.insert_market_script("BTC", "x", "long", "m", [scenario_row()], 0, (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        data = self.client.get("/api/vandaag").json()
        self.assertEqual(data["prices"]["BTC"], 100.0)
        (sc,) = data["scenarios"].values()
        self.assertEqual(sc["state"], "waiting")
        self.assertAlmostEqual(sc["to_trigger_pct"], 1.0)

    def test_login_required_and_nav_and_landing_redirect(self):
        anon = TestClient(self.main.app)
        self.assertIn(anon.get("/vandaag", follow_redirects=False).status_code, (302, 303, 401))
        page = self.client.get("/vandaag").text
        self.assertIn('href="/vandaag"', page)
        self.assertIn(">Journaal<", page)
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/ceo")


    def test_public_landing_shows_live_vandaag_without_scenarios_and_manifest_opens_on_vandaag(self):
        now = datetime.now(timezone.utc)
        repo.insert_market_script("BTC", "Geheime samenvatting", "long", "m", [scenario_row()], 0, (now + timedelta(hours=10)).isoformat())
        anon = TestClient(self.main.app)
        page = anon.get("/").text
        self.assertIn("Marktbeeld", page)
        self.assertNotIn("Claude", page)                         # de werkwijze staat niet op de openbare pagina
        self.assertNotIn("markt-script", page)
        self.assertIn("vd-timeline", page)
        self.assertIn("1 long-scenario", page)
        self.assertNotIn("Geheime samenvatting", page)           # scenario's en duiding blijven achter het inloggen
        self.assertNotIn("Break boven gisteren hoog.", page)       # de reden bij een scenario blijft ook achter het inloggen
        self.assertNotIn("Wacht op de voorwaarde", page)
        self.assertEqual(anon.get("/static/manifest.json").json()["start_url"], "/ceo")
        self.assertEqual(self.client.get("/dashboard", follow_redirects=False).headers["location"], "/vandaag")


    def test_meldingen_page_groups_by_day_with_chip_and_keeps_line_breaks(self):
        uid = repo.get_user_by_username("tester")["id"]
        repo.create_notification(uid, "update", "Nieuw in HesPulse", "Regel een\nRegel twee", "/vandaag")
        r = self.client.get("/meldingen")
        self.assertEqual(r.status_code, 200)
        for text in ("Vandaag", "Nieuw in HesPulse", "nf-chip chip-new", "Regel een\nRegel twee", "alles gelezen (1)", "zojuist"):
            self.assertIn(text, r.text, text)


if __name__ == "__main__":
    unittest.main()
