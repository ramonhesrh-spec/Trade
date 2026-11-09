"""Elke uitgezette motor zoekt met ENGINE_FOCUS aan niets nieuws en meldt niets; ENGINE_FOCUS=false geeft het oude gedrag terug. De gates
zitten op de aanroep (het begin van de motor), niet in de beslislogica: de golden tests van setup_eval, smc_eval en de day-trading-pipeline
merken er niets van."""
import asyncio
from datetime import datetime, timezone
from unittest import mock

from app import config, focus, level_check, market_scanner, market_script, range_sweep_live, range_watch, rejection_live, repo, rule_live
from app import samenval, signal_processor, trend_live
from tests.test_samenval import DbCase

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)      # minuut 0: de range-watch en de range sweep zoeken dan


def calls():
    seen = []

    async def fake(*a, **k):
        seen.append(a)
    return seen, fake


class EngineGateTest(DbCase):
    def assert_off(self, beat_name):
        self.assertEqual((repo.get_beat(beat_name) or {}).get("detail"), focus.OFF_DETAIL)

    def test_trend(self):
        seen, fake = calls()
        with mock.patch.object(trend_live, "_check", fake), mock.patch.object(config, "TREND_ENABLED", True), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]):
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                asyncio.run(trend_live.run(NOW))
            self.assertEqual(seen, [])
            self.assert_off("trend")
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                asyncio.run(trend_live.run(NOW))
            self.assertEqual([a[0] for a in seen], ["BTC"])

    def test_rejection(self):
        seen, fake = calls()
        with mock.patch.object(rejection_live, "_check", fake), mock.patch.object(config, "REJECTION_ENABLED", True), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]):
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                asyncio.run(rejection_live.run(NOW))
            self.assertEqual(seen, [])
            self.assert_off("rejectie")
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                asyncio.run(rejection_live.run(NOW))
            self.assertEqual([a[0] for a in seen], ["BTC"])

    def test_rule_live_scan_stops_but_update_open_follows(self):
        seen, fake = calls()
        lab = {"lab_passes": 1}
        stamp = datetime(2026, 10, 27, 12, 5, tzinfo=timezone.utc)      # net na het slot van een 4u-candle
        with mock.patch.object(rule_live, "_scan_coin", fake), mock.patch.object(repo, "get_rule_lab", lambda r: lab), \
                mock.patch.object(rule_live, "live_results", lambda: []):
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                asyncio.run(rule_live.scan(stamp))
            self.assertEqual(seen, [])
            self.assert_off(rule_live.RULE)
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                asyncio.run(rule_live.scan(stamp))
            self.assertEqual(len(seen), len(rule_live.COINS))
        followed, fake_update = calls()
        trade = {"signal_id": 1, "coin": "BTC"}
        with mock.patch.object(config, "ENGINE_FOCUS", True), mock.patch.object(rule_live, "_update_trade", fake_update), \
                mock.patch.object(repo, "list_open_rule_trades", lambda r: [trade]), mock.patch.object(rule_live, "live_results", lambda: []):
            asyncio.run(rule_live.update_open(stamp))
        self.assertEqual(len(followed), 1)

    def test_range_watch(self):
        seen, fake = calls()
        with mock.patch.object(range_watch, "_detect", fake), mock.patch.object(config, "RANGE_WATCH_ENABLED", True):
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                asyncio.run(range_watch.run(NOW))
            self.assertEqual(seen, [])
            self.assert_off("range_watch")
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                asyncio.run(range_watch.run(NOW))
            self.assertEqual(len(seen), len(range_watch.COINS))

    def test_range_sweep_scan_stops(self):
        seen = []

        async def fake(coin, stamp):
            seen.append(coin)
            return {}
        with mock.patch.object(range_sweep_live, "_frames", fake), mock.patch.object(range_sweep_live, "fresh_setups", lambda *a: []), \
                mock.patch.object(config, "RANGE_SWEEP_ENABLED", True), \
                mock.patch.object(config, "RANGE_SWEEP_UNTESTED", True):
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                asyncio.run(range_sweep_live.scan(NOW))
            self.assertEqual(seen, [])
            self.assert_off("range_sweep")
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                asyncio.run(range_sweep_live.scan(NOW))
            self.assertEqual(len(seen), len(range_sweep_live.COINS))

    def test_market_script_triggers_and_generation(self):
        fired, fake_fire = calls()
        generated = []
        expired = []
        with mock.patch.object(market_script, "_fire", fake_fire), mock.patch.object(config, "SCRIPT_ENABLED", True), \
                mock.patch.object(repo, "expire_scenarios", lambda at: expired.append(at)), \
                mock.patch.object(repo, "list_waiting_scenarios", lambda: [{"coin": "BTC"}]), \
                mock.patch.object(market_script, "generate_for_coin", lambda c: generated.append(c)), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]), \
                mock.patch("app.exchange.fetch_ohlcv", side_effect=RuntimeError("geen beurs in de test")):
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                self.assertEqual(asyncio.run(market_script.run_triggers(NOW)), 0)
                market_script.generate_all()
            self.assertEqual((fired, generated), ([], []))
            self.assertEqual(len(expired), 1)                   # verlopen scenario's ruimt hij nog op
            self.assert_off("script")
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                market_script.generate_all()
            self.assertEqual(generated, ["BTC"])

    def test_samenval(self):
        with mock.patch.object(config, "SAMENVAL_ENABLED", True), mock.patch.object(repo, "list_smc_signals_since") as smc:
            with mock.patch.object(config, "ENGINE_FOCUS", True):
                self.assertEqual(asyncio.run(samenval.run(NOW)), 0)
            smc.assert_not_called()
            smc.return_value = []
            with mock.patch.object(config, "ENGINE_FOCUS", False):
                asyncio.run(samenval.run(NOW))
            smc.assert_called_once()


class FastCycleTest(DbCase):
    def run_fast(self, focus_on):
        ran = []

        def step(name):
            async def fake(*a, **k):
                ran.append(name)
            return fake
        with mock.patch.object(config, "ENGINE_FOCUS", focus_on), mock.patch.object(repo, "is_market_scan_enabled", lambda: True), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]), \
                mock.patch.object(market_scanner, "_run_smc_check", step("smc")), \
                mock.patch.object(market_scanner.market_context_live, "run", step("context")), \
                mock.patch.object(market_scanner.calendar_alerts, "run", step("agenda")), \
                mock.patch.object(market_scanner.structure_live, "run", step("structuur")), \
                mock.patch.object(market_scanner.zone_radar_live, "run", step("zone_radar")), \
                mock.patch.object(market_scanner.samenval, "run", step("samenval")), \
                mock.patch.object(market_scanner.market_script, "run_triggers", step("script")), \
                mock.patch.object(market_scanner.trend_live, "run", step("trend")), \
                mock.patch.object(market_scanner.rejection_live, "run", step("rejectie")), \
                mock.patch.object(market_scanner.rule_live, "scan", step("rule")), \
                mock.patch.object(market_scanner.range_watch, "run", step("range_watch")), \
                mock.patch.object(market_scanner.range_sweep_live, "scan", step("rs_scan")), \
                mock.patch.object(market_scanner.range_sweep_live, "track", step("rs_track")), \
                mock.patch.object(market_scanner.range_sweep_live, "follow", step("rs_follow")):
            asyncio.run(market_scanner.scan_smc_fast())
        return ran

    def test_focus_skips_the_smc_check_and_keeps_focus_engines(self):
        ran = self.run_fast(True)
        self.assertNotIn("smc", ran)
        for name in ("structuur", "zone_radar", "context", "agenda", "rs_track", "rs_follow"):
            self.assertIn(name, ran)
        self.assertEqual((repo.get_beat("smc") or {}).get("detail"), focus.OFF_DETAIL)

    def test_focus_off_runs_the_smc_check_again(self):
        self.assertIn("smc", self.run_fast(False))


class ScanMarketTest(DbCase):
    """De 4u-scan: SMC, de drie structurele detectoren (patroon) en de autonome day-trading-melding zoeken niets nieuws; een al open
    day-trading-signaal wordt elke cyclus ververst zoals altijd."""

    def run_scan(self, focus_on, open_signal):
        seen = {"smc": 0, "find": 0, "day": 0}

        async def smc(coin):
            seen["smc"] += 1

        async def find(*a, **k):
            seen["find"] += 1
            return None

        async def day(*a, **k):
            seen["day"] += 1
        ind = mock.Mock(ema9=2.0, ema21=1.0, atr=1.0)
        with mock.patch.object(config, "ENGINE_FOCUS", focus_on), mock.patch.object(repo, "is_market_scan_enabled", lambda: True), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]), mock.patch.object(config, "EXTRA_COINS", []), \
                mock.patch.object(market_scanner, "_run_smc_check", smc), \
                mock.patch.object(market_scanner, "_find_breakout_retest_candidate", find), \
                mock.patch.object(market_scanner, "_find_trendline_retest_candidate", find), \
                mock.patch.object(market_scanner, "_find_chart_pattern_candidate", find), \
                mock.patch.object(market_scanner, "process_day_trading_signal", day), \
                mock.patch.object(market_scanner.exchange, "fetch_ohlcv", lambda *a, **k: None), \
                mock.patch.object(market_scanner.patterns, "find_divergence", lambda df: None), \
                mock.patch.object(market_scanner.patterns, "find_forming_wedge", lambda *a: None), \
                mock.patch.object(market_scanner.patterns, "find_forming_reversal_patterns", lambda df: []), \
                mock.patch.object(market_scanner.indicators, "compute_indicators", lambda df: ind), \
                mock.patch.object(market_scanner.indicators, "detect_trendlines", lambda *a: []), \
                mock.patch.object(market_scanner.indicators, "confirms_direction", lambda *a: (True, "", 100, True)), \
                mock.patch.object(repo, "find_open_signal", lambda c, d: {"id": 1} if open_signal else None), \
                mock.patch.object(repo, "record_scan_direction", lambda c, d: 99), \
                mock.patch.object(repo, "recent_autonomous_loss", lambda *a: False):
            asyncio.run(market_scanner.scan_market())
        return seen

    def test_focus_finds_nothing_new(self):
        self.assertEqual(self.run_scan(True, open_signal=False), {"smc": 0, "find": 0, "day": 0})

    def test_focus_still_refreshes_an_open_day_trading_signal(self):
        self.assertEqual(self.run_scan(True, open_signal=True)["day"], 1)

    def test_focus_off_is_the_old_scan(self):
        self.assertEqual(self.run_scan(False, open_signal=False), {"smc": 1, "find": 3, "day": 1})


class LevelCheckTest(DbCase):
    def run_checks(self, focus_on):
        ran = []

        def step(name):
            async def fake(*a, **k):
                ran.append(name)
            return fake
        with mock.patch.object(config, "ENGINE_FOCUS", focus_on), \
                mock.patch.object(level_check, "check_open_trades", step("open_trades")), \
                mock.patch.object(level_check, "check_price_alerts", step("price_alerts")), \
                mock.patch.object(level_check, "check_signal_outcomes", step("outcomes")), \
                mock.patch.object(level_check.rule_live, "update_open", step("rule_follow")), \
                mock.patch.object(level_check, "check_pending_signals", step("pending")), \
                mock.patch.object(level_check, "check_swing_watches", step("swing")), \
                mock.patch.object(level_check, "check_narratives", step("narratives")):
            asyncio.run(level_check.run_all_checks())
        return ran

    def test_open_trades_keep_being_followed_but_no_new_swing(self):
        ran = self.run_checks(True)
        for name in ("open_trades", "outcomes", "rule_follow", "pending", "price_alerts"):
            self.assertIn(name, ran)
        self.assertNotIn("swing", ran)

    def test_focus_off_checks_swing_watches_again(self):
        self.assertIn("swing", self.run_checks(False))


def message(message_id):
    from app import db
    with db.session() as conn:
        return dict(conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone())


class DiscordGateTest(DbCase):
    def handle(self, focus_on, text="BTC long entry 100"):
        message_id = repo.insert_message(text, [])
        with mock.patch.object(config, "ENGINE_FOCUS", focus_on), \
                mock.patch.object(signal_processor, "interpret_message", return_value=[]) as interp:
            asyncio.run(signal_processor.handle_message(message_id, text, []))
        return message_id, interp

    def test_focus_stores_the_message_without_interpreting_it(self):
        message_id, interp = self.handle(True)
        interp.assert_not_called()
        msg = message(message_id)
        self.assertIsNotNone(msg["processed_at"])
        self.assertIn(focus.OFF_DETAIL, msg["note"])
        self.assertEqual(repo.list_signals_for_quality_report(None), [])

    def test_duplicate_is_still_deduplicated_first(self):
        self.handle(True)
        message_id, _ = self.handle(True)
        msg = message(message_id)
        self.assertIsNotNone(msg["processed_at"])
        self.assertIsNone(msg["note"])            # het dedupe-pad, niet de focus-regel: dedupe gaat voor

    def test_focus_off_interprets_again(self):
        _, interp = self.handle(False)
        interp.assert_called_once()
