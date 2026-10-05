import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import pandas as pd

from app import config, db, quality_report, repo


def _row(trade_type, outcome, price=100.0, stop=99.0, take=102.0, message_id=None):
    return {"message_id": message_id, "trade_type": trade_type, "auto_outcome": outcome, "price": price,
            "stop_loss": stop, "take_profit": take, "created_at": "2026-10-01T00:00:00+00:00"}


class PureFunctionTests(unittest.TestCase):
    def test_r_van_een_afgerond_signaal(self):
        self.assertEqual(quality_report._r_of(_row("smc", "take_profit")), 2.0)
        self.assertEqual(quality_report._r_of(_row("smc", "stop_loss")), -1.0)
        self.assertIsNone(quality_report._r_of(_row("smc", "vervallen")))
        self.assertIsNone(quality_report._r_of(_row("smc", None)))
        self.assertIsNone(quality_report._r_of(_row("smc", "take_profit", stop=100.0)))  # geen stopafstand

    def test_scan_stats_telt_alleen_scansignalen(self):
        rows = [_row("smc", "take_profit"), _row("smc", "stop_loss"), _row("smc", "vervallen"),
                _row("smc", "take_profit", message_id=5), _row("patroon", "stop_loss")]
        stats = quality_report.scan_stats(rows)
        self.assertEqual((stats["smc"]["tp"], stats["smc"]["sl"], stats["smc"]["other"]), (1, 1, 1))
        self.assertEqual(stats["patroon"]["sl"], 1)
        self.assertAlmostEqual(sum(stats["smc"]["r"]) / 2, 0.5)

    def test_oordeel(self):
        few = {"alle": {"n": 10}}
        self.assertIn("Te weinig", quality_report.verdict(few))
        no_data = {"alle": {"n": 80}}
        self.assertIn("ontbreken", quality_report.verdict(no_data))
        good = {"alle": {"n": 80, "t": 2.5, "trades": {"net": 0.2}}}
        self.assertIn("lijkt een voorsprong", quality_report.verdict(good))
        weak_t = {"alle": {"n": 80, "t": 1.0, "trades": {"net": 0.2}}}
        self.assertIn("Geen voorsprong", quality_report.verdict(weak_t))
        negative = {"alle": {"n": 80, "t": 3.0, "trades": {"net": -0.1}}}
        self.assertIn("Geen voorsprong", quality_report.verdict(negative))


class BuildReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "t.db"))
        self.patch.start()
        db.init_db()
        with db.session() as conn:
            for trade_type, outcome in (("smc", "take_profit"), ("smc", "stop_loss"), ("patroon", "stop_loss")):
                conn.execute(
                    """INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price,
                       stop_loss, take_profit, auto_outcome, trade_type, created_at)
                       VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, ?, ?, ?)""",
                    (outcome, trade_type, "2026-10-01T00:00:00+00:00"))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_rapport_zonder_community_berichten(self):
        title, body = quality_report.build_report(datetime(2026, 10, 5, 12, tzinfo=timezone.utc), frames={})
        self.assertIn("05-10-2026", title)
        self.assertIn("smc: 2 afgerond, 1 winst", body)
        self.assertIn("patroon: 1 afgerond, 0 winst", body)
        self.assertIn("geen berichten met coin en richting", body)

    def test_rapport_met_community_en_run_schrijft_melding(self):
        from tests.replay.fixtures import make_smc_prone_1m
        frame = make_smc_prone_1m(days=40, start="2026-09-01", seed=3, spike_prob=0.01, spike_scale=0.01)
        with db.session() as conn:
            for i in range(10):
                at = (frame["timestamp"].iloc[3000 + i * 400]).isoformat()
                conn.execute("INSERT INTO messages (received_at, raw_text, coin, direction, category, unclear) VALUES (?, 'x', 'BTC', ?, 'day_trading', 0)",
                             (at, "long" if i % 2 else "short"))
        title, body = quality_report.build_report(datetime(2026, 10, 5, 12, tzinfo=timezone.utc), frames={"BTC": frame})
        self.assertIn("Community-calls (sinds", body)
        self.assertIn("onafhankelijke calls", body)
        self.assertIn("Te weinig onafhankelijke calls", body)
        with mock.patch.object(quality_report, "build_report", return_value=(title, body)):
            quality_report.run(None)
        with db.session() as conn:
            rows = conn.execute("SELECT type, user_id, title FROM notifications").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "quality_report")
        self.assertIsNone(rows[0]["user_id"])

    def test_onbekende_gebruiker_geeft_admin_melding_en_candles_alleen_voor_coins_met_genoeg_calls(self):
        calls = pd.DataFrame({"coin": ["BTC"] * 9 + ["ETH"] * 2, "at": pd.date_range("2026-09-10", periods=11, freq="D", tz="UTC")})
        seen = []

        def fake_update(coin, first, timeframe):
            seen.append((coin, first))
            return pd.DataFrame({"timestamp": []})

        with mock.patch.object(quality_report.candles, "update_candles", side_effect=fake_update):
            frames = quality_report.load_frames(calls, pd.Timestamp("2026-10-05", tz="UTC"))
        self.assertEqual([c for c, _ in seen], ["BTC"])
        self.assertEqual(seen[0][1], pd.Timestamp("2026-09-10", tz="UTC"))
        self.assertEqual(list(frames), ["BTC"])
        with mock.patch.object(quality_report, "build_report", return_value=("t", "b")):
            quality_report.run("bestaat-niet")
        with db.session() as conn:
            self.assertIsNone(conn.execute("SELECT user_id FROM notifications").fetchone()["user_id"])


class UpdateCandlesTests(unittest.TestCase):
    def test_nieuwe_cache_en_aanvullen(self):
        import pathlib
        from app.replay import candles
        base = pd.DataFrame({"timestamp": pd.date_range("2026-09-01", periods=60, freq="1min", tz="UTC"),
                             "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
        with tempfile.TemporaryDirectory() as d, mock.patch.object(candles, "CACHE_DIR", pathlib.Path(d)):
            calls = []

            def fake_download(coin, years, fetch=None, now=None, timeframe="15m", since_ts=None):
                calls.append(since_ts)
                return base[base["timestamp"] >= since_ts].reset_index(drop=True)

            with mock.patch.object(candles, "download_candles", side_effect=fake_download):
                first = candles.update_candles("BTC", pd.Timestamp("2026-09-03", tz="UTC"), "1m")
                self.assertEqual(calls[0], pd.Timestamp("2026-09-01", tz="UTC"))  # twee dagen eerder
                self.assertEqual(len(first), 60)
                again = candles.update_candles("BTC", pd.Timestamp("2026-09-03", tz="UTC"), "1m")
                self.assertEqual(calls[1], pd.Timestamp("2026-09-01 00:59:00", tz="UTC") + pd.Timedelta(minutes=1))
                self.assertEqual(len(again), 60)  # niets nieuws, geen dubbelen


if __name__ == "__main__":
    unittest.main()
