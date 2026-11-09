import unittest

from app import repo
from tests.test_samenval import DbCase


class RuleLabTest(DbCase):
    def test_roundtrip_and_overwrite(self):
        repo.set_rule_lab("don55_trend", True, {"n": 812, "avg": 0.09}, "2026-10-10T10:00:00+00:00")
        got = repo.get_rule_lab("don55_trend")
        self.assertTrue(got["lab_passes"])
        self.assertEqual(got["summary"]["n"], 812)
        repo.set_rule_lab("don55_trend", False, {"n": 900, "avg": -0.01}, "2026-10-11T10:00:00+00:00")
        self.assertFalse(repo.get_rule_lab("don55_trend")["lab_passes"])
        self.assertEqual(len(repo.list_rule_labs()), 1)

    def test_unknown_rule_is_none(self):
        self.assertIsNone(repo.get_rule_lab("bestaat_niet"))


class RangeSweepRuleStatusTest(DbCase):
    """De labrijen zoals strategy_lab --opslaan ze schrijft, door rule_status gelezen: stopkwaliteit geslaagd en voordeel mislukt is de verwachte uitkomst."""

    def labs(self):
        return {r["rule"]: r for r in repo.list_rule_labs()}

    def test_expected_case_stop_pass_edge_fail_is_in_proef(self):
        from app import track_record
        from tests import range_seed
        range_seed.seed_labs(stop_passes=True, edge_passes=False)
        labs = self.labs()
        self.assertEqual(track_record.rule_status(labs["range_sweep"], [], stop_lab=labs["range_sweep_stop"])["status"], "In proef")

    def test_no_stop_pass_means_negatief(self):
        from app import track_record
        from tests import range_seed
        range_seed.seed_labs(stop_passes=False, edge_passes=False)
        labs = self.labs()
        self.assertEqual(track_record.rule_status(labs["range_sweep"], [], stop_lab=labs["range_sweep_stop"])["status"], "Negatief")

    def test_both_pass_but_few_live_trades_is_still_in_proef(self):
        from app import track_record
        from tests import range_seed
        range_seed.seed_labs(stop_passes=True, edge_passes=True)
        labs = self.labs()
        self.assertEqual(track_record.rule_status(labs["range_sweep"], [0.2] * 10, stop_lab=labs["range_sweep_stop"])["status"], "In proef")

    def test_range_sweep_trades_come_through_the_repo_lists(self):
        from tests import range_seed
        sid = range_seed.seed_trade(stop_hit=True, ref_r=-1.0, closed=True)
        range_seed.seed_trade(coin="APT", direction="long")
        trade = repo.get_range_sweep_trade(sid)
        self.assertEqual((trade["coin"], trade["direction"]), ("ARB", "short"))
        self.assertEqual(repo.get_range_sweep_setup_by_signal(sid)["id"], trade["setup_id"])
        self.assertEqual(repo.count_range_sweep_setups_by_state(), {"filled": 2})
        self.assertIsNone(repo.get_range_sweep_trade(999))


class TradeResultTest(DbCase):
    def test_override_reaches_both_queries_and_upserts(self):
        sid = self.insert_signal(trade_type="smc")
        repo.mark_signal_auto_outcome(sid, "take_profit", "2026-10-10T10:00:00+00:00")
        other = self.insert_signal(trade_type="smc")
        repo.mark_signal_auto_outcome(other, "stop_loss", "2026-10-10T11:00:00+00:00")
        self.assertEqual({r["r_override"] for r in repo.list_type_results("smc")}, {None})
        repo.set_trade_result(sid, 2.3, "2026-10-10T10:00:00+00:00")
        repo.set_trade_result(sid, 1.8, "2026-10-10T10:05:00+00:00")
        got = {r["id"]: r["r_override"] for r in repo.list_signals_for_quality_report(None)}
        self.assertEqual(got, {sid: 1.8, other: None})
        self.assertEqual(sorted(r["r_override"] or 0 for r in repo.list_type_results("smc")), [0, 1.8])


if __name__ == "__main__":
    unittest.main()
