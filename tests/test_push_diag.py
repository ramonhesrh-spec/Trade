import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("push_diag", Path(__file__).resolve().parent.parent / "scripts" / "push_diag.py")
pd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pd)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


class PushDiagTest(unittest.TestCase):
    def test_pause_wins(self):
        u = {"push_paused_until": (NOW + timedelta(minutes=30)).isoformat(), "push_budget": None}
        ok, why = pd.verdict(u, 1, [], "ETH", "long", True, NOW)
        self.assertFalse(ok)
        self.assertIn("pauze", why)

    def test_budget_full(self):
        recent = [{"coin": f"C{i}", "direction": "long", "at": (NOW - timedelta(hours=i)).isoformat()} for i in range(15)]
        ok, why = pd.verdict({"push_budget": None}, 1, recent, "ETH", "long", True, NOW)
        self.assertFalse(ok)
        self.assertIn("Dagbudget", why)

    def test_no_subscription_and_ok(self):
        self.assertFalse(pd.verdict({}, 0, [], "ETH", "long", True, NOW)[0])
        self.assertTrue(pd.verdict({}, 1, [], "ETH", "long", True, NOW)[0])

    def test_age_text(self):
        self.assertEqual(pd.age_text((NOW - timedelta(minutes=5)).isoformat(), NOW), "5 min geleden")
        self.assertEqual(pd.age_text(None, NOW), "onbekend")


if __name__ == "__main__":
    unittest.main()
