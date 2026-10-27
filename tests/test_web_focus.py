"""Focus in de weergave: Plannen, Nu, de tellers en Vandaag tonen voor nieuwe en wachtende kansen alleen focus-soorten; een open trade van een
uitgezette soort blijft staan onder zijn eigen label tot hij sluit. Bewijs zet de focus-soorten bovenaan en de rest onder één kopje met hun
eindcijfers, voor de CEO en voor een leerling hetzelfde."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from tests.test_web_nu import zone
from tests.test_web_vandaag import scenario_row
from web import main


def signal(coin, trade_type, outcome=None, price=100.0, stop=99.0, take=102.0, direction="long"):
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss, take_profit,
               trade_type, auto_outcome, auto_outcome_at, created_at) VALUES (NULL, ?, ?, 'x', 'hoog', 1, ?, ?, ?, ?, ?, ?, ?)""",
            (coin, direction, price, stop, take, trade_type, outcome, db.now_iso() if outcome else None, db.now_iso()))
        return cur.lastrowid


def smc_setup(coin, low, high):
    with db.session() as conn:
        conn.execute(
            """INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
               created_at, updated_at) VALUES (?, 'long', ?, ?, ?, ?, ?, 1.0, ?, ?)""",
            (coin, low, high, high + 1, low - 1, high + 10, db.now_iso(), db.now_iso()))


class Base(unittest.TestCase):
    focus_on = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for p in (mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "f.db")),
                  mock.patch.object(config, "ENGINE_FOCUS", self.focus_on),
                  mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init_db()
        main._price_cache.clear()
        main._price_fetched_at.clear()
        main._ceo_cache.update(at=0.0)
        main._proof_cache.update(at=0.0)
        self.client = TestClient(main.app)
        self.ceo_id = repo.create_user("ceo", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(self.ceo_id))
        smc_setup("XRP", 99.5, 100.5)                                   # SMC in de zone: koers 100
        zone("BTC", "short", 100.0, 101.0, 102.0, 96.0, "1h:bear:a")    # zone-radar in de zone
        self.smc_open = signal("ETH", "smc")                             # open SMC-trade van voor de focus

    def as_student(self):
        sid = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(sid))
        main._ceo_cache.update(at=0.0)


class FocusOnTests(Base):
    def test_radar_shows_no_new_smc_plan_but_keeps_the_open_smc_trade(self):
        html = self.client.get("/smc").text
        self.assertNotIn('id="radar-setup-', html)                    # de coinlijst in het menu noemt XRP wel; een kaart niet
        self.assertIn('id="radar-zone-', html)
        self.assertIn(f'id="radar-signal-{self.smc_open}"', html)

    def test_nu_takes_the_zone_radar_plan_never_the_smc_plan(self):
        html = self.client.get("/vandaag").text
        sec = html[html.index('<section class="nu'):html.index("</section>", html.index('<section class="nu'))]
        self.assertIn('class="nu-coin">BTC short<', sec)
        self.assertNotIn("XRP", sec)
        self.assertNotIn("Ook in zone", sec)                            # het SMC-plan staat ook in de zone, maar telt niet

    def test_counters_count_only_focus_plans(self):
        self.client.get("/smc")                                         # vult de koerscache die de tellers lezen
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 1)
        nav = main._nav_context(mock.Mock(cookies={}))
        self.assertEqual(nav["nav_counts"]["in_zone"], 1)
        self.assertEqual(nav["nav_counts"]["radar"], 1)

    def test_vandaag_has_no_waiting_script_scenario_but_lists_an_open_script_trade(self):
        repo.insert_market_script("SOL", "Script van voor de focus", "long", "m", [scenario_row()], 0,
                                  (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat())
        signal("SOL", "script")
        html = self.client.get("/vandaag").text
        self.assertNotIn("Wacht op de voorwaarde", html)
        self.assertNotIn("Script van voor de focus", html)
        self.assertNotIn("Stemming van het markt-script", html)
        self.assertIn("Markt-script · Open, gemeld", html)

    def test_bewijs_puts_focus_first_and_the_rest_under_one_heading(self):
        for outcome in ("take_profit", "stop_loss"):
            signal("BTC", "zone_radar", outcome)
        for outcome in ("take_profit", "stop_loss", "stop_loss"):
            signal("BTC", "patroon", outcome)
        html = self.client.get("/bewijs").text
        self.assertIn("Uitgezet, ter verbetering", html)
        self.assertIn("melden niets nieuws", html)
        self.assertLess(html.index("Zone-radar (ongetest)"), html.index("Uitgezet, ter verbetering"))
        off = html[html.index("Uitgezet, ter verbetering"):]
        self.assertIn("Chart-patroon", off)
        self.assertRegex(off, r'Chart-patroon.*?<td[^>]*>3</td><td[^>]*>1</td><td[^>]*>2</td><td class="neg">-0,18R</td>')    # 2R en twee keer -1R, min 0,06R kosten per trade
        self.assertIn("SMC liquidity sweep", off)           # alleen open: telt 0 afgerond, maar verdwijnt niet

    def test_a_student_sees_the_same_split(self):
        signal("BTC", "patroon", "stop_loss")
        self.as_student()
        html = self.client.get("/bewijs").text
        self.assertIn("Uitgezet, ter verbetering", html)
        self.assertIn("Chart-patroon", html[html.index("Uitgezet, ter verbetering"):])
        self.assertNotIn('id="radar-setup-', self.client.get("/smc").text)

    def test_handleiding_names_what_is_active(self):
        html = self.client.get("/uitleg").text
        self.assertIn("tijdelijk uit", html)
        self.assertIn("Zone-radar", html)


class FocusOffTests(Base):
    focus_on = False

    def test_old_radar_shows_the_smc_plan_again(self):
        self.assertIn('id="radar-setup-', self.client.get("/smc").text)

    def test_old_bewijs_has_no_off_section(self):
        signal("BTC", "patroon", "stop_loss")
        self.assertNotIn("Uitgezet, ter verbetering", self.client.get("/bewijs").text)


if __name__ == "__main__":
    unittest.main()
