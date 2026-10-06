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
        self.assertIn("<svg", v["ladder"])

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
