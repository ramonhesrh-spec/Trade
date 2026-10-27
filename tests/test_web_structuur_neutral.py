"""Structuur zonder oordeel naar buiten: elke gespotte kans heet Structuur, op geen scherm voor gebruikers staat A, B of C of sterk, redelijk of
zwak. Bewijs houdt structuur en structuur_c als twee regels, zodat niets verdwijnt."""
import json
from datetime import datetime, timedelta, timezone

from app import repo
from tests.test_web_focus import Base, signal

WORDS = ("Zwak", "Sterk", "Redelijk", "Structuur C", "oordeel C", "Oordeel van de CEO", "setup-grade", "A of B", "De CEO keurt")


class NeutralStructureTests(Base):
    def setUp(self):
        super().setUp()
        candles = [[(datetime(2026, 3, 2, tzinfo=timezone.utc) + timedelta(minutes=30 * i)).isoformat(), 100.0, 101.0, 99.0, 100.5] for i in range(20)]
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0], "targets_r": [2.0, 3.0], "candles": candles}
        for coin, grade in (("SOL", "C"), ("ADA", "A")):
            repo.insert_structure_setup({
                "coin": coin, "direction": "short", "kind": "RANGE", "break_at": candles[10][0], "p1_at": candles[2][0], "line_a": 100.0,
                "line_slope": 0.0, "atr": 0.5, "grade": grade, "reason": "Rommelige structuur.", "features": "{}", "state": "waiting",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        self.c_signal = signal("SOL", "structuur_c")
        from app import db
        with db.session() as conn:                    # een ouder signaal, nog met het oordeel als kenmerk
            conn.execute("UPDATE signals SET reason = ?, pass_pct = 50, confidence = 'Structuur C' WHERE id = ?",
                         ("✓ Volume van de breuk minstens 1,5x gemiddeld | ✗ De CEO keurt goed (A of B)", self.c_signal))

    def test_no_grade_on_any_user_screen(self):
        for url in ("/structuur", "/smc", "/vandaag", f"/kans/{self.c_signal}", "/signalen", "/signalen?alles=1", "/uitleg", "/meldingen",
                    "/nu/order/structuur:1"):
            html = self.client.get(url).text
            for word in WORDS:
                self.assertNotIn(word, html, f"{word} op {url}")

    def test_a_filled_c_chance_is_called_structuur(self):
        self.assertIn("Structuur gevuld · Open, gemeld", self.client.get("/vandaag").text)
        self.assertIn("Structuur", self.client.get(f"/kans/{self.c_signal}").text)

    def test_bewijs_keeps_both_internal_types(self):
        for t, o in (("structuur", "take_profit"), ("structuur_c", "stop_loss")):
            signal("BTC", t, o)
        html = self.client.get("/bewijs").text
        self.assertIn("Structuur-breuk", html)
        self.assertIn("Structuur oordeel C", html)
