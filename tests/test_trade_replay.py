"""De replay van een afgeronde trade (app/trade_replay.py): venster, momenten uit echte tijdstempels en R alleen na de vulling."""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import trade_replay as tr

TZ = ZoneInfo("Europe/Amsterdam")
FILL = datetime(2026, 10, 25, 20, 40, tzinfo=timezone.utc)
CLOSE = FILL + timedelta(minutes=60)
SIGNAL = {"id": 5, "coin": "BTC", "direction": "short", "price": 100.0, "stop_loss": 101.0, "take_profit": 98.0,
          "created_at": FILL.isoformat(), "auto_outcome": "take_profit", "auto_outcome_at": CLOSE.isoformat(), "r_override": None}


def candles(start, n, step=300, closes=None):
    """[unix_s, open, high, low, close]; closes per candle, anders vlak op 100."""
    out = []
    for i in range(n):
        c = closes[i] if closes else 100.0
        out.append([int(start.timestamp()) + i * step, c, c + 0.1, c - 0.1, c])
    return out


class WindowTests(unittest.TestCase):
    def test_een_uur_voor_de_vulling_tot_de_sluiting_op_5m(self):
        start, end, tf = tr.window(FILL.isoformat(), CLOSE.isoformat())
        self.assertEqual((start, tf), (FILL - timedelta(hours=1), "5m"))
        self.assertGreaterEqual(end, CLOSE)

    def test_een_lange_trade_valt_terug_op_een_grovere_candle(self):
        self.assertEqual(tr.window(FILL.isoformat(), (FILL + timedelta(days=3)).isoformat())[2], "15m")
        self.assertEqual(tr.window(FILL.isoformat(), (FILL + timedelta(days=12)).isoformat())[2], "1h")

    def test_aantal_candles_om_op_te_halen(self):
        start, end, tf = tr.window(FILL.isoformat(), CLOSE.isoformat())
        self.assertEqual(tr.candle_count(start, end, tf), 25)          # 2 uur van 5 minuten, plus de sluitcandle


class MomentTests(unittest.TestCase):
    def test_momenten_uit_echte_tijden_in_volgorde(self):
        plan = {"created_at": (FILL - timedelta(hours=3)).isoformat(), "zone_at": (FILL - timedelta(minutes=10)).isoformat()}
        run = {"opened_at": (FILL - timedelta(minutes=9)).isoformat(), "done_at": (FILL - timedelta(minutes=8)).isoformat()}
        ms = tr.moments(SIGNAL, plan, run)
        self.assertEqual([m["key"] for m in ms], ["plan", "zone", "order", "filled", "target"])
        self.assertEqual([m["label"] for m in ms], ["Plan actief", "In zone", "Order gezet", "Gevuld", "Doel geraakt"])

    def test_zonder_plan_en_checklist_alleen_vulling_en_uitkomst(self):
        ms = tr.moments({**SIGNAL, "auto_outcome": "stop_loss"}, None, None)
        self.assertEqual([m["label"] for m in ms], ["Gevuld", "Stop geraakt"])

    def test_in_zone_gelijk_aan_de_vulling_staat_er_een_keer(self):
        ms = tr.moments(SIGNAL, {"created_at": (FILL - timedelta(hours=3)).isoformat(), "zone_at": FILL.isoformat()}, None)
        self.assertEqual([m["key"] for m in ms], ["plan", "filled", "target"])


class FramesTests(unittest.TestCase):
    def setUp(self):
        start = FILL - timedelta(hours=1)
        closes = [100.0] * 12 + [100.0, 100.5, 99.5, 99.0] + [98.5] * 9          # 25 candles van 5 minuten
        self.rows = candles(start, 25, closes=closes)
        self.view = tr.build(self.rows, SIGNAL, tr.moments(SIGNAL, None, None), "5m", TZ)

    def test_voor_de_vulling_niet_gevuld(self):
        f = self.view["frames"][0]
        self.assertEqual((f["r_label"], f["r_text"]), ("Niet gevuld", "—"))

    def test_na_de_vulling_r_uit_de_candlesluiting(self):
        f = self.view["frames"][13]                                       # candle 20:45, slot 100,5 bij een short met risico 1
        self.assertEqual((f["r_label"], f["r_text"]), ("Open", "−0,5 R"))
        self.assertEqual(self.view["frames"][15]["r_text"], "+1,0 R")

    def test_vanaf_de_uitkomst_het_gemeten_resultaat(self):
        last = self.view["frames"][-1]
        self.assertEqual((last["r_label"], last["r_text"]), ("Resultaat", "+2,0 R"))
        self.assertEqual(self.view["frames"][24]["r_text"], "+2,0 R")

    def test_momenten_staan_op_hun_candle(self):
        idx = {m["key"]: m["index"] for m in self.view["moments"]}
        self.assertEqual(idx, {"filled": 12, "target": 24})
        self.assertEqual(self.view["moments"][0]["time"], "21:40")
        self.assertEqual(self.view["frames"][12]["step"], "Moment 1 van 2")
        self.assertIn("Gevuld op 100,00", self.view["frames"][12]["event"])
        self.assertEqual(self.view["frames"][5]["event"], "Voor de vulling. Prijs nog niet op de limiet.")

    def test_een_moment_buiten_het_venster_staat_op_de_eerste_candle(self):
        plan = {"created_at": (FILL - timedelta(hours=6)).isoformat(), "zone_at": None}
        view = tr.build(self.rows, SIGNAL, tr.moments(SIGNAL, plan, None), "5m", TZ)
        self.assertEqual(view["moments"][0]["index"], 0)
        self.assertEqual(view["moments"][0]["time"], "15:40")

    def test_niveaus_en_svg_alleen_stop_en_doel_gekleurd(self):
        self.assertEqual([l["label"] for l in self.view["levels"]], ["Stop", "Instap", "Doel"])
        svg = self.view["svg"]
        self.assertIn('class="rp-candle', svg)
        self.assertIn('class="rp-lvl is-loss"', svg)
        self.assertIn('class="rp-lvl is-win"', svg)
        self.assertEqual(svg.count('class="rp-candle'), 25)
        self.assertIn('class="rp-cursor"', svg)

    def test_geen_candles_geen_replay(self):
        self.assertIsNone(tr.build([], SIGNAL, [], "5m", TZ))


if __name__ == "__main__":
    unittest.main()
