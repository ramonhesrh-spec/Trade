"""Kansen V5: de tab Structuur tekent weer zijn eigen momentopname (setup_chart.setup_svg) voor een wachtend plan én een open trade, de andere
soorten houden de kaartgrafiek; boven de tabs staat het totaal en naast elke tabnaam het aantal wachtende kansen."""
import json
from datetime import datetime, timedelta, timezone

from unittest import mock

from app import repo
from web import main
from tests.test_web_focus import Base, signal


def section(html, key):
    return html.split(f'<section id="tab-{key}"')[1].split("</section>")[0]


def structure_setup(coin, state="waiting", level=99.0, stop=98.0, targets=(102.0, 104.0)):
    candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.5, 100.5] for i in range(20)]
    plan = {"level": level, "stop": stop, "risk_pct": 1.0, "targets": list(targets), "targets_r": [3.0, 5.0], "candles": candles}
    return repo.insert_structure_setup({
        "coin": coin, "direction": "long", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 99.0,
        "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "", "features": "{}", "state": state,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})


class StructureDrawingTests(Base):
    def setUp(self):
        super().setUp()
        self.waiting = structure_setup("SOL")
        self.trade = signal("ADA", "structuur", price=99.0, stop=98.0, take=102.0)
        sid = structure_setup("ADA", state="waiting")
        repo.set_structure_state(sid, "fired", self.trade)

    def test_waiting_plan_and_open_trade_show_the_structure_drawing(self):
        tab = section(self.client.get("/smc").text, "structuur")
        plan = tab.split(f'id="structuur-{self.waiting}"')[1].split("</article>")[0]
        self.assertIn('<svg class="sc"', plan)
        self.assertNotIn("data-levelchart", plan)
        trade = tab.split(f'id="radar-signal-{self.trade}"')[1].split("</article>")[0]
        self.assertIn('<svg class="sc"', trade)
        self.assertIn('data-chart-coin="ADA"', trade)                       # live.js schuift de koerslijn van deze tekening
        self.assertNotIn("data-levelchart", trade)

    def test_zone_radar_keeps_the_card_chart(self):
        tab = section(self.client.get("/smc").text, "zone_radar")
        self.assertIn("data-levelchart", tab)
        self.assertNotIn('<svg class="sc"', tab)


class CounterTests(Base):
    def test_total_line_and_tab_numbers(self):
        structure_setup("SOL")
        html = self.client.get("/smc").text
        # zone-radar BTC in de zone (Base), een wachtend Structuur-plan; de open SMC-trade telt als open
        self.assertIn('data-kansen-total', html)
        self.assertIn("2 kansen klaar · 1 in de zone · 1 open", html)
        tabs = html.split('class="ut-list"')[1].split("</div>")[0]
        self.assertRegex(tabs, r'Structuur<span class="ut-num"[^>]*>1</span>')
        self.assertRegex(tabs, r'Zone-radar<span class="ut-num"[^>]*>1</span><i class="ut-badge"[^>]*>1<span class="sr-only"> in de zone</span></i>')

    def test_empty_page_says_no_chances(self):
        from app import db
        with db.session() as conn:
            conn.execute("DELETE FROM zone_radar_setups")
            conn.execute("UPDATE signals SET auto_outcome = 'stop_loss'")
        html = self.client.get("/smc").text
        self.assertIn(">Geen kansen<", html)
        tabs = html.split('class="ut-list"')[1].split("</div>")[0]
        self.assertRegex(tabs, r'Structuur<span class="ut-num"[^>]*>0</span>')
        self.assertNotIn('class="ut-badge"', tabs)


class CardSvgTests(Base):
    def setUp(self):
        super().setUp()
        start = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp())
        rows = [[start + 3600 * i, 100.0, 101.0, 99.0, 100.3] for i in range(120)]

        async def fake(coin, tf):
            return rows
        p = mock.patch.object(main, "_cached_candles", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)
        self.zone_id = repo.list_zone_radar_setups()[0]["id"]

    def test_zone_radar_card_svg(self):
        r = self.client.get(f"/api/kaart_svg/zone:{self.zone_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<svg class="sc is-card"', r.text)
        self.assertIn("Aanbod 1u", r.text)
        self.assertIn("Doelzone 4u", r.text)

    def test_card_has_a_placeholder_that_loads_it(self):
        tab = section(self.client.get("/smc").text, "zone_radar")
        self.assertIn(f'data-kc-svg="/api/kaart_svg/zone:{self.zone_id}"', tab)
        self.assertNotIn("lc-bare", tab)                                          # geen generieke 15m-kaartgrafiek meer
        self.assertRegex(tab, r'data-levelchart=[^>]*hidden></div>')               # alleen nog verborgen, als bron voor "Groot"

    def test_unknown_or_foreign_keys_are_404(self):
        for key in ("zone:999", "setup:1", "structuur:1", "signal:999", "zone:abc"):
            self.assertEqual(self.client.get(f"/api/kaart_svg/{key}").status_code, 404, key)

    def test_open_zone_trade_draws_its_setup(self):
        sid = signal("BTC", "zone_radar", price=100.0, stop=102.0, take=96.0, direction="short")
        from app import db
        with db.session() as conn:
            conn.execute("UPDATE zone_radar_setups SET signal_id = ?, state = 'filled' WHERE id = ?", (sid, self.zone_id))
        r = self.client.get(f"/api/kaart_svg/signal:{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Aanbod 1u", r.text)


class DuplicateWebTests(Base):
    def test_two_identical_trades_show_once_with_a_line_in_the_sheet(self):
        a = signal("ETH", "zone_radar", price=2357.5, stop=2380.0, take=2300.0, direction="short")
        b = signal("ETH", "zone_radar", price=2357.5, stop=2390.0, take=2300.0, direction="short")
        html = self.client.get("/smc").text
        self.assertIn(f'id="radar-signal-{a}"', html)                           # de oudste blijft
        self.assertNotIn(f'id="radar-signal-{b}"', html)
        self.assertIn("Nog 1 vergelijkbaar signaal", html)
        self.assertEqual(repo.get_signal(b)["coin"], "ETH")                     # het signaal zelf blijft bestaan
