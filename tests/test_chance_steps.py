import unittest
from types import SimpleNamespace

from app import chance_steps as cs


class ChanceStepsTests(unittest.TestCase):
    def test_structure_steps_carry_what_the_browser_needs_to_follow_the_price_live(self):
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0}
        first = cs.structure_steps(plan, [(98.0, 2.0), (97.0, 3.0)], 99.0, "short", "BTC")[0]
        self.assertEqual((first["live_coin"], first["live_level"], first["live_mode"]), ("BTC", 100.0, "lp"))
        self.assertEqual(first["dist"], "+1.01%")                          # (100 - 99) / 99
        self.assertNotIn("live_coin", cs.structure_steps(plan, [(98.0, 2.0)], 99.0, "short")[0])   # zonder coin geen live variant

    def test_smc_distance_uses_the_radar_convention_per_direction(self):
        long_plan = SimpleNamespace(limit=100.0, stop=99.5, take=102.0, risk_pct=0.5, rr=4.0, direction="long")
        short_plan = SimpleNamespace(limit=100.0, stop=100.5, take=98.0, risk_pct=0.5, rr=4.0, direction="short")
        self.assertEqual(cs.smc_steps(long_plan, 99.0, 100.0, 101.0, 1.0, "SOL")[0]["live_mode"], "pl")
        self.assertEqual(cs.smc_steps(short_plan, 100.0, 101.0, 99.0, 1.0, "SOL")[0]["live_mode"], "ll")

    def test_script_steps_are_live_only_while_waiting(self):
        sc = {"state": "waiting", "trigger": "5m-candle sluit boven 101", "entry": 100.8, "stop": 99.8, "take": 103.0, "risk_pct": 1.0, "rr": 2.2,
              "to_trigger_pct": 1.5, "coin": "ETH", "trigger_level": 101.0}
        self.assertEqual(cs.script_steps(sc)[0]["live_level"], 101.0)
        self.assertNotIn("live_coin", cs.script_steps({**sc, "state": "fired"})[0])


if __name__ == "__main__":
    unittest.main()
