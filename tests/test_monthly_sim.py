import unittest

from app import monthly_sim as ms


def row(outcome="take_profit", done="2026-09-10T12:00:00+00:00", created=None, trade_type="smc",
        price=100.0, stop=99.0, take=102.0, r_override=None):
    # take_profit = +2R brutto, stop_loss = -1R
    return {"trade_type": trade_type, "auto_outcome": outcome, "price": price, "stop_loss": stop, "take_profit": take,
            "created_at": created or "2026-09-10T11:00:00+00:00", "auto_outcome_at": done, "r_override": r_override}


def win(done, **kw):
    return row("take_profit", done, **kw)


def loss(done, **kw):
    return row("stop_loss", done, **kw)


class SimulateTests(unittest.TestCase):
    def test_flat_adds_r_times_risk_of_start_equity(self):
        res = ms.simulate([win("2026-09-10T12:00:00+00:00"), loss("2026-09-11T12:00:00+00:00")], risk_pct=1.0, cost_pct=0, compound=False)
        # +2% dan -1% van 100: 102, 101
        self.assertAlmostEqual(res["months"][0]["end_equity"], 101.0)
        self.assertAlmostEqual(res["totals"]["total_return_pct"], 1.0)

    def test_compound_multiplies(self):
        res = ms.simulate([win("2026-09-10T12:00:00+00:00"), loss("2026-09-11T12:00:00+00:00")], risk_pct=1.0, cost_pct=0, compound=True)
        self.assertAlmostEqual(res["months"][0]["end_equity"], 100 * 1.02 * 0.99)
        self.assertAlmostEqual(res["months"][0]["return_pct"], 100 * 1.02 * 0.99 - 100)

    def test_risk_pct_scales(self):
        res = ms.simulate([win("2026-09-10T12:00:00+00:00")], risk_pct=2.0, cost_pct=0, compound=False)
        self.assertAlmostEqual(res["totals"]["total_return_pct"], 4.0)

    def test_costs_lower_net_r(self):
        # stop 1% -> kosten 0.06/1 = 0.06R per trade
        res = ms.simulate([win("2026-09-10T12:00:00+00:00"), loss("2026-09-11T12:00:00+00:00")], cost_pct=0.06, compound=False)
        self.assertAlmostEqual(res["months"][0]["net_r"], 1.94 + -1.06)
        self.assertAlmostEqual(res["totals"]["avg_net_r"], (1.94 - 1.06) / 2)

    def test_default_cost_is_config(self):
        from app import config
        res = ms.simulate([loss("2026-09-10T12:00:00+00:00")], compound=False)
        self.assertAlmostEqual(res["months"][0]["net_r"], -1 - config.TRACK_RECORD_COST_PCT)

    def test_orders_by_outcome_time_not_input_order(self):
        # eerst een verlies (op 9e), dan een winst (op 10e): compound is hier commutatief, dus check de curve via drawdown
        late_win = win("2026-09-10T12:00:00+00:00")
        early_loss = loss("2026-09-09T12:00:00+00:00")
        res = ms.simulate([late_win, early_loss], cost_pct=0, compound=False)
        self.assertAlmostEqual(res["totals"]["max_drawdown_pct"], 1.0 / 100 * 100)  # 100 -> 99 -> 101
        self.assertEqual(res["totals"]["longest_losing_streak"], 1)

    def test_fallback_to_created_at(self):
        r = win(None, created="2026-08-31T23:00:00+00:00")
        res = ms.simulate([r], cost_pct=0)
        self.assertEqual(res["months"][0]["month"], "2026-08")

    def test_month_boundary_and_per_month_numbers(self):
        rows = [win("2026-08-31T23:59:00+00:00"), loss("2026-09-01T00:01:00+00:00"), win("2026-09-02T00:00:00+00:00")]
        res = ms.simulate(rows, cost_pct=0, compound=False)
        self.assertEqual([m["month"] for m in res["months"]], ["2026-08", "2026-09"])
        aug, sep = res["months"]
        self.assertEqual((aug["trades"], aug["wins"]), (1, 1))
        self.assertEqual((sep["trades"], sep["wins"]), (2, 1))
        self.assertAlmostEqual(aug["return_pct"], 2.0)
        self.assertAlmostEqual(aug["end_equity"], 102.0)
        self.assertAlmostEqual(sep["net_r"], 1.0)
        self.assertAlmostEqual(sep["return_pct"], 1.0)
        self.assertAlmostEqual(sep["end_equity"], 103.0)

    def test_compound_month_return_relative_to_month_start(self):
        rows = [win("2026-08-10T00:00:00+00:00"), win("2026-09-10T00:00:00+00:00")]
        res = ms.simulate(rows, cost_pct=0, compound=True)
        self.assertAlmostEqual(res["months"][1]["return_pct"], 2.0)
        self.assertAlmostEqual(res["totals"]["total_return_pct"], (1.02 ** 2 - 1) * 100)

    def test_r_override_honoured(self):
        r = row("take_profit", r_override=0.5)
        res = ms.simulate([r], cost_pct=0, compound=False)
        self.assertAlmostEqual(res["months"][0]["net_r"], 0.5)

    def test_unresolved_and_expired_ignored(self):
        rows = [win("2026-09-10T12:00:00+00:00"), row("vervallen"), row(None), row("open")]
        res = ms.simulate(rows, cost_pct=0)
        self.assertEqual(res["totals"]["n"], 1)

    def test_drawdown_and_losing_streak(self):
        rows = [win("2026-09-01T12:00:00+00:00"), loss("2026-09-02T12:00:00+00:00"), loss("2026-09-03T12:00:00+00:00"),
                loss("2026-09-04T12:00:00+00:00"), win("2026-09-05T12:00:00+00:00"), loss("2026-09-06T12:00:00+00:00")]
        res = ms.simulate(rows, cost_pct=0, compound=False)
        # 100,102,101,100,99,101,100 ; piek 102 dal naar 99 = 3/102
        self.assertAlmostEqual(res["totals"]["max_drawdown_pct"], 3 / 102 * 100)
        self.assertEqual(res["totals"]["longest_losing_streak"], 3)

    def test_totals_best_worst_month_winrate(self):
        rows = [win("2026-08-10T00:00:00+00:00"), loss("2026-09-10T00:00:00+00:00")]
        t = ms.simulate(rows, cost_pct=0, compound=False)["totals"]
        self.assertEqual(t["n"], 2)
        self.assertAlmostEqual(t["winrate_pct"], 50.0)
        self.assertEqual(t["best_month"]["month"], "2026-08")
        self.assertEqual(t["worst_month"]["month"], "2026-09")

    def test_overlap_warning(self):
        a = win("2026-09-10T12:00:00+00:00", created="2026-09-10T08:00:00+00:00")
        b = loss("2026-09-10T14:00:00+00:00", created="2026-09-10T10:00:00+00:00")
        c = win("2026-09-12T14:00:00+00:00", created="2026-09-12T10:00:00+00:00")
        res = ms.simulate([a, b, c], cost_pct=0)
        self.assertEqual(res["totals"]["overlapping"], 2)
        self.assertTrue(any("tegelijk" in w for w in res["warnings"]))

    def test_no_overlap_no_overlap_warning(self):
        a = win("2026-09-10T12:00:00+00:00", created="2026-09-10T08:00:00+00:00")
        b = win("2026-09-11T12:00:00+00:00", created="2026-09-11T08:00:00+00:00")
        res = ms.simulate([a, b], cost_pct=0)
        self.assertEqual(res["totals"]["overlapping"], 0)
        self.assertFalse(any("tegelijk" in w for w in res["warnings"]))

    def test_small_sample_warnings_and_cost_note(self):
        res = ms.simulate([win("2026-09-10T12:00:00+00:00")], cost_pct=0.06)
        text = " ".join(res["warnings"])
        self.assertIn("maanden", text)
        self.assertIn("trades", text)
        self.assertIn("0.06", text)

    def test_empty_input(self):
        res = ms.simulate([])
        self.assertEqual(res["months"], [])
        self.assertEqual(res["totals"]["n"], 0)
        self.assertIsNone(res["totals"]["winrate_pct"])
        self.assertTrue(res["warnings"])

    def test_filter_by_type(self):
        rows = [win("2026-09-10T12:00:00+00:00", trade_type="smc"), loss("2026-09-11T12:00:00+00:00", trade_type="patroon")]
        res = ms.simulate(rows, cost_pct=0, trade_types=["smc"])
        self.assertEqual(res["totals"]["n"], 1)

    def test_by_type(self):
        rows = [win("2026-09-10T12:00:00+00:00", trade_type="smc"), loss("2026-09-11T12:00:00+00:00", trade_type="patroon"),
                win("2026-09-12T12:00:00+00:00", trade_type="smc")]
        res = ms.simulate_by_type(rows, cost_pct=0, compound=False)
        self.assertEqual(set(res), {"smc", "patroon"})
        self.assertEqual(res["smc"]["n"], 2)
        self.assertAlmostEqual(res["smc"]["total_return_pct"], 4.0)
        self.assertAlmostEqual(res["patroon"]["total_return_pct"], -1.0)


if __name__ == "__main__":
    unittest.main()
