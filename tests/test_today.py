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


class RangeSweepTodayTest(unittest.TestCase):
    ROW = {"direction": "short", "family": "zone", "legs": "[[0.4, 101.0], [0.6, 101.5]]", "stop": 103.0, "range_high": 102.0, "range_low": 90.0,
           "expires_at": "2026-10-16T18:00:00+00:00", "variant": "RZ_2H", "stop_name": "zone_05"}
    AT = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)

    def test_range_sweep_card_counts_as_open_chance(self):
        card = {"id": 3, "coin": "ARB", "direction": "short", "distance_pct": 0.12, "family": "zone"}
        items = today.open_chances([], [], [], [], {}, datetime(2026, 10, 16, tzinfo=timezone.utc), range_cards=[card])
        self.assertEqual([(i["kind"], i["soort"], i["url"]) for i in items], [("range_sweep", "Zone-retest", "/structuur#range-sweep-3")])

    def test_sweep_family_is_named_range_sweep_and_sorting_uses_the_distance(self):
        near = {"id": 1, "coin": "ARB", "direction": "short", "distance_pct": 0.1, "family": "sweep"}
        far = {"id": 2, "coin": "OP", "direction": "long", "distance_pct": -2.5, "family": "zone"}
        items = today.open_chances([], [], [], [], {}, self.AT, range_cards=[far, near])
        self.assertEqual([(i["coin"], i["soort"], i["dist_text"]) for i in items], [("ARB", "Range sweep", "+0.10%"), ("OP", "Zone-retest", "-2.50%")])

    def test_filled_range_sweep_without_target_stays_open_for_six_hours(self):
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        sig = {"id": 9, "coin": "ARB", "direction": "short", "trade_type": "range_sweep", "auto_outcome": None, "created_at": "2026-10-16T10:00:00+00:00",
               "stop_loss": 0.2052, "take_profit": None}
        self.assertEqual(today.open_chances([], [], [], [sig], {"ARB": 0.199}, now)[0]["soort"], "Range sweep gevuld")
        old = dict(sig, created_at="2026-10-16T05:00:00+00:00")
        self.assertEqual(today.open_chances([], [], [], [old], {"ARB": 0.199}, now), [])
        self.assertEqual(today.open_chances([], [], [], [dict(sig, auto_outcome="stop_loss")], {"ARB": 0.199}, now), [])

    def test_state_uses_the_engine_names_and_open_means_none(self):
        s = today.range_sweep_state
        self.assertIsNone(s(self.ROW, 100.0, self.AT))
        self.assertIsNone(s(self.ROW, None, self.AT))
        self.assertEqual(s(dict(self.ROW, expires_at="2026-10-16T12:00:00+00:00"), 100.0, self.AT), "verlopen")
        self.assertEqual(s(self.ROW, 95.9, self.AT), "weggelopen")                  # het midden (96) is geraakt zonder de limiet
        self.assertEqual(s(self.ROW, 103.0, self.AT), "stop_voor_vulling")
        long = dict(self.ROW, direction="long", stop=89.0, legs="[[1.0, 91.0]]")
        self.assertIsNone(s(long, 92.0, self.AT))
        self.assertEqual(s(long, 96.0, self.AT), "weggelopen")
        self.assertEqual(s(long, 88.9, self.AT), "stop_voor_vulling")
        self.assertEqual(today.OPEN_RANGE_STATES, (None,))

    def test_stop_headline_is_measured(self):
        h = today.stop_headline({"direction": "short", "legs": "[[1.0, 100.0]]", "stop": 102.5}, {"doelkans": [{"r": 1, "p_text": "48%", "ci_text": "41 tot 55%", "n": 412}]}, 0.12)
        self.assertEqual((h["value"], h["unit"]), ("2,50", "%"))
        self.assertEqual(h["delta"], "kosten 0,05R")
        self.assertEqual(h["doelkans"][0]["p_text"], "48%")

    def test_stop_headline_without_a_lab_row_has_no_table(self):
        h = today.stop_headline({"direction": "long", "legs": "[[0.4, 100.0], [0.6, 99.0]]", "stop": 98.0}, None, 0.12)
        self.assertEqual(h["doelkans"], [])
        self.assertEqual(h["value"], "1,41")                                          # (99.4 - 98) / 99.4

    def test_the_target_table_only_shows_for_the_variant_the_lab_measured(self):
        lab = {"summary": {"variant": "RZ_2H", "stop_name": "zone_05", "doelkans": [{"r": 1, "p_text": "48%", "ci_text": "41 tot 55%", "n": 412}]}}
        self.assertEqual(today.lab_doelkans(lab, self.ROW)[0]["p_text"], "48%")
        self.assertEqual(today.lab_doelkans(lab, dict(self.ROW, variant="RS_1H")), [])      # een ander lab dan dat van deze setup: geen cijfers lenen
        self.assertEqual(today.lab_doelkans(lab, dict(self.ROW, stop_name="wick_025")), [])
        self.assertEqual(today.lab_doelkans(None, self.ROW), [])

    def test_range_watch_row_names_the_nearest_edge(self):
        w = {"id": 4, "coin": "ARB", "tf": "2h", "range_high": 0.2040, "range_low": 0.17, "found_at": "2026-10-16T09:00:00+00:00", "state": "actief"}
        row = today.range_watch_row(w, 0.2000, self.AT)
        self.assertEqual((row["edge"], row["tf_label"], row["age"]), ("boven", "2u", "3 uur geleden"))
        self.assertAlmostEqual(row["dist_pct"], 2.0, places=6)
        self.assertEqual(row["dist_text"], "2,0% tot boven")
        self.assertEqual(today.range_watch_row(w, 0.1720, self.AT)["edge"], "onder")
        self.assertEqual(today.range_watch_row(w, 0.2100, self.AT)["dist_text"], "2,9% buiten boven")
        none = today.range_watch_row(w, None, self.AT)
        self.assertEqual((none["dist_pct"], none["dist_text"]), (None, ""))
