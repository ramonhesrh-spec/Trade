import re
import unittest
from datetime import datetime, timedelta, timezone

from app import today

NOW = datetime(2026, 10, 6, 6, 40, tzinfo=timezone.utc)


def moment(hours, kind="funding", label="Funding-reset"):
    return {"at": NOW + timedelta(hours=hours), "kind": kind, "label": label}


class TimelineTest(unittest.TestCase):
    def test_now_marker_left_and_moments_ordered_by_time(self):
        svg = today.timeline_svg(NOW, [moment(1.3), moment(6.0, "vs_open", "Opening VS-beurs"), moment(30)])
        self.assertEqual(svg.count('class="vd-moment '), 2)                   # 30 uur ligt buiten de as
        xs = [float(x) for x in re.findall(r'<circle cx="([\d.]+)" cy="62" r="4.5"', svg)]
        self.assertEqual(xs, sorted(xs))
        self.assertIn('class="vd-now"', svg)

    def test_vs_open_shows_measured_note_and_funding_does_not(self):
        svg = today.timeline_svg(NOW, [moment(7, "vs_open", "Opening VS-beurs"), moment(3, "funding")])
        self.assertIn("beweegt 1,9x harder dan normaal", svg)
        self.assertNotIn("1,0x", svg)

    def test_labels_are_escaped_and_empty_agenda_is_fine(self):
        svg = today.timeline_svg(NOW, [moment(2, "macro", "<b>CPI</b>")])
        self.assertIn("&lt;b&gt;CPI", svg)
        self.assertNotIn("<b>", svg)
        self.assertIn("<svg", today.timeline_svg(NOW, []))


def scenario(**kw):
    s = {"id": 1, "coin": "BTC", "direction": "long", "trigger_type": "close_above", "trigger_level": 101.0, "entry": 100.8,
         "stop_loss": 99.8, "take_profit": 103.0, "reason": "Break", "state": "waiting",
         "expires_at": (NOW + timedelta(hours=9)).isoformat()}
    s.update(kw)
    return s


class ScenarioTest(unittest.TestCase):
    def test_numbers_and_distance(self):
        v = today.scenario_view(scenario(), 100.0, NOW)
        self.assertAlmostEqual(v["rr"], 2.2)
        self.assertAlmostEqual(v["to_trigger_pct"], 1.0)
        self.assertAlmostEqual(v["hours_left"], 9.0)
        self.assertEqual(v["trigger"], "5m-candle sluit boven 101")
        self.assertEqual((v["chart"]["entry"], v["chart"]["stop"], v["chart"]["take"], v["chart"]["price"]), (100.8, 99.8, 103.0, 100.0))

    def test_scenario_has_copyable_levels(self):
        view = today.scenario_view(scenario(), 100.0, NOW)
        self.assertEqual([c["value"] for c in view["levels"]], [100.8, 99.8, 103.0])

    def test_overdue_waiting_scenario_shows_as_expired_and_fired_has_no_distance(self):
        old = scenario(expires_at=(NOW - timedelta(hours=1)).isoformat())
        self.assertEqual(today.scenario_view(old, 100.0, NOW)["state"], "expired")
        fired = today.scenario_view(scenario(state="fired"), 100.0, NOW)
        self.assertIsNone(fired["to_trigger_pct"])

    def test_no_price_still_renders(self):
        self.assertIsNone(today.scenario_view(scenario(), None, NOW)["to_trigger_pct"])


class MoodAndLiquidationTest(unittest.TestCase):
    def test_mood_counts(self):
        m = today.mood([{"bias": "long"}, {"bias": "long"}, {"bias": "short"}, {"bias": "x"}])
        self.assertEqual((m["long"], m["short"], m["neutraal"], m["total"]), (2, 1, 1, 4))
        self.assertAlmostEqual(m["long_pct"], 50.0)
        self.assertEqual(today.mood([])["total"], 0)

    def test_mood_counts_waiting_scenarios_by_direction(self):
        m = today.mood([{"bias": "neutraal", "scenarios": [{"state": "waiting", "direction": "long"}, {"state": "fired", "direction": "short"}]},
                        {"bias": "neutraal", "scenarios": [{"state": "waiting", "direction": "short"}]}])
        self.assertEqual((m["wait_long"], m["wait_short"], m["neutraal"]), (1, 1, 2))
        self.assertEqual((m["wait_total"], m["wait_long_pct"]), (2, 50.0))

    def test_liquidation_rows_sorted_scaled_and_empty_coins_dropped(self):
        rows = today.liquidation_rows({
            "BTC": [{"long_usd": 3e6, "short_usd": 1e6}], "ETH": [{"long_usd": 0, "short_usd": 2e6}], "SOL": []})
        self.assertEqual([r["coin"] for r in rows], ["BTC", "ETH"])
        self.assertEqual(rows[0]["width_pct"], 100)
        self.assertAlmostEqual(rows[1]["width_pct"], 50.0)
        self.assertAlmostEqual(rows[0]["long_share"], 75.0)

    def test_money_format(self):
        self.assertEqual((today.money(41_200_000), today.money(380_000), today.money(512)), ("41,2M", "380K", "512"))


if __name__ == "__main__":
    unittest.main()


class AgendaTest(unittest.TestCase):
    def test_agenda_drops_unmeasured_noise_but_keeps_us_open_and_macro(self):
        kinds = [m["kind"] for m in today.agenda([moment(1, "funding"), moment(2, "opties_expiry"), moment(3, "vs_open"), moment(4, "macro")])]
        self.assertEqual(kinds, ["vs_open", "macro"])


class OpenChancesTest(unittest.TestCase):
    def card(self, dist="+1.50%", **kw):
        return {"coin": "BTC", "direction": "short", "steps": [{"dist": dist}], **kw}

    def smc(self, state="wacht", dist=-2.0, **kw):
        return {"kind": "setup", "coin": "SOL", "direction": "long", "distance_pct": dist, "state": state, "state_label": state, **kw}

    def sig(self, **kw):
        return {"id": 5, "coin": "ETH", "direction": "long", "trade_type": "trend", "stop_loss": 99.0, "take_profit": 105.0,
                "created_at": (NOW - timedelta(hours=1)).isoformat(), "auto_outcome": None, **kw}

    def test_sorted_by_distance_and_nearest_is_the_first_of_the_same_list(self):
        scripts = [{"coin": "DOGE", "scenarios": [{"state": "waiting", "direction": "short", "to_trigger_pct": 0.9, "hours_left": 5},
                                                   {"state": "fired", "direction": "long", "to_trigger_pct": 0.1, "hours_left": 5}]}]
        chances = today.open_chances([self.card()], scripts, [self.smc()], [], {}, NOW)
        self.assertEqual([(c["coin"], c["kind"]) for c in chances], [("DOGE", "scenario"), ("BTC", "structure"), ("SOL", "smc")])
        best = today.nearest_chance(chances)
        self.assertEqual((best["name"], best["dist"]), ("DOGE short", "+0.90%"))

    def test_invalid_things_do_not_count(self):
        scripts = [{"coin": "DOGE", "scenarios": [{"state": "waiting", "direction": "short", "to_trigger_pct": 0.9, "hours_left": 0.0}]}]
        smc = [self.smc(state=st) for st in ("ongeldig", "door_zone", "doel_geraakt")]
        signals = [self.sig(auto_outcome="stop_loss"), self.sig(created_at=(NOW - timedelta(hours=7)).isoformat()), self.sig(trade_type="swing"),
                   self.sig(stop_loss=99.0), self.sig(take_profit=105.0)]
        self.assertEqual(today.open_chances([], scripts, smc, signals[:3], {}, NOW), [])
        self.assertEqual(today.open_chances([], [], [], [signals[3]], {"ETH": 98.0}, NOW), [])        # voorbij de stop
        self.assertEqual(today.open_chances([], [], [], [signals[4]], {"ETH": 106.0}, NOW), [])       # voorbij het doel

    def test_a_chance_without_price_still_counts_and_nearest_is_dash_only_when_empty(self):
        chances = today.open_chances([self.card("-")], [], [], [self.sig()], {}, NOW)
        self.assertEqual(len(chances), 2)
        self.assertEqual(today.nearest_chance(chances)["name"], "BTC short")
        self.assertIsNone(today.nearest_chance([]))

    def test_structure_state_expiry_and_price(self):
        setup = {"direction": "short", "expires_at": (NOW + timedelta(hours=1)).isoformat()}
        plan = {"level": 100.0, "stop": 101.0, "targets": [98.0]}
        self.assertEqual(today.structure_state(setup, plan, 99.0, NOW), "wacht")
        self.assertEqual(today.structure_state(setup, plan, 100.0, NOW), "in_zone")
        self.assertEqual(today.structure_state(setup, plan, 102.0, NOW), "ongeldig")
        self.assertEqual(today.structure_state(setup, plan, 97.0, NOW), "doel_geraakt")
        self.assertIsNone(today.structure_state(setup, plan, None, NOW))
        self.assertEqual(today.structure_state(dict(setup, expires_at=(NOW - timedelta(minutes=1)).isoformat()), plan, 99.0, NOW), "verlopen")


class BudgetRingTest(unittest.TestCase):
    def test_default_budget_is_six(self):
        ring = today.budget_ring(3, None)
        self.assertEqual((ring["limit"], ring["offset"], ring["full"], ring["off"]), (6, 50.0, False, False))
        self.assertEqual(ring["label"], "3 van 6 meldingen in 24 uur")

    def test_full_and_over_budget_stays_a_full_ring(self):
        ring = today.budget_ring(8, 6)
        self.assertEqual((ring["offset"], ring["full"]), (0.0, True))

    def test_zero_switches_the_budget_off(self):
        ring = today.budget_ring(1, 0)
        self.assertTrue(ring["off"])
        self.assertEqual(ring["label"], "1 melding in 24 uur, geen budget")


class AgoTextTest(unittest.TestCase):
    def test_ago_text(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(today.ago_text(None, now), "-")
        self.assertEqual(today.ago_text("2026-01-01T11:59:30+00:00", now), "net nu")
        self.assertEqual(today.ago_text("2026-01-01T11:40:00+00:00", now), "20 min geleden")
        self.assertEqual(today.ago_text("2026-01-01T09:00:00+00:00", now), "3 uur geleden")
        self.assertEqual(today.ago_text("2025-12-30T12:00:00+00:00", now), "2 dgn geleden")
