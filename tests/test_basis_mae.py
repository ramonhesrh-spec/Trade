"""Onderdeel B: hoe ver een afgeronde trade eerst tegen je in ging (MAE) en met je mee (MFE), in R, op candles van na de vulling tot de uitkomst.
Alleen meting: niets in een motor leest het."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import db, excursion, level_check, repo
from tests.test_range_sweep_live import EngineCase, FollowEngineTest
from tests.test_samenval import DbCase
from tests.test_web_focus import Base, signal


def bars(rows, start=datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc), minutes=5):
    return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(minutes=minutes * i)), "open": (h + l) / 2, "high": h, "low": l,
                          "close": (h + l) / 2, "volume": 1.0} for i, (h, l) in enumerate(rows)])


class MeasureTest(unittest.TestCase):
    def test_a_winner_against_then_with_you_until_the_target(self):
        out = excursion.measure("long", 100.0, 99.0, 102.0, bars([(100.5, 99.6), (101.0, 99.5), (102.3, 100.0), (110.0, 90.0)]))
        self.assertAlmostEqual(out["mae_r"], 0.5)
        self.assertAlmostEqual(out["mfe_r"], 2.0)          # tot het doel: na de uitkomst telt niets meer

    def test_a_loser_counts_the_stop_as_one_r_against(self):
        out = excursion.measure("long", 100.0, 99.0, 102.0, bars([(100.8, 99.7), (100.2, 98.5), (105.0, 98.0)]))
        self.assertAlmostEqual(out["mae_r"], 1.0)
        self.assertAlmostEqual(out["mfe_r"], 0.8)          # de stopcandle telt niet voor de meebeweging

    def test_short_is_mirrored(self):
        out = excursion.measure("short", 100.0, 101.0, 98.0, bars([(100.3, 99.4), (100.1, 97.9)]))
        self.assertAlmostEqual(out["mae_r"], 0.3)
        self.assertAlmostEqual(out["mfe_r"], 2.0)

    def test_without_a_target_it_runs_to_the_end_of_the_candles(self):
        out = excursion.measure("long", 100.0, 99.0, None, bars([(100.5, 99.6), (103.0, 100.0)]))
        self.assertAlmostEqual(out["mfe_r"], 3.0)

    def test_no_candles_or_no_risk_measures_nothing(self):
        self.assertIsNone(excursion.measure("long", 100.0, 99.0, 102.0, bars([])))
        self.assertIsNone(excursion.measure("long", 100.0, 100.0, 102.0, bars([(101.0, 99.0)])))

    def test_target_after_stop(self):
        self.assertTrue(excursion.target_reached("long", 102.0, bars([(101.0, 98.0), (102.1, 100.0)])))
        self.assertFalse(excursion.target_reached("short", 98.0, bars([(101.0, 98.5)])))


def done(trade_type, outcome, mae, mfe=1.0):
    return {"trade_type": trade_type, "auto_outcome": outcome, "price": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "mae_r": mae, "mfe_r": mfe}


class StatsTest(unittest.TestCase):
    def test_median_and_p75_per_type_for_winners_and_losers(self):
        rows = [done("zone_radar", "take_profit", m) for m in (0.2, 0.4, 0.6, 0.8)] + [done("zone_radar", "stop_loss", 1.0, 0.3)]
        rows += [done("zone_radar", "take_profit", None), done("zone_radar", None, 0.1)]   # niet gemeten, niet afgerond
        s = excursion.stats(rows)["zone_radar"]
        self.assertEqual((s["n"], s["win_n"], s["loss_n"], s["unmeasured"]), (5, 4, 1, 1))
        self.assertAlmostEqual(s["win_mae_med"], 0.5)
        self.assertAlmostEqual(s["win_mae_p75"], 0.65)
        self.assertAlmostEqual(s["loss_mfe_med"], 0.3)

    def test_the_bewijs_line_is_a_measurement_without_advice(self):
        rows = [done("structuur", "take_profit", m) for m in (0.3, 0.4, 0.5)]
        line = excursion.line(excursion.stats(rows)["structuur"])
        self.assertEqual(line, "Winnaars gingen eerst mediaan 0,4 R tegen je in (3 gemeten).")

    def test_no_winners_yet(self):
        self.assertEqual(excursion.line(excursion.stats([done("structuur", "stop_loss", 1.0)])["structuur"]),
                         "Nog geen gemeten winnaar.")


class MaeCheckScriptTest(unittest.TestCase):
    """scripts/mae_check.py: rekent achteraf op candles, alleen-lezen, en telt stops die binnen 24 uur toch het doel haalden."""

    def test_measure_row_uses_candles_after_the_signal_until_the_outcome(self):
        row = {**done("zone_radar", "stop_loss", None), "direction": "long", "created_at": "2026-10-30T10:00:00+00:00",
               "auto_outcome_at": "2026-10-30T10:05:00+00:00", "r_override": None}
        frame = bars([(100.5, 99.9), (100.6, 99.5), (100.4, 98.9), (102.5, 100.0)], start=datetime(2026, 10, 30, 9, 55, tzinfo=timezone.utc))
        out = excursion.measure_row(row, frame)
        self.assertAlmostEqual(out["mae_r"], 1.0)
        self.assertAlmostEqual(out["mfe_r"], 0.6)            # de candle van 09:55 opende vóór het signaal en telt niet
        self.assertTrue(out["stop_then_target"])             # 10:15 haalde 102 na de stop

    def test_a_stop_without_target_has_no_later_target(self):
        row = {**done("zone_sweep", "stop_loss", None), "take_profit": None, "direction": "long", "created_at": "2026-10-30T10:00:00+00:00",
               "auto_outcome_at": "2026-10-30T10:05:00+00:00", "r_override": -1.0}
        out = excursion.measure_row(row, bars([(100.2, 99.8), (100.0, 98.9), (105.0, 99.0)], start=datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)))
        self.assertIsNone(out["stop_then_target"])

    def test_report_counts_stops_that_reached_the_target_later(self):
        rows = [{**done("zone_radar", "stop_loss", 1.0), "stop_then_target": t} for t in (True, False, None)]
        s = excursion.stats(rows)["zone_radar"]
        self.assertEqual((s["stops_checked"], s["stops_then_target"]), (2, 1))


class LevelCheckStoresExcursionTest(DbCase):
    def test_the_outcome_check_stores_mae_and_mfe(self):
        sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "zone_radar", "price": 100.0,
                                  "stop_loss": 99.0, "take_profit": 102.0, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}, chain_it=False)
        created = datetime.now(timezone.utc) - timedelta(minutes=60)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?", (created.isoformat(), sid))
        frame = bars([(100.3, 99.4), (101.0, 99.8), (102.4, 100.5), (100.0, 95.0)], start=created + timedelta(minutes=5))
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: frame):
            asyncio.run(level_check.check_signal_outcomes())
        self.assertEqual(repo.get_signal(sid)["auto_outcome"], "take_profit")
        x = repo.get_trade_excursion(sid)
        self.assertAlmostEqual(x["mae_r"], 0.6)
        self.assertAlmostEqual(x["mfe_r"], 2.0)
        self.assertEqual(x["timeframe"], "5m")


class FollowStoresExcursionTest(EngineCase):
    _flat_market = FollowEngineTest._flat_market
    _synthetic_long = FollowEngineTest._synthetic_long

    def test_a_reference_exit_stores_the_excursion_once(self):
        sid = self._synthetic_long()
        self.run_(__import__("app.range_sweep_live", fromlist=["follow"]).follow, pd.Timestamp("2025-03-15 00:05", tz="UTC"))
        x = repo.get_trade_excursion(sid)
        self.assertIsNotNone(x)
        self.assertGreaterEqual(x["mae_r"], 0.0)
        self.assertEqual(x["timeframe"], "15m")


class BewijsShowsExcursionTest(Base):
    def test_the_focus_type_shows_the_mae_line(self):
        for mae in (0.3, 0.4, 0.5):
            sid = signal("SOL", "zone_radar", "take_profit")
            repo.set_trade_excursion(sid, mae, 1.5, "5m")
        html = self.client.get("/bewijs").text
        self.assertIn("Winnaars gingen eerst mediaan 0,4 R tegen je in (3 gemeten).", html)


if __name__ == "__main__":
    unittest.main()
