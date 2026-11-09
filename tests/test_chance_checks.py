import unittest

from app import chance_checks as cc


class ChanceChecksTests(unittest.TestCase):
    def test_finish_builds_the_checkmark_format_the_template_reads(self):
        reason, pct = cc.finish([("A", True), ("B", False), ("C", True), ("D", True)])
        self.assertEqual(reason, "✓ A | ✗ B | ✓ C | ✓ D")
        self.assertEqual(pct, 75.0)

    def test_parse_reason_is_the_inverse_of_finish(self):
        checks = [("A", True), ("Zone dun (hooguit 1,5 ATR)", False)]
        self.assertEqual(cc.parse_reason(cc.finish(checks)[0]), checks)
        self.assertEqual(cc.parse_reason(None), [])
        self.assertEqual(cc.parse_reason("Toelichting zonder tekens"), [])

    def test_poc_samenval_is_one_measured_feature_or_nothing(self):
        self.assertEqual(cc.poc_checks(None), [])                  # niet gemeten: geen kenmerk, geen score
        self.assertEqual(cc.poc_checks(True), [(cc.POC_LABEL, True)])
        self.assertEqual(cc.poc_checks(False), [(cc.POC_LABEL, False)])
        self.assertIn("POC-samenval", cc.POC_LABEL)
        self.assertEqual(cc.with_checks("Gemeten: x.", None), ("Gemeten: x.", None))
        reason, pct = cc.with_checks("Gemeten: x.", True)
        self.assertEqual(reason, "Gemeten: x. | ✓ " + cc.POC_LABEL)
        self.assertEqual(pct, 100.0)
        self.assertEqual(cc.parse_reason(reason), [(cc.POC_LABEL, True)])
        self.assertEqual(cc.with_checks("Gemeten: x.", False)[1], 0.0)

    def test_structure_checks_count_measured_features(self):
        plan = {"from_levels": True, "targets_r": [1.0, 2.0, 3.0]}
        full = cc.structure_checks({"vol_ratio": 2.0, "with_trend": True, "touches": 4, "span": 20}, plan, "A")
        self.assertTrue(all(ok for _, ok in full))
        weak = cc.structure_checks({"vol_ratio": 0.9, "with_trend": False, "touches": 2, "span": 6}, {"targets_r": [1.0]}, "C")
        self.assertFalse(any(ok for _, ok in weak))
        self.assertEqual(cc.parse_features("{kapot"), {})

    def test_structure_checks_ignore_the_grade(self):
        # Het oordeel A/B/C is alleen nog een meting in de database: het telt niet als kenmerk en staat niet op een kaart.
        plan = {"from_levels": True, "targets_r": [1.0, 2.0]}
        f = {"vol_ratio": 2.0, "with_trend": True, "touches": 4, "span": 20}
        self.assertEqual(cc.structure_checks(f, plan, "A"), cc.structure_checks(f, plan, "C"))
        self.assertFalse(any("CEO" in label for label, _ in cc.structure_checks(f, plan, None)))

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


class RangeSweepScoreTest(unittest.TestCase):
    F = {"touches_high": 6, "touches_low": 6, "width_atr": 9.3, "age_bars": 120, "edge_spread_atr": 0.0, "ob_opposite": True,
         "displacement_atr": 1.3, "zone_fresh": True, "zone_atr": 0.9}

    def test_fixture_scores_85_and_is_strong(self):
        reason, score = cc.weighted_finish(cc.range_sweep_checks(self.F, "1h"))
        self.assertEqual(score, 85.0)
        self.assertEqual(cc.grade_of(score), "A")
        self.assertIn("✗ Sterke beweging weg van de zone (minstens 1,5 ATR)", reason)

    def test_weights_are_forty_and_sixty(self):
        checks = cc.range_sweep_checks(self.F, "1h")
        self.assertEqual(sum(w for _, _, w in checks[:4]), 40)
        self.assertEqual(sum(w for _, _, w in checks[4:]), 60)

    def test_age_minimum_depends_on_timeframe(self):
        f = {**self.F, "age_bars": 40}
        by_label = lambda tf: {l: ok for l, ok, _ in cc.range_sweep_checks(f, tf)}
        self.assertFalse(by_label("30m")["Range minstens 48 candles oud"])
        self.assertTrue(by_label("2h")["Range minstens 36 candles oud"])

    def test_grades(self):
        self.assertEqual([cc.grade_of(s) for s in (80, 79.9, 60, 59.9)], ["A", "B", "B", "C"])

    def test_constants_follow_the_preregistration(self):
        from app.replay import rangesweep as rs
        self.assertEqual(cc.AGE_MIN, rs.AGE_MIN)


if __name__ == "__main__":
    unittest.main()
