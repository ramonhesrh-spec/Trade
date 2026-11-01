"""Reproducties van de externe review (2026-10-31): elk geval faalde vóór zijn reparatie."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import db, level_check, repo
from tests.test_samenval import DbCase


class ResolvedSignalIsNeverUpdatedTest(DbCase):
    def _open_day_trade(self) -> int:
        sid = self.insert_signal(trade_type="day_trading")
        uid = repo.list_users()[0]["id"]
        repo.create_journal_entry(sid, uid, None)
        return sid

    def test_find_open_signal_skips_a_signal_with_an_outcome(self):
        sid = self._open_day_trade()
        self.assertEqual(repo.find_open_signal("BTC", "long")["id"], sid)
        repo.mark_signal_auto_outcome(sid, "stop_loss", db.now_iso())
        self.assertIsNone(repo.find_open_signal("BTC", "long"))

    def test_update_signal_leaves_a_resolved_plan_alone(self):
        sid = self._open_day_trade()
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        data = dict(repo.get_signal(sid))
        data.update(price=50.0, stop_loss=40.0, take_profit=70.0)
        repo.update_signal(sid, data)
        after = repo.get_signal(sid)
        self.assertEqual((after["price"], after["stop_loss"], after["take_profit"]), (100.0, 99.0, 102.0))


def _bars(start: datetime, rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(minutes=5 * i)), "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
                         for i, (o, h, l, c) in enumerate(rows)])


class TakenTradeCase(DbCase):
    """level_check.check_open_trades: de stop-/doelmelding voor een genomen trade."""

    def setUp(self):
        super().setUp()
        self.sent = []

    async def _push(self, user_id, title, body, url, silent=False, **kw):
        self.sent.append((title, body))

    def _taken(self, minutes_ago: float) -> int:
        sid = self.insert_signal(trade_type="zone_radar")
        created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?", (created.isoformat(), sid))
        uid = repo.list_users()[0]["id"]
        entry = repo.create_journal_entry(sid, uid, None)
        repo.update_journal_status(entry, uid, "genomen", 100.0)
        return entry

    def _run(self, frame, push=None):
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: frame), \
                mock.patch.object(level_check.push_notify, "send_push", push or self._push):
            asyncio.run(level_check.check_open_trades())

    def _alert_sent(self, entry_id: int) -> int:
        with db.session() as conn:
            return conn.execute("SELECT level_alert_sent FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()[0]


class OpenTradeAlertTest(TakenTradeCase):

    def test_a_stop_touch_before_the_signal_existed_does_not_alert(self):
        entry = self._taken(minutes_ago=12)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        # Eerste candle (30 min geleden, vóór het signaal) raakte de stop; daarna rustig.
        self._run(_bars(start, [(100, 100.2, 98.5, 100.0)] + [(100, 100.3, 99.6, 100.1)] * 5))
        self.assertEqual(self.sent, [])
        self.assertEqual(self._alert_sent(entry), 0)

    def test_the_candle_that_overlaps_the_signal_moment_does_not_count(self):
        self._taken(minutes_ago=12)
        start = datetime.now(timezone.utc) - timedelta(minutes=15)       # opent 3 minuten vóór het signaal
        self._run(_bars(start, [(100, 100.2, 98.5, 100.0)] + [(100, 100.3, 99.6, 100.1)] * 2))
        self.assertEqual(self.sent, [])

    def test_a_stop_touch_after_the_signal_still_alerts(self):
        entry = self._taken(minutes_ago=40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._run(_bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 100.2, 98.5, 99.0)] + [(99, 99.5, 98.8, 99.1)] * 2))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self._alert_sent(entry), 1)

    def test_stop_and_target_in_one_candle_says_order_unknown(self):
        self._taken(minutes_ago=40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._run(_bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 102.5, 98.5, 100.0)]))
        title, body = self.sent[0]
        self.assertIn("Stop loss geraakt", body)
        self.assertIn(level_check.AMBIGUOUS_NOTE, body)

    def test_a_clean_stop_does_not_say_order_unknown(self):
        self._taken(minutes_ago=40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._run(_bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 100.2, 98.5, 99.0)]))
        self.assertNotIn(level_check.AMBIGUOUS_NOTE, self.sent[0][1])

    def test_the_alert_names_the_level_not_the_candle_extreme(self):
        self._taken(minutes_ago=40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._run(_bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 100.2, 98.5, 99.0)]))
        body = self.sent[0][1]
        self.assertIn("Stop 99.0000", body)
        self.assertIn("koers raakte 98.5000", body)
        self.assertNotIn("Op 98.5000", body)

    def test_a_target_alert_names_the_target(self):
        self._taken(minutes_ago=40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self._run(_bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 102.7, 99.9, 102.4)]))
        body = self.sent[0][1]
        self.assertIn("Doel 102.0000", body)
        self.assertIn("koers raakte 102.7000", body)


class FailedLevelAlertIsRetriedTest(TakenTradeCase):
    def _stop_frame(self):
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        return _bars(start, [(100, 100.3, 99.6, 100.1)] * 3 + [(100, 100.2, 98.5, 99.0)])

    async def _boom(self, *a, **k):
        raise RuntimeError("netwerk weg")

    async def _devices_failed(self, *a, **k):
        return "1 van 1 apparaten mislukt"

    def test_a_raised_send_leaves_the_flag_and_logs_the_attempt(self):
        entry = self._taken(minutes_ago=40)
        self._run(self._stop_frame(), push=self._boom)
        self.assertEqual(self._alert_sent(entry), 0)
        attempts = repo.list_push_attempts("niveau", f"journal:{entry}")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["ok"], 0)
        self.assertIn("netwerk weg", attempts[0]["error"])

    def test_a_send_that_reached_no_device_is_retried(self):
        entry = self._taken(minutes_ago=40)
        self._run(self._stop_frame(), push=self._devices_failed)
        self.assertEqual(self._alert_sent(entry), 0)
        self._run(self._stop_frame())
        self.assertEqual(self._alert_sent(entry), 1)
        self.assertEqual([a["ok"] for a in repo.list_push_attempts("niveau", f"journal:{entry}")], [0, 1])

    def test_after_the_maximum_attempts_the_flag_is_set(self):
        entry = self._taken(minutes_ago=40)
        for _ in range(level_check.MAX_LEVEL_ALERT_ATTEMPTS):
            self._run(self._stop_frame(), push=self._boom)
        self.assertEqual(self._alert_sent(entry), 1)
        self.assertEqual(len(repo.list_push_attempts("niveau", f"journal:{entry}")), level_check.MAX_LEVEL_ALERT_ATTEMPTS)


class SendPushReportsFailureTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.list_users()[0]["id"]
        repo.upsert_push_subscription(self.uid, "https://push.example/1", "p", "a")

    def _send(self, send_one):
        from app import config, push_notify
        with mock.patch.object(config, "VAPID_PRIVATE_KEY", "k"), mock.patch.object(push_notify, "_send_one", send_one):
            return asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))

    def test_every_device_failing_returns_the_error(self):
        def fail(sub, payload):
            raise RuntimeError("503")
        self.assertIn("503", self._send(fail))

    def test_a_delivered_push_returns_none(self):
        self.assertIsNone(self._send(lambda sub, payload: None))

    def test_a_failed_kans_push_lands_on_the_notifications_page(self):
        from app import push_notify

        async def failed(*a, **k):
            return "1 van 1 apparaten mislukt: 503"
        with mock.patch.object(push_notify, "send_push", failed):
            asyncio.run(push_notify.send_kans_push(self.uid, "BTC", "long", "Titel", "Tekst", "/smc"))
        notes = repo.list_notifications(self.uid)
        self.assertEqual(len(notes), 1)
        self.assertIn("kwam niet aan", notes[0]["body"])
        attempts = repo.list_push_attempts("kans", "/smc")
        self.assertEqual([(a["user_id"], a["ok"]) for a in attempts], [(self.uid, 0)])


class EngineAnnounceRecordsFailureTest(DbCase):
    """De claim (alert_sent eerst) blijft: een mislukte verzending wordt per gebruiker vastgelegd in push_attempts."""

    async def _boom(self, *a, **k):
        raise RuntimeError("stuk")

    def test_zone_radar_new_card(self):
        from app import zone_radar_live
        card = {"id": 7, "coin": "BTC", "direction": "long", "tf": "1h", "zone_low": 99.0, "zone_high": 100.0, "stop_loss": 98.0,
                "take_profit": 104.0, "rr": 4.0, "target_tf": "1h"}
        with mock.patch.object(repo, "mark_zone_radar_alert_sent", lambda i: True), \
                mock.patch.object(zone_radar_live, "new_card_body", lambda c: "x"), \
                mock.patch("app.push_notify.send_kans_push", self._boom):
            asyncio.run(zone_radar_live._push_new_card(card))
        attempts = repo.list_push_attempts("kans", zone_radar_live.card_url(7))
        self.assertEqual(len(attempts), 1)
        self.assertIn("stuk", attempts[0]["error"])


class PatternScoreIsNotAChanceTest(unittest.TestCase):
    """repo.pattern_kansberekening is (factoren + historische winrate)/2: een samengestelde score, geen gemeten winkans."""

    def _card(self) -> str:
        from web import main
        entry = {"id": 1, "signal_id": 1, "coin": "BTC", "direction": "long", "trade_type": "patroon", "pattern_name": "Vlag",
                 "success_rate": 72.0, "user_confirmed": False, "pass_pct": 80.0, "reason": "✓ a | ✗ b", "price": 100.0,
                 "stop_loss": 99.0, "take_profit": 102.0, "auto_outcome": None, "created_at": db.now_iso()}
        return main.templates.env.from_string('{% import "_macros.html" as m %}{{ m.signal_card(e) }}').render(e=entry)

    def test_the_pattern_card_calls_it_a_score(self):
        html = self._card()
        self.assertNotIn("kans 72%", html)
        self.assertIn("score 72", html)


class FastCycleTimingTest(DbCase):
    """scan_smc_fast schrijft in zijn hartslag hoe laat na het 5m-slot hij begon en hoe lang hij duurde (deploy timer *:0/5:20)."""

    def test_seconds_after_the_five_minute_slot(self):
        from app import market_scanner
        self.assertEqual(market_scanner.seconds_after_slot(datetime(2026, 10, 31, 12, 8, 7, tzinfo=timezone.utc)), 187.0)
        self.assertEqual(market_scanner.seconds_after_slot(datetime(2026, 10, 31, 12, 10, 0, tzinfo=timezone.utc)), 0.0)

    def test_the_cycle_writes_its_timing_even_when_the_scan_is_off(self):
        from app import market_scanner

        async def nothing():
            return None
        with mock.patch.object(market_scanner.announce_live, "run", nothing), \
                mock.patch.object(repo, "is_market_scan_enabled", lambda: False):
            asyncio.run(market_scanner.scan_smc_fast())
        detail = repo.get_beat(market_scanner.FAST_CYCLE_BEAT)["detail"]
        self.assertRegex(detail, r"start \d+ s na het 5m-slot, duur \d+ s")


@unittest.skipUnless(__import__("shutil").which("node"), "node ontbreekt")
class LiveFreshnessPerCoinTest(unittest.TestCase):
    """live.js hield één gedeeld tijdstip (__liveAt) voor alle coins: één tikkende coin liet een stille coin vers lijken."""

    def test_freshness_is_per_coin(self):
        from tests.test_static_js import run_node
        out = run_node("live_harness.js", "live.js")
        self.assertEqual((out["btc"], out["eth"], out["sol"]), (True, False, False))
        self.assertFalse(out["all"])                       # zonder coin: pas vers als elke coin op de pagina vers is
        self.assertTrue(out["allFresh"])
        self.assertFalse(out["none"])

    def test_the_dot_follows_the_stalest_shown_price(self):
        from tests.test_static_js import run_node
        out = run_node("live_harness.js", "live.js")
        self.assertEqual(out["shownStalest"], 80000)       # ETH, niet de verse BTC
        self.assertEqual(out["shownPollHelps"], 95000)     # een verse poll dekt beide coins
        self.assertEqual(out["shownOnlyPoll"], 93000)
        self.assertIsNone(out["shownNothing"])


class AmbiguousOutcomeIsStoredTest(DbCase):
    def _run_outcomes(self, frame):
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: frame):
            asyncio.run(level_check.check_signal_outcomes())

    def _signal(self, minutes_ago: float) -> int:
        sid = self.insert_signal(direction="long", price=100.0, stop_loss=99.0, take_profit=102.0)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(), sid))
        return sid

    def test_both_levels_in_one_candle_is_stop_with_a_note(self):
        sid = self._signal(60)
        start = datetime.now(timezone.utc) - timedelta(minutes=50)
        self._run_outcomes(_bars(start, [(100, 102.5, 98.5, 100.0)] + [(100, 100.2, 99.9, 100.0)] * 8))
        signal = repo.get_signal(sid)
        self.assertEqual(signal["auto_outcome"], "stop_loss")
        self.assertEqual(signal["auto_outcome_note"], level_check.AMBIGUOUS_NOTE)

    def test_a_clean_stop_has_no_note(self):
        sid = self._signal(60)
        start = datetime.now(timezone.utc) - timedelta(minutes=50)
        self._run_outcomes(_bars(start, [(100, 100.2, 98.5, 99.0)] + [(100, 100.2, 99.9, 100.0)] * 8))
        self.assertIsNone(repo.get_signal(sid)["auto_outcome_note"])


if __name__ == "__main__":
    unittest.main()
