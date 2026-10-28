"""scripts/structuur_check.py en zijn zuivere telling (app/structure_report.py): per dag ontstaan, gemeld, gevuld en de uitkomst; de hartslag;
coins met de meeste en zonder plannen; of de dagcap geraakt werd. Alleen-lezen."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import structure_report as sr

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


def row(coin, state, hours_ago, outcome=None, signal_id=None):
    return {"coin": coin, "direction": "long", "state": state, "created_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "signal_id": signal_id, "auto_outcome": outcome}


ROWS = [row("BTC", "geen_plan", 1), row("BTC", "waiting", 2), row("ETH", "fired", 3, "take_profit", 7), row("ETH", "fired", 4, None, 8),
        row("SOL", "niet_gemeld", 5), row("SOL", "expired", 30), row("ADA", "fired", 31, "stop_loss", 9), row("BTC", "oordeel", 2)]


class DailyTests(unittest.TestCase):
    def test_per_day_counts(self):
        days = sr.daily(ROWS, NOW, days=3)
        self.assertEqual([d["date"] for d in days], ["2026-10-28", "2026-10-27", "2026-10-26"])
        today = days[0]
        self.assertEqual((today["breuken"], today["plannen"], today["gemeld"], today["gevuld"]), (6, 5, 3, 2))
        self.assertEqual((today["doel"], today["stop"], today["open"], today["niet_gemeld"], today["vast"]), (1, 0, 1, 1, 1))
        yesterday = days[1]
        self.assertEqual((yesterday["plannen"], yesterday["gemeld"], yesterday["gevuld"], yesterday["stop"]), (2, 2, 1, 1))
        self.assertEqual(days[2]["breuken"], 0)

    def test_cap_is_hit_when_a_chance_was_held(self):
        self.assertTrue(sr.daily(ROWS, NOW, days=1)[0]["cap_hit"])
        self.assertFalse(sr.daily([row("BTC", "waiting", 1)], NOW, days=1)[0]["cap_hit"])


class CoinTests(unittest.TestCase):
    def test_most_and_none(self):
        most, none = sr.coin_counts(ROWS, ["BTC", "ETH", "SOL", "ADA", "XRP"], NOW, days=1)
        self.assertEqual(most[:3], [("BTC", 2), ("ETH", 2), ("SOL", 1)])      # meeste eerst, bij gelijk op naam
        self.assertEqual(none, ["ADA", "XRP"])                    # ADA had alleen een plan van 31 uur geleden


class BeatTests(unittest.TestCase):
    def test_full_and_partial(self):
        b = sr.beat_view({"at": (NOW - timedelta(minutes=4)).isoformat(), "detail": "33 van 35 coins gecontroleerd in 41 s; mislukt: PEPE, WIF"}, 35, NOW)
        self.assertEqual((b["minutes"], b["checked"], b["total"], b["all"]), (4, 33, 35, False))
        old = sr.beat_view({"at": NOW.isoformat(), "detail": "35 coins gecontroleerd"}, 35, NOW)
        self.assertTrue(old["all"])

    def test_off_and_never(self):
        self.assertTrue(sr.beat_view({"at": NOW.isoformat(), "detail": "uit door focus"}, 35, NOW)["off"])
        self.assertIsNone(sr.beat_view(None, 35, NOW)["minutes"])


class ScriptTests(unittest.TestCase):
    def test_runs_read_only_on_a_scratch_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.db")
            env = {**os.environ, "DATABASE_PATH": path}
            seed = (
                "from app import db, repo; import json; from datetime import datetime, timedelta, timezone; db.init_db();"
                "repo.add_coin_if_new('BTC', 'crypto');"
                "n = datetime.now(timezone.utc);"
                "repo.insert_structure_setup({'coin': 'BTC', 'direction': 'long', 'kind': 'RANGE', 'break_at': n.isoformat(), 'p1_at': n.isoformat(),"
                "'line_a': 1.0, 'line_slope': 0.0, 'atr': 0.1, 'grade': None, 'reason': '', 'features': '{}', 'state': 'waiting',"
                "'expires_at': (n + timedelta(hours=3)).isoformat(), 'plan': json.dumps({'level': 1.0})});"
                "repo.beat('structuur', '1 van 35 coins gecontroleerd in 3 s')")
            subprocess.run([sys.executable, "-c", seed], cwd=ROOT, env=env, check=True)
            before = os.path.getsize(path)
            out = subprocess.run([sys.executable, "scripts/structuur_check.py"], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
            self.assertIn("Structuur, laatste 10 dagen", out)
            self.assertIn("1 van 35 coins", out)
            self.assertIn("niet alle FIXED_COINS", out)
            self.assertIn("Dagcap", out)
            self.assertIn("Zonder enig plan", out)
            self.assertEqual(os.path.getsize(path), before)


if __name__ == "__main__":
    unittest.main()
