import unittest

from app import chance_checks as cc


class ChanceChecksTests(unittest.TestCase):
    def test_finish_builds_the_checkmark_format_the_template_reads(self):
        reason, pct = cc.finish([("A", True), ("B", False), ("C", True), ("D", True)])
        self.assertEqual(reason, "✓ A | ✗ B | ✓ C | ✓ D")
        self.assertEqual(pct, 75.0)

    def test_structure_checks_count_measured_features(self):
        plan = {"from_levels": True, "targets_r": [1.0, 2.0, 3.0]}
        full = cc.structure_checks({"vol_ratio": 2.0, "with_trend": True, "touches": 4, "span": 20}, plan, "A")
        self.assertTrue(all(ok for _, ok in full))
        weak = cc.structure_checks({"vol_ratio": 0.9, "with_trend": False, "touches": 2, "span": 6}, {"targets_r": [1.0]}, "C")
        self.assertFalse(any(ok for _, ok in weak))
        self.assertEqual(cc.parse_features("{kapot"), {})

    def test_trend_checks_use_room_to_the_impulse_top_and_stop_size(self):
        ok = cc.trend_checks("long", 100.0, 99.0, 102.0)        # top op 2R, stop 1%
        self.assertEqual([c for _, c in ok], [True, True, True])
        bad = cc.trend_checks("long", 100.0, 99.9, 100.05)      # top op 0,5R, stop 0,1%
        self.assertEqual([c for _, c in bad], [True, False, False])

    def test_script_and_smc_checks(self):
        self.assertEqual([c for _, c in cc.script_checks("short", 100.0, 101.0, 97.0, "short")], [True, True, True])
        self.assertFalse(cc.script_checks("short", 100.0, 101.0, 97.0, "long")[2][1])
        smc = cc.smc_checks(2.5, 0.5, True, warning=False)
        self.assertTrue(all(ok for _, ok in smc))
        self.assertFalse(cc.smc_checks(1.0, 0.1, False, warning=True)[1][1])


if __name__ == "__main__":
    unittest.main()
