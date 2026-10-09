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
