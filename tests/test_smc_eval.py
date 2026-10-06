import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from app import smc_eval


def candle(low, high, close, ts="2026-01-01 10:00"):
    return {"timestamp": pd.Timestamp(ts, tz="UTC"), "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


class CandleStateTest(unittest.TestCase):
    def test_short_rejection_closes_below_zone_after_touch(self):
        in_zone, rejected, passed = smc_eval.last_candle_state(candle(99, 101, 98.5), 100.0, 102.0, "short")
        self.assertEqual((in_zone, rejected, passed), (True, True, False))

    def test_short_passed_needs_close_above_zone_plus_buffer(self):
        _, rejected, passed = smc_eval.last_candle_state(candle(101, 104, 103.5), 100.0, 102.0, "short", atr=2.0)
        self.assertEqual((rejected, passed), (False, True))
        _, _, passed_small = smc_eval.last_candle_state(candle(101, 102.4, 102.3), 100.0, 102.0, "short", atr=2.0)
        self.assertFalse(passed_small)

    def test_long_mirror(self):
        in_zone, rejected, passed = smc_eval.last_candle_state(candle(99.5, 101, 102.5), 100.0, 102.0, "long")
        self.assertEqual((in_zone, rejected, passed), (True, True, False))


class MarginsTest(unittest.TestCase):
    def test_atr_margins(self):
        setup = {"atr": 8.0, "sweep_price": 2820.0, "liquidity_target": 2600.0}
        self.assertEqual(smc_eval.smc_stop_take_margins(setup), (2.0, 2.0))

    def test_legacy_pct_margins_when_atr_missing(self):
        setup = {"atr": None, "sweep_price": 2000.0, "liquidity_target": 1000.0}
        self.assertEqual(smc_eval.smc_stop_take_margins(setup), (2.0, 5.0))


class ExpiryTest(unittest.TestCase):
    def test_expired_after_max_age(self):
        setup = {"created_at": "2026-01-01T00:00:00+00:00"}
        self.assertFalse(smc_eval.setup_expired(setup, datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)))
        self.assertTrue(smc_eval.setup_expired(setup, datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc)))


class JudgeTest(unittest.TestCase):
    def frame(self, rows):
        ts = pd.date_range("2026-01-01 10:00", periods=len(rows), freq="15min", tz="UTC")
        return pd.DataFrame({"timestamp": ts, "open": [r[2] for r in rows], "high": [r[1] for r in rows],
                             "low": [r[0] for r in rows], "close": [r[2] for r in rows], "volume": [1.0] * len(rows)})

    def setup(self, **kw):
        base = {"zone_low": 100.0, "zone_high": 102.0, "direction": "short", "atr": None,
                "updated_at": "2026-01-01T10:00:00+00:00"}
        base.update(kw)
        return base

    def test_rejected_candle_after_updated_at(self):
        closed = self.frame([(95, 96, 95.5), (99, 101, 98.5)])  # tweede candle sluit 10:30, na updated_at
        self.assertEqual(smc_eval.judge_forming_setup(self.setup(), closed), "rejected")

    def test_candle_before_updated_at_is_ignored(self):
        closed = self.frame([(99, 101, 98.5)])  # sloot 10:15
        self.assertEqual(smc_eval.judge_forming_setup(self.setup(updated_at="2026-01-01T10:30:00+00:00"), closed), "open")

    def test_passed_candle(self):
        closed = self.frame([(101, 104, 103.5)])
        self.assertEqual(smc_eval.judge_forming_setup(self.setup(), closed), "passed")


class EvaluateCompletionTest(unittest.TestCase):
    def short_setup(self):
        # atr 8 -> marges 2.0: stop = 2820 + 2 = 2822, doel = 2600 + 2 = 2602
        return {"direction": "short", "atr": 8.0, "sweep_price": 2820.0, "liquidity_target": 2600.0}

    def flat_frame(self, last_close):
        n = 40
        ts = pd.date_range("2026-01-01 00:00", periods=n, freq="15min", tz="UTC")
        closes = [2700.0] * (n - 1) + [last_close]
        return pd.DataFrame({"timestamp": ts, "open": closes, "high": [c + 1 for c in closes],
                             "low": [c - 1 for c in closes], "close": closes, "volume": [1.0] * n})

    def test_no_sniper_found_rejects_entry(self):
        result = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2700.0))
        self.assertIsNone(result.signal)
        self.assertEqual(result.reject_reason, "entry_slechter_dan_sniper")
        self.assertIn("geen sniper gevonden", result.detail)

    def test_entry_below_sniper_for_short_is_rejected(self):
        with mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(2710.0, "reden")):
            result = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2700.0))
        self.assertEqual(result.reject_reason, "entry_slechter_dan_sniper")

    def test_risk_reward_gate_then_success(self):
        setup = self.short_setup()
        with mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(2690.0, "reden")):
            low = smc_eval.evaluate_completion(setup, self.flat_frame(2700.0))
            # entry 2700: risico 122, rendement 98 -> 0.80 tegen 1
            self.assertIsNone(low.signal)
            self.assertEqual(low.reject_reason, "risico_rendement_te_laag")
            self.assertIn("0.80", low.detail)

            ok = smc_eval.evaluate_completion(setup, self.flat_frame(2750.0))
        # entry 2750: risico 72, rendement 148 -> 2.06 tegen 1
        self.assertIsNone(ok.reject_reason)
        draft = ok.signal
        self.assertEqual(draft.entry_price, 2750.0)
        self.assertEqual(draft.stop_loss, 2822.0)
        self.assertEqual(draft.take_profit, 2602.0)
        self.assertEqual(draft.sniper_entry_price, 2690.0)
        self.assertEqual(draft.sniper_reason, "reden")
        self.assertAlmostEqual(draft.risk_reward_ratio, 148.0 / 72.0)

    def test_min_stop_distance_widens_tight_stops_instead_of_rejecting(self):
        # entry 2750, stop 2822: stopafstand 72 / 2750 = 2.62%
        with mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(2690.0, "reden")):
            tight = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2750.0), min_stop_pct=2.65)
            exact = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2750.0), min_stop_pct=2.6)
            off = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2750.0), min_stop_pct=0)
        self.assertIsNotNone(tight.signal)                                  # de kans blijft, de stop gaat verder weg
        self.assertAlmostEqual(tight.signal.stop_loss, 2750.0 * 1.0265)
        self.assertLess(tight.signal.risk_reward_ratio, off.signal.risk_reward_ratio)   # en de R:R zakt eerlijk mee
        self.assertEqual(exact.signal.stop_loss, 2822.0)                    # al ruim genoeg: ongemoeid
        self.assertEqual(off.signal.stop_loss, 2822.0)

    def test_widened_stop_counts_in_the_risk_reward_gate(self):
        with mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(2690.0, "reden")), \
                mock.patch.object(smc_eval.config, "SMC_MIN_STOP_PCT", 5.0):
            result = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2700.0))
        self.assertEqual(result.reject_reason, "risico_rendement_te_laag")
        self.assertIn("stop 2835.0000", result.detail)                      # 2700 + 5%

    def test_floor_stop_both_directions(self):
        self.assertAlmostEqual(smc_eval.floor_stop("long", 100.0, 99.95, 0.2), 99.8)
        self.assertEqual(smc_eval.floor_stop("long", 100.0, 98.0, 0.2), 98.0)       # al ruim: ongemoeid
        self.assertAlmostEqual(smc_eval.floor_stop("short", 100.0, 100.05, 0.2), 100.2)
        self.assertEqual(smc_eval.floor_stop("short", 100.0, 105.0, 0.2), 105.0)
        self.assertEqual(smc_eval.floor_stop("long", 100.0, 99.95, 0), 99.95)       # 0 zet de toets uit

    def test_stop_on_wrong_side_is_rejected(self):
        with mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(2690.0, "reden")):
            result = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2850.0))
        self.assertEqual(result.reject_reason, "stop_take_verkeerde_kant")

    def test_sniper_beyond_stop_is_suppressed_not_rejected(self):
        # sniper voorbij de stop (gemockt): alleen de sniper-weergave verdwijnt, het signaal blijft
        with mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(2680.0, "reden")), \
                mock.patch.object(smc_eval.indicators, "sniper_beyond_stop", return_value=True):
            result = smc_eval.evaluate_completion(self.short_setup(), self.flat_frame(2750.0))
        self.assertIsNotNone(result.signal)
        self.assertIsNone(result.signal.sniper_entry_price)
        self.assertIsNone(result.signal.sniper_reason)


class FindCandidateSkipTest(unittest.TestCase):
    """find_candidate met gemockte indicatoren: alleen de beslisvolgorde en de skip-redenen."""

    def frames(self):
        ts30 = pd.date_range("2026-01-01 00:00", periods=5, freq="30min", tz="UTC")
        df_30m = pd.DataFrame({"timestamp": ts30, "open": 100.0, "high": 106.0, "low": 95.0, "close": 100.0, "volume": 1.0})
        ts15 = pd.date_range("2026-01-01 00:00", periods=8, freq="15min", tz="UTC")
        closed_15m = pd.DataFrame({"timestamp": ts15, "open": 98.0, "high": 99.0, "low": 97.0, "close": 98.0, "volume": 1.0})
        return df_30m.iloc[:-1], df_30m, closed_15m

    def run_scan(self, sweep, last_close=98.0, zone=(100.0, 102.0)):
        closed_30m, df_30m, closed_15m = self.frames()
        last_candle = {"close": last_close}
        ind = smc_eval.indicators
        with mock.patch.object(ind, "find_structure_break", return_value=SimpleNamespace(
                direction="short", break_index=1, broken_pivot=SimpleNamespace(price=110.0))), \
                mock.patch.object(ind, "compute_indicators", return_value=SimpleNamespace(atr=2.0)), \
                mock.patch.object(ind, "find_liquidity_sweep_before_break", return_value=sweep), \
                mock.patch.object(ind, "find_fair_value_gaps", return_value=[]), \
                mock.patch.object(ind, "find_order_blocks", return_value=[]), \
                mock.patch.object(ind, "find_confluence_zone", return_value=zone), \
                mock.patch.object(ind, "_find_pivots", return_value=[SimpleNamespace(kind="low", price=90.0)]):
            return smc_eval.find_candidate(closed_30m, df_30m, closed_15m, last_candle)

    def test_geen_sweep_keeps_break_direction(self):
        scan = self.run_scan(sweep=None)
        self.assertEqual((scan.break_direction, scan.candidate, scan.skip_reason), ("short", None, "geen_sweep"))

    def test_stop_of_doel_binnen_zone(self):
        # sweep 101 + 0.25*2 = 101.5 ligt nog onder zone_high 102: stop niet voorbij de zone
        scan = self.run_scan(sweep=SimpleNamespace(index=0, price=101.0))
        self.assertEqual((scan.break_direction, scan.candidate, scan.skip_reason),
                         ("short", None, "stop_of_doel_binnen_zone"))
        self.assertIn("101.5000", scan.detail)
        self.assertIn("100.0000-102.0000", scan.detail)

    def test_stop_vlak_achter_de_limiet_blijft_een_kandidaat(self):
        # de stop wordt later verbreed (floor_stop), de setup zelf blijft bestaan
        scan = self.run_scan(sweep=SimpleNamespace(index=0, price=1000.6), zone=(1000.0, 1000.5))
        self.assertIsNone(scan.skip_reason)
        self.assertEqual(scan.candidate.sweep_price, 1000.6)

    def test_koers_al_in_zone(self):
        # stop 105.5 en doel 90.5 liggen goed, maar de laatste close (101) zit al in/boven zone_low voor een short
        scan = self.run_scan(sweep=SimpleNamespace(index=0, price=105.0), last_close=101.0)
        self.assertEqual((scan.break_direction, scan.candidate, scan.skip_reason), ("short", None, "koers_al_in_zone"))

    def test_valid_candidate_when_price_below_zone(self):
        scan = self.run_scan(sweep=SimpleNamespace(index=0, price=105.0), last_close=98.0)
        self.assertIsNone(scan.skip_reason)
        c = scan.candidate
        self.assertEqual((c.direction, c.zone_low, c.zone_high, c.sweep_price, c.liquidity_target, c.atr),
                         ("short", 100.0, 102.0, 105.0, 90.0, 2.0))


if __name__ == "__main__":
    unittest.main()
