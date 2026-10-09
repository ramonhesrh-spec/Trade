import unittest
from datetime import datetime, timezone

from app import track_record as tr

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def row(trade_type="smc", outcome="take_profit", price=100.0, stop=99.0, take=102.0, message_id=None,
        created="2026-09-20T10:00:00+00:00", done="2026-09-20T10:30:00+00:00"):
    return {"message_id": message_id, "trade_type": trade_type, "auto_outcome": outcome, "price": price,
            "stop_loss": stop, "take_profit": take, "created_at": created, "auto_outcome_at": done}


class RTests(unittest.TestCase):
    def test_r_override_beats_the_fixed_formula(self):
        r = {"price": 100.0, "stop_loss": 95.0, "take_profit": 120.0, "auto_outcome": "take_profit", "r_override": 2.3}
        self.assertEqual(tr.signal_r(r), 2.3)
        r["auto_outcome"], r["r_override"] = "stop_loss", -0.4
        self.assertEqual(tr.signal_r(r), -0.4)

    def test_without_override_nothing_changes(self):
        r = {"price": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "auto_outcome": "take_profit"}
        self.assertEqual(tr.signal_r(r), 2.0)
        self.assertEqual(tr.signal_r({**r, "r_override": None}), 2.0)

    def test_override_on_unresolved_signal_is_ignored(self):
        for outcome in (None, "vervallen"):
            self.assertIsNone(tr.signal_r({**row(outcome=outcome), "r_override": 1.5}))

    def test_r_per_uitkomst(self):
        self.assertEqual(tr.signal_r(row()), 2.0)
        self.assertEqual(tr.signal_r(row(outcome="stop_loss")), -1.0)
        self.assertIsNone(tr.signal_r(row(outcome="vervallen")))
        self.assertIsNone(tr.signal_r(row(outcome=None)))
        self.assertIsNone(tr.signal_r(row(stop=100.0)))

    def test_score_split_toont_hoge_tegenover_lage_score(self):
        rows = [dict(row(outcome="take_profit"), pass_pct=86.0), dict(row(outcome="stop_loss"), pass_pct=43.0),
                dict(row(outcome="stop_loss"), pass_pct=29.0), row(outcome="take_profit")]   # laatste heeft geen score
        entry = next(e for e in tr.summarize(rows, 0.0, NOW) if e["source"] == "scan" and e["trade_type"] == "smc")
        split = entry["score_split"]
        self.assertEqual((split["high_n"], split["low_n"]), (1, 2))
        self.assertAlmostEqual(split["high_avg"], 2.0)
        self.assertAlmostEqual(split["low_avg"], -1.0)
        plain = next(e for e in tr.summarize([row()], 0.0, NOW) if e["source"] == "scan")
        self.assertIsNone(plain["score_split"])

    def test_kosten_per_signaal_hangen_af_van_stopafstand(self):
        # stop 1% en kosten 0,06% per rondreis: 0,06R. Stop 0,1%: 0,6R.
        self.assertAlmostEqual(tr._cost_r(row(), 0.06), 0.06)
        self.assertAlmostEqual(tr._cost_r(row(stop=99.9), 0.06), 0.6)


class SummarizeTests(unittest.TestCase):
    def test_groepen_tellingen_en_netto(self):
        rows = [row(), row(outcome="stop_loss"), row(outcome="vervallen"), row(trade_type="patroon", outcome="stop_loss"),
                row(trade_type="day_trading", message_id=4)]
        out = {(e["source"], e["trade_type"]): e for e in tr.summarize(rows, 0.06, NOW)}
        smc = out[("scan", "smc")]
        self.assertEqual((smc["total"], smc["resolved"], smc["wins"], smc["losses"], smc["open_or_expired"]), (3, 2, 1, 1, 1))
        self.assertAlmostEqual(smc["winrate"], 0.5)
        self.assertAlmostEqual(smc["avg_gross"], 0.5)
        self.assertAlmostEqual(smc["avg_net"], 0.5 - 0.06)
        self.assertEqual(out[("community", "day_trading")]["total"], 1)
        self.assertEqual(out[("alles", "alles")]["total"], 5)
        self.assertEqual(tr.summarize(rows, 0.06, NOW)[-1]["source"], "alles")

    def test_status(self):
        self.assertEqual(tr._status(10, 1.0), "te_weinig")
        self.assertEqual(tr._status(40, -0.1), "verlies")
        self.assertEqual(tr._status(40, 0.0), "verlies")
        self.assertEqual(tr._status(40, 0.2), "positief")
        self.assertEqual(tr._status(150, 0.2), "voordeel")
        self.assertEqual(tr._status(0, None), "te_weinig")

    def test_status_in_summary_en_vervallen_tellen_niet_mee(self):
        rows = [row(outcome="stop_loss") for _ in range(35)] + [row(outcome="vervallen") for _ in range(50)]
        smc = [e for e in tr.summarize(rows, 0.06, NOW) if e["trade_type"] == "smc"][0]
        self.assertEqual(smc["status"], "verlies")
        self.assertEqual(smc["resolved"], 35)
        self.assertEqual(smc["open_or_expired"], 50)

    def test_cumulatief_per_week_en_recent(self):
        rows = [row(outcome="stop_loss", created="2026-05-01T10:00:00+00:00", done="2026-05-01T10:30:00+00:00"),   # ver terug
                row(outcome="stop_loss", done="2026-10-01T10:00:00+00:00"),
                row(done="2026-10-02T10:00:00+00:00")]
        smc = [e for e in tr.summarize(rows, 0.0, NOW) if e["trade_type"] == "smc"][0]
        self.assertEqual(len(smc["cumulative"]), tr.WEEKS_SHOWN)
        self.assertAlmostEqual(smc["cumulative"][-1], -1.0 + -1.0 + 2.0)   # alles sinds het begin is -1 -1 +2
        self.assertEqual(smc["recent_resolved"], 2)                        # de eerste ligt buiten 90 dagen

    def test_lege_invoer(self):
        self.assertEqual(tr.summarize([], 0.06, NOW), [])


class SparklineTests(unittest.TestCase):
    def test_stijgend_dalend_vlak_en_leeg(self):
        self.assertIn("proof-spark-up", tr.sparkline_svg([0, 1, 2]))
        self.assertIn("proof-spark-down", tr.sparkline_svg([2, 1, 0]))
        self.assertIn("polyline", tr.sparkline_svg([0.0, 0.0, 0.0]))
        self.assertEqual(tr.sparkline_svg([]), "")


if __name__ == "__main__":
    unittest.main()


class SamenvalGroupTest(unittest.TestCase):
    def test_samenval_rows_get_own_entry_without_double_counting_total(self):
        base = {"message_id": None, "trade_type": "smc", "auto_outcome": "take_profit", "auto_outcome_at": "2026-10-01T10:00:00+00:00",
                "price": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "created_at": "2026-10-01T09:00:00+00:00"}
        rows = [{**base, "samenval": 1}, {**base, "samenval": 0}]
        out = {(e["source"], e["trade_type"]): e for e in tr.summarize(rows, 0.06, now=datetime(2026, 10, 5, tzinfo=timezone.utc))}
        self.assertEqual(out[("scan", "samenval")]["resolved"], 1)
        self.assertEqual(out[("scan", "smc")]["resolved"], 2)
        self.assertEqual(out[("alles", "alles")]["resolved"], 2)


class DaySummaryTests(unittest.TestCase):
    def test_telt_gemeld_afgerond_en_netto_r_sinds_een_moment(self):
        since = datetime(2026, 10, 5, 0, tzinfo=timezone.utc)
        rows = [row(created="2026-10-05T09:00:00+00:00"),                              # winst +2R
                row(outcome="stop_loss", created="2026-10-05T10:00:00+00:00"),         # -1R
                row(outcome=None, created="2026-10-05T11:00:00+00:00"),                # nog open
                row(created="2026-10-01T09:00:00+00:00")]                              # te oud
        d = tr.day_summary(rows, 0.0, since)
        self.assertEqual((d["signals"], d["resolved"], d["wins"]), (3, 2, 1))
        self.assertAlmostEqual(d["net_r"], 1.0)


class WeekSummaryTests(unittest.TestCase):
    def test_week_telt_per_dag_en_kiest_beste_en_slechtste(self):
        rows = [dict(row(created="2026-10-04T09:00:00+00:00", done="2026-10-04T10:00:00+00:00"), id=1, coin="BTC", direction="long"),            # +2R
                dict(row(outcome="stop_loss", created="2026-10-05T09:00:00+00:00", done="2026-10-05T10:00:00+00:00"), id=2, coin="ETH", direction="short"),   # -1R
                dict(row(outcome=None, created="2026-10-05T11:00:00+00:00"), id=3, coin="SOL", direction="long"),                                          # open
                dict(row(created="2026-09-01T09:00:00+00:00"), id=4, coin="OLD", direction="long")]                                                        # te oud
        w = tr.week_summary(rows, 0.0, NOW)
        self.assertEqual((w["signals"], w["resolved"], w["wins"]), (3, 2, 1))
        self.assertAlmostEqual(w["net_r"], 1.0)
        self.assertEqual(len(w["days"]), 7)
        self.assertAlmostEqual(w["cumulative"][-1], 1.0)
        self.assertEqual((w["best"]["coin"], w["worst"]["coin"]), ("BTC", "ETH"))


class RuleStatusTest(unittest.TestCase):
    PASS = {"lab_passes": True}

    def test_new_rule_is_in_proef(self):
        self.assertEqual(tr.rule_status(self.PASS, [0.1] * 10)["status"], "In proef")
        self.assertEqual(tr.rule_status(None, [])["status"], "In proef")

    def test_proven_needs_lab_and_fifty_live_trades(self):
        self.assertEqual(tr.rule_status(self.PASS, [0.1] * 50)["status"], "Bewezen")
        self.assertEqual(tr.rule_status(self.PASS, [0.1] * 49)["status"], "In proef")
        self.assertEqual(tr.rule_status(None, [0.1] * 80)["status"], "In proef")

    def test_thirty_losing_trades_make_a_rule_negative(self):
        self.assertEqual(tr.rule_status(self.PASS, [0.2] * 60 + [-0.5] * 30)["status"], "Negatief")

    def test_failed_lab_is_negative_even_without_live_trades(self):
        self.assertEqual(tr.rule_status({"lab_passes": False}, [])["status"], "Negatief")

    def test_proven_rule_falls_back_when_last_hundred_turn_clearly_negative(self):
        series = [0.5] * 100 + [-0.2] * 100
        self.assertNotEqual(tr.rule_status(self.PASS, series)["status"], "Bewezen")

    def test_result_keys_and_average_of_last_hundred(self):
        few = tr.rule_status(self.PASS, [0.1] * 99)
        self.assertIsNone(few["avg_last100"])
        self.assertEqual(few["n_live"], 99)
        self.assertTrue(few["reason"])
        full = tr.rule_status(self.PASS, [-0.1] * 20 + [0.2] * 100)
        self.assertAlmostEqual(full["avg_last100"], 0.2)
        self.assertEqual(full["status"], "Bewezen")

    def test_last_hundred_with_negative_upper_bound_blocks_proof(self):
        series = [1.0] * 400 + [-0.05] * 100       # gemiddelde alles positief, laatste 100 duidelijk onder 0
        self.assertNotEqual(tr.rule_status(self.PASS, series)["status"], "Bewezen")
