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


class NowLineTest(unittest.TestCase):
    def test_waiting_names_the_level_and_the_full_order(self):
        self.assertEqual(cs.now_line("wacht", "short", 2455.0, 2484.0, 2392.0),
                         "Wacht tot de koers 2455.00 bereikt. Zet dan een limit short op 2455.00, stop 2484.00, doel 2392.00.")
        # Zonder koers is er nog geen stand: dan is wachten het enige wat je kunt doen.
        self.assertEqual(cs.now_line(None, "short", 2455.0, 2484.0, 2392.0), cs.now_line("wacht", "short", 2455.0, 2484.0, 2392.0))

    def test_open_trade_only_names_stop_and_target(self):
        self.assertEqual(cs.now_line("open", "short", 2455.0, 2484.0, 2392.0), "Trade loopt. Stop 2484.00, doel 2392.00.")
        self.assertEqual(cs.now_line("open", "long", 100.0, 99.0), "Trade loopt. Stop 99.0000.")       # meelopende stop: geen doel

    def test_every_state_gets_its_own_sentence(self):
        states = ("wacht", "in_zone", "door_zone", "ongeldig", "doel_geraakt", "open", "fired", "vervallen")
        lines = {s: cs.now_line(s, "long", 100.0, 99.0, 103.0) for s in states}
        self.assertEqual(len(set(lines.values())), len(states))
        self.assertIn("waarschijnlijk gevuld", lines["in_zone"])
        self.assertIn("Haal je limit op 100.00 weg", lines["ongeldig"])
        self.assertTrue(lines["fired"].startswith("De voorwaarde is geraakt. Zet nu een limit long op 100.00"))

    def test_a_scenario_waits_for_its_condition(self):
        self.assertTrue(cs.now_line("wacht", "long", 100.8, 99.8, 103.0, wait_for="een 5m-candle sluit boven 101")
                        .startswith("Wacht tot een 5m-candle sluit boven 101. Zet dan een limit long op 100.80"))


class LevelChipsTest(unittest.TestCase):
    def test_three_chips_in_the_same_notation_as_the_steps(self):
        chips = cs.level_chips(100.0, 97.0, 0.09571)
        self.assertEqual([c["key"] for c in chips], ["entry", "stop", "take"])
        self.assertEqual([c["label"] for c in chips], ["Instap", "Stop", "Doel"])
        self.assertEqual([c["text"] for c in chips], ["100.00", "97.0000", "0.09571"])
        self.assertEqual(chips[2]["value"], 0.09571)

    def test_tiny_prices_stay_fixed_point(self):
        self.assertEqual(cs.fmt(0.0000123), "0.0000123")
        self.assertEqual(cs.fmt(0.0957), "0.0957")
        self.assertNotIn("e", cs.fmt(0.00000123))


if __name__ == "__main__":
    unittest.main()



class RangeSweepStepsTest(unittest.TestCase):
    ROW = {"direction": "short", "family": "zone", "legs": "[[0.4, 0.2045], [0.6, 0.199]]", "stop": 0.2052, "range_high": 0.2045, "range_low": 0.17, "range_tf": "2h"}

    def test_three_steps_and_no_target(self):
        steps = cs.range_sweep_steps(self.ROW, 0.1985, "ARB")
        self.assertEqual(len(steps), 3)
        self.assertIn("zone", steps[0]["title"])
        self.assertIn("40% op 0.2045", steps[1]["title"])
        self.assertIn("60% op 0.199", steps[1]["title"])
        self.assertIn("doel kies je zelf", steps[2]["title"])
        self.assertIn("Overkant 0.17", steps[2]["sub"])
        self.assertNotIn("rr", steps[2])

    def test_first_step_follows_the_nearest_limit_live(self):
        first = cs.range_sweep_steps(self.ROW, 0.1985, "ARB")[0]
        self.assertEqual((first["live_coin"], first["live_level"], first["live_mode"]), ("ARB", 0.199, "lp"))
        self.assertEqual(first["dist"], "+0.25%")                          # (0.199 - 0.1985) / 0.1985, the nearest limit for a short
        self.assertNotIn("live_coin", cs.range_sweep_steps(self.ROW, 0.1985, "")[0])
        self.assertEqual(cs.range_sweep_steps(self.ROW, None, "ARB")[0]["dist"], "-")

    def test_sweep_family_speaks_of_the_order_block_and_one_leg_is_one_order(self):
        row = dict(self.ROW, family="sweep", legs="[[1.0, 0.199]]")
        steps = cs.range_sweep_steps(row, 0.1985, "ARB")
        self.assertIn("order block", steps[0]["title"])
        self.assertEqual(steps[1]["title"], "Zet een limietorder op 0.199")

    def test_a_long_waits_on_the_highest_limit_and_names_the_high_as_far_edge(self):
        row = dict(self.ROW, direction="long", legs="[[0.4, 0.172], [0.6, 0.176]]", stop=0.1705)
        steps = cs.range_sweep_steps(row, 0.18, "ARB")
        self.assertIn("0.176", steps[0]["title"])
        self.assertIn("Overkant 0.2045", steps[2]["sub"])

    def test_chips(self):
        chips = cs.range_chips([(0.4, 0.2045), (0.6, 0.199)], 0.2052, 0.18725, 0.17)
        self.assertEqual([c["label"] for c in chips], ["Limiet 40%", "Limiet 60%", "Stop", "Midden (ref.)", "Overkant (ref.)"])
        self.assertEqual([c["text"] for c in chips], ["0.2045", "0.199", "0.2052", "0.18725", "0.17"])

    def test_one_leg_gives_a_plain_limit_chip(self):
        self.assertEqual(cs.range_chips([(1.0, 100.0)], 102.0, 95.0, 90.0)[0]["label"], "Limiet")
