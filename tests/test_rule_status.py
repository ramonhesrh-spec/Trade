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


if __name__ == "__main__":
    unittest.main()
