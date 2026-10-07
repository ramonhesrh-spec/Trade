import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security


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
        self.assertIn("Laatste 24 uur: 1 breuk gezien, 1 goedgekeurd", r.text)
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

    def test_tabbar_filters_and_empty_state_invite_the_user(self):
        text = self.client.get("/vandaag").text
        self.assertIn('class="tabbar"', text)                              # onderbalk met tabs voor de telefoon
        self.assertIn("quick-actions", text)
        self.assertIn("Geen plan klaar", self.client.get("/structuur").text)   # lege staat met uitleg en een knop
        self.assertIn("Alleen A en B", self.client.get("/structuur?kant=short").text)

    def test_grade_c_card_is_muted_and_shows_claudes_doubt_on_top(self):
        import json
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        repo.insert_structure_setup({
            "coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "C", "reason": "Te weinig ruimte.", "features": "{}", "state": "waiting",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        text = self.client.get("/structuur").text
        self.assertIn("is-weak", text)
        self.assertIn("De CEO twijfelt", text)
        self.assertEqual(text.count("Te weinig ruimte."), 1)               # de reden staat één keer, bovenaan

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
        signal = {"message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "trend", "pattern_name": "Trend-pullback",
                  "price": 100.0, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None, "atr": None,
                  "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Trend-pullback",
                  "reason": "test", "stop_loss": 99.0, "take_profit": 102.0, "context_note": None, "is_practice": 0, "plain_explanation": None,
                  "suggested_entry_low": None, "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None}
        repo.insert_signal(signal)
        text = self.client.get("/vandaag").text
        self.assertIn("1 Trend, laatste 6 uur", text)
        self.assertNotIn("Er staat niets open", text)
        self.assertNotIn("jaar candles", text)

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
        self.assertIn("Vandaag, live", page)
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
