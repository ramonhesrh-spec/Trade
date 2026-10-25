"""De ophaler van de marktcontext (app/market_context_live.py) en de opslag (repo): bronnen met hun eigen cache, een falende bron laat de oude waarde
staan, de scan wacht nooit langer dan de grens, en de HTTP-laag geeft bij elke fout None in plaats van een uitzondering."""
import asyncio
import os
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import config, db, repo
from app import market_context_live as live
from tests import market_context_fixtures as fx

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class DbCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patches = [mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "m.db")),
                   mock.patch.object(config, "MARKET_CONTEXT_ENABLED", True),
                   mock.patch.object(repo, "list_coins", return_value=[{"symbol": "BTC"}, {"symbol": "ETH"}, {"symbol": "SOL"}])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init_db()


class RepoTests(DbCase):
    def test_latest_per_coin_source_and_metric(self):
        repo.add_market_context([("BTC", "binance", "funding_8h", 0.01, "2026-10-25T11:00:00+00:00"),
                                 ("BTC", "binance", "funding_8h", 0.02, "2026-10-25T11:55:00+00:00"),
                                 ("ETH", "okx", "funding_8h", 0.03, "2026-10-25T11:55:00+00:00"),
                                 ("markt", "alternative", "fear_greed", 38.0, "2026-10-25T08:00:00+00:00")])
        rows = repo.latest_market_context(["BTC", "markt"])
        self.assertEqual({(r["coin"], r["bron"], r["metric"], r["waarde"]) for r in rows},
                         {("BTC", "binance", "funding_8h", 0.02), ("markt", "alternative", "fear_greed", 38.0)})
        self.assertEqual(repo.market_context_last_at("binance"), "2026-10-25T11:55:00+00:00")
        self.assertIsNone(repo.market_context_last_at("bybit"))

    def test_migration_adds_snapshot_columns_to_an_existing_table(self):
        with db.session() as conn:
            conn.execute("ALTER TABLE zone_radar_setups RENAME TO zr_old")
            conn.execute("CREATE TABLE zone_radar_setups (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, zone_key TEXT, signal_id INTEGER, state TEXT)")
        db.init_db()
        db.init_db()                                                        # idempotent
        with db.session() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(zone_radar_setups)")}
        self.assertTrue({"ctx_funding", "ctx_oi_change_24h", "ctx_spread"} <= cols)

    def test_series_and_prune(self):
        repo.add_market_context([("BTC", "hyperliquid", "oi_usd", 1.0, "2026-09-01T00:00:00+00:00"),
                                 ("BTC", "hyperliquid", "oi_usd", 2.0, "2026-10-24T12:00:00+00:00")])
        self.assertEqual(repo.market_context_series("BTC", "hyperliquid", "oi_usd", "2026-10-01T00:00:00+00:00"),
                         [("2026-10-24T12:00:00+00:00", 2.0)])
        repo.prune_market_context("2026-10-01T00:00:00+00:00")
        self.assertEqual(len(repo.market_context_series("BTC", "hyperliquid", "oi_usd", "2000-01-01")), 1)


def fixtures():
    return {
        "fetch_binance_premium": fx.BINANCE_PREMIUM, "fetch_binance_funding_info": fx.BINANCE_FUNDING_INFO,
        "fetch_binance_oi": fx.BINANCE_OI_HIST, "fetch_hyperliquid": fx.HYPERLIQUID, "fetch_bybit": fx.BYBIT,
        "fetch_okx": fx.OKX_BTC, "fetch_fear_greed": fx.FEAR_GREED, "fetch_stablecoins": fx.STABLECOINS,
    }


class LiveTests(DbCase):
    def setUp(self):
        super().setUp()
        self.answers = fixtures()
        self.calls = []
        for name in self.answers:
            p = mock.patch.object(live, name, side_effect=self._answer(name))
            p.start()
            self.addCleanup(p.stop)

    def _answer(self, name):
        def fn(*args):
            self.calls.append(name)
            value = self.answers[name]
            if isinstance(value, Exception):
                raise value
            return value
        return fn

    def run_at(self, now):
        return asyncio.run(live.run(now))

    def metrics(self):
        return {(r["coin"], r["bron"], r["metric"]) for r in repo.latest_market_context(["BTC", "ETH", "SOL", "markt"])}

    def test_writes_every_source_and_beats(self):
        self.run_at(NOW)
        got = self.metrics()
        for key in [("BTC", "binance", "funding_8h"), ("BTC", "binance", "oi_change_24h"), ("SOL", "hyperliquid", "funding_8h"),
                    ("ETH", "bybit", "funding_8h"), ("BTC", "okx", "funding_8h"), ("markt", "alternative", "fear_greed"),
                    ("markt", "defillama", "stablecoin_usd"), ("markt", "defillama", "stablecoin_change_7d")]:
            self.assertIn(key, got)
        beat = repo.get_beat("marktcontext")
        self.assertIsNotNone(beat)
        self.assertIn("6 van 6 bronnen", beat["detail"])

    def test_each_source_keeps_its_own_cache(self):
        self.run_at(NOW)
        self.calls.clear()
        self.run_at(NOW + timedelta(minutes=2))
        self.assertEqual(self.calls, [])                                   # alles nog vers
        self.run_at(NOW + timedelta(minutes=6))
        self.assertIn("fetch_bybit", self.calls)
        self.assertNotIn("fetch_fear_greed", self.calls)                   # 6 uur cache
        self.assertNotIn("fetch_stablecoins", self.calls)
        self.calls.clear()
        self.run_at(NOW + timedelta(hours=7))
        self.assertIn("fetch_fear_greed", self.calls)

    def test_failing_source_keeps_old_value_with_its_time(self):
        self.run_at(NOW)
        self.answers["fetch_bybit"] = None
        self.answers["fetch_hyperliquid"] = RuntimeError("kapot")         # een uitzondering in een ophaler blijft binnen
        later = NOW + timedelta(minutes=6)
        with self.assertLogs("market_context_live", "ERROR"):
            self.run_at(later)
        rows = {(r["coin"], r["bron"], r["metric"]): r for r in repo.latest_market_context(["ETH", "BTC"])}
        self.assertEqual(rows[("ETH", "bybit", "funding_8h")]["gemeten_op"], NOW.isoformat())
        self.assertEqual(rows[("BTC", "binance", "funding_8h")]["gemeten_op"], later.isoformat())
        detail = repo.get_beat("marktcontext")["detail"]
        self.assertEqual(detail, "2 van 4 bronnen, mislukt: hyperliquid, bybit")     # de trage bronnen waren nog niet aan de beurt

    def test_hyperliquid_oi_change_from_own_history(self):
        repo.add_market_context([("BTC", "hyperliquid", "oi_usd", 28012.34 * 67410.0 / 1.1, (NOW - timedelta(hours=24, minutes=5)).isoformat())])
        self.run_at(NOW)
        row = next(r for r in repo.latest_market_context(["BTC"]) if r["bron"] == "hyperliquid" and r["metric"] == "oi_change_24h")
        self.assertAlmostEqual(row["waarde"], 10.0)

    def test_disabled_does_nothing(self):
        with mock.patch.object(config, "MARKET_CONTEXT_ENABLED", False):
            self.run_at(NOW)
        self.assertEqual(self.calls, [])
        self.assertIsNone(repo.get_beat("marktcontext"))

    def test_slow_source_never_holds_the_scan(self):
        def slow(*args):
            time.sleep(1.0)
            return fx.BYBIT
        with mock.patch.object(live, "fetch_bybit", side_effect=slow), mock.patch.object(live, "RUN_TIMEOUT_S", 0.2):
            start = time.monotonic()
            self.run_at(NOW)
            self.assertLess(time.monotonic() - start, 0.9)
        self.assertNotIn(("ETH", "bybit", "funding_8h"), self.metrics())
        self.assertIn(("BTC", "binance", "funding_8h"), self.metrics())


class RequestTests(unittest.TestCase):
    def test_network_error_is_none(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("geen netwerk")), self.assertLogs("market_context_live", "WARNING"):
            self.assertIsNone(live._request("https://api.bybit.com/v5/market/tickers", {"category": "linear"}))

    def test_bad_json_is_none(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"<html>"
        with mock.patch("urllib.request.urlopen", return_value=resp), self.assertLogs("market_context_live", "WARNING"):
            self.assertIsNone(live._request("https://api.alternative.me/fng/"))

    def test_post_body_and_timeout(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = b"[1]"
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            self.assertEqual(live._request(live.HYPERLIQUID_URL, body={"type": "metaAndAssetCtxs"}), [1])
        req = urlopen.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.data, b'{"type": "metaAndAssetCtxs"}')
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)


if __name__ == "__main__":
    unittest.main()


class ScanWiringTests(unittest.TestCase):
    def test_scan_runs_context_and_survives_its_failure(self):
        from app import market_scanner as ms
        order = []

        async def boom():
            order.append("context")
            raise RuntimeError("kapot")

        async def zone():
            order.append("zone_radar")

        async def noop(*a, **k):
            return None

        patches = [mock.patch.object(ms.repo, "is_market_scan_enabled", return_value=True), mock.patch.object(ms.repo, "list_coins", return_value=[]),
                   mock.patch.object(ms.market_context_live, "run", side_effect=boom), mock.patch.object(ms.zone_radar_live, "run", side_effect=zone)]
        for mod, name in ((ms.samenval, "run"), (ms.market_script, "run_triggers"), (ms.calendar_alerts, "run"), (ms.trend_live, "run"),
                          (ms.rejection_live, "run"), (ms.rule_live, "scan"), (ms.range_watch, "run"), (ms.range_sweep_live, "scan"),
                          (ms.range_sweep_live, "track"), (ms.range_sweep_live, "follow"), (ms.structure_live, "run")):
            patches.append(mock.patch.object(mod, name, side_effect=noop))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with self.assertLogs("market_scanner", "ERROR"):
            asyncio.run(ms.scan_smc_fast())
        self.assertEqual(order, ["context", "zone_radar"])        # vóór de zone-radar klaar, zodat een nieuwe kaart een verse stand bewaart
