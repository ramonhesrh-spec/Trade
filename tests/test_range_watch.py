import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import config, db, push_notify, range_watch as rw, repo
from app.replay import rangesweep as rs
from tests.replay.rangesweep_fixtures import SWEEP_HOUR, frames
from tests.test_samenval import DbCase


def rng(high=110.0, low=100.0, atr=1.0, first="2026-10-01"):
    t = pd.Timestamp(first, tz="UTC")
    return rs.Range("4h", t, high, low, 3, 3, 0.0, 0.0, t, atr)


class RangeWatchTest(unittest.TestCase):
    def test_current_ranges_uses_closed_candles(self):
        b15, b1h, b4h = frames()
        now = b1h["timestamp"].iloc[SWEEP_HOUR]
        cut = lambda df: df[df["timestamp"] < now]
        cur = rw.current_ranges(rs.build_frames(cut(b15), cut(b1h), cut(b4h)), now)
        self.assertAlmostEqual(cur["1h"].high, 106.025)
        self.assertEqual(set(cur), set(rs.TFS))

    def test_current_ranges_ignores_a_forming_candle(self):
        b15, b1h, b4h = frames()
        now = b1h["timestamp"].iloc[SWEEP_HOUR]
        full = rw.current_ranges(rs.build_frames(b15, b1h, b4h), now)
        cut = lambda df, tf: rs.closed_only(df, now, tf)
        part = rw.current_ranges(rs.build_frames(cut(b15, "15m"), cut(b1h, "1h"), cut(b4h, "4h")), now)
        self.assertEqual({k: v and v.high for k, v in full.items()}, {k: v and v.high for k, v in part.items()})

    def test_edge_events_once_per_edge(self):
        w = {"range_high": 110.0, "range_low": 100.0, "atr": 1.0, "edge_high_at": None, "edge_low_at": None}
        self.assertEqual(rw.events(w, 109.8, rng()), ["rand_high"])
        self.assertEqual(rw.events({**w, "edge_high_at": "x"}, 109.8, rng()), [])
        self.assertEqual(rw.events(w, 105.0, rng()), [])
        self.assertEqual(rw.events(w, 100.1, rng()), ["rand_low"])
        self.assertEqual(rw.events(w, 105.0, None), ["einde"])

    def test_budget_and_small_timeframes(self):
        self.assertEqual(rw.should_push("gevonden", "4h", 0, 3), (True, ""))
        self.assertEqual(rw.should_push("gevonden", "2h", 0, 3), (True, ""))
        self.assertFalse(rw.should_push("gevonden", "30m", 0, 3)[0])
        ok, why = rw.should_push("rand_high", "1h", 3, 3)
        self.assertFalse(ok)
        self.assertIn("budget", why)

    def test_small_timeframe_edges_leave_the_last_slot_for_2h_and_4h(self):
        self.assertTrue(rw.should_push("rand_high", "1h", 1, 3)[0])
        ok, why = rw.should_push("rand_high", "30m", 2, 3)
        self.assertFalse(ok)
        self.assertIn("2u en 4u", why)
        self.assertTrue(rw.should_push("rand_high", "2h", 2, 3)[0])
        self.assertTrue(rw.should_push("gevonden", "4h", 2, 3)[0])
        self.assertTrue(rw.should_push("rand_low", "30m", 50, 0)[0])        # budget 0 is onbeperkt

    def test_body_is_measured_only(self):
        body = rw.watch_body("ARB", "2h", rng(0.2045, 0.17, 0.003), 0.1988)
        self.assertIn("Range 2u", body)
        self.assertIn("3 keer boven, 3 keer onder", body)
        self.assertIn("ongetest", body)
        self.assertNotIn("kans", body.lower())
        self.assertNotIn("—", body)


class RunTest(DbCase):
    """Eén coin, de kunstmatige markt uit de fixture, en een nepbeurs: de echte is vanuit de sandbox niet bereikbaar."""

    def setUp(self):
        super().setUp()
        self.b15, self.b1h, self.b4h = frames()
        self.price = 103.0
        self.fetched = []
        for p in (mock.patch.object(config, "RANGE_WATCH_ENABLED", True), mock.patch.object(config, "RANGE_SWEEP_PUBLIC", False),
                  mock.patch.object(rw, "COINS", ("ARB",)),
                  mock.patch("app.exchange.fetch_ohlcv", side_effect=self.fake_ohlcv),
                  mock.patch("app.exchange.fetch_last_price", side_effect=lambda coin: self.price)):
            p.start()
            self.addCleanup(p.stop)
        self.push = mock.AsyncMock()
        p = mock.patch.object(push_notify, "send_push", self.push)
        p.start()
        self.addCleanup(p.stop)
        self.ceo = repo.get_ceo_user()["id"]

    def fake_ohlcv(self, coin, timeframe="4h", limit=200, since=None):
        self.fetched.append(timeframe)
        return {"15m": self.b15, "1h": self.b1h, "4h": self.b4h}[timeframe].copy()

    def at(self, hour, minute=0):
        return self.b1h["timestamp"].iloc[hour].to_pydatetime() + timedelta(minutes=minute)

    def run_at(self, hour, minute=0):
        asyncio.run(rw.run(self.at(hour, minute)))

    def known_coin(self):
        """Een eerdere, ver weg gelegen range: de coin is dan niet voor het eerst gezien en meldt gewoon."""
        db.set_setting("range_watch_seeded:ARB", "1")
        repo.upsert_range_watch({"coin": "ARB", "tf": "30m", "range_high": 50.0, "range_low": 40.0, "first_at": "2025-01-01T00:00:00+00:00",
                                 "found_at": "2025-01-01T00:00:00+00:00", "atr": 1.0})

    def kinds(self):
        with db.session() as conn:
            return [(r["kind"], r["pushed"]) for r in conn.execute("SELECT kind, pushed FROM range_watch_log ORDER BY id")]

    def test_disabled_does_nothing(self):
        with mock.patch.object(config, "RANGE_WATCH_ENABLED", False):
            self.run_at(130)
        self.assertEqual((self.fetched, repo.list_range_watches()), ([], []))

    def test_first_sight_of_a_coin_registers_silently(self):
        self.price = 105.95
        self.run_at(130)
        self.assertEqual(sorted(w["tf"] for w in repo.list_range_watches()), ["1h", "2h", "4h"])
        self.push.assert_not_called()
        self.assertEqual(repo.list_notifications(self.ceo), [])
        self.run_at(130, 5)
        self.assertEqual(self.kinds(), [])

    def test_a_coin_without_ranges_is_seeded_too_and_reports_its_first_real_range(self):
        self.run_at(60)
        self.assertEqual(repo.list_range_watches(), [])
        self.run_at(130)
        self.assertEqual(self.kinds(), [("gevonden", True), ("gevonden", True)])

    def test_found_pushes_only_2h_and_4h_and_only_once(self):
        self.known_coin()
        self.run_at(130)
        self.assertEqual(self.kinds(), [("gevonden", True), ("gevonden", True)])
        self.assertEqual(self.push.await_count, 2)
        self.assertTrue(all(c.kwargs["silent"] for c in self.push.await_args_list))
        self.run_at(130, 5)
        self.run_at(131)
        self.assertEqual(self.push.await_count, 2)

    def test_edge_fires_once_per_edge_and_budget_caps_pushes_at_three(self):
        self.known_coin()
        self.price = 105.95
        self.run_at(130)
        pushed = [k for k, p in self.kinds() if p]
        self.assertEqual(len(pushed), 3)
        self.assertEqual(len(self.kinds()), 5)
        notes = repo.list_notifications(self.ceo)
        self.assertEqual(len(notes), 2)
        self.assertTrue(all("budget" in n["body"] for n in notes))
        self.run_at(130, 5)
        self.run_at(131)
        self.assertEqual(len(self.kinds()), 5)

    def test_one_failing_viewer_does_not_block_the_next(self):
        self.known_coin()
        other = repo.create_user("b", "x", 0, 1)
        calls = []

        async def flaky(uid, *a, **k):
            calls.append(uid)
            if len(calls) == 1:
                raise RuntimeError("push stuk")
        with mock.patch.object(rw, "viewers", return_value=[self.ceo, other]), mock.patch.object(push_notify, "send_push", flaky):
            asyncio.run(rw._warn(1, "4h", "gevonden", "t", "b", self.at(130)))
        self.assertEqual(calls, [self.ceo, other])

    def test_budget_frees_up_after_24_hours(self):
        self.known_coin()
        self.price = 105.95
        self.run_at(130)
        old = (self.at(130) - timedelta(hours=25)).isoformat()
        with db.session() as conn:
            conn.execute("UPDATE range_watch_log SET at = ?", (old,))
        self.assertEqual(repo.count_range_watch_pushes(self.ceo, (self.at(131) - timedelta(hours=24)).isoformat()), 0)

    def test_outside_the_window_only_the_live_price_is_checked(self):
        self.known_coin()
        self.run_at(130)
        before = len(self.kinds())
        self.fetched.clear()
        self.price = 105.95
        with mock.patch("app.exchange.fetch_ohlcv", side_effect=AssertionError("geen candles buiten het venster")):
            self.run_at(130, 15)
        self.assertGreater(len(self.kinds()), before)
        self.assertEqual(self.fetched, [])

    def test_forming_candles_never_make_a_range(self):
        self.known_coin()
        self.run_at(60)
        self.assertEqual([w for w in repo.list_range_watches() if w["tf"] != "30m"], [])
        self.push.assert_not_called()

    def test_paused_user_gets_a_quiet_note_and_no_push(self):
        self.known_coin()
        repo.set_push_pause(self.ceo, (self.at(130) + timedelta(hours=1)).isoformat())
        self.run_at(130)
        self.push.assert_not_called()
        self.assertEqual(self.kinds(), [("gevonden", False), ("gevonden", False)])
        self.assertIn("pauze", repo.list_notifications(self.ceo)[0]["body"])

    def test_students_get_nothing_until_public(self):
        other = repo.create_user("b", "x", 0, 1)
        self.known_coin()
        self.run_at(130)
        self.assertEqual({c.args[0] for c in self.push.await_args_list}, {self.ceo})
        self.assertEqual(repo.list_notifications(other), [])
        with mock.patch.object(config, "RANGE_SWEEP_PUBLIC", True):
            self.price = 105.95
            self.run_at(131)
        self.assertIn(other, {c.args[0] for c in self.push.await_args_list})

    def test_range_that_shifts_key_is_not_found_twice(self):
        # Na een prik krijgt dezelfde range een ander eerste zwaaipunt met bijna dezelfde randen: geen nieuwe "gevonden", geen herhaalde randmelding.
        self.known_coin()
        old, _ = repo.upsert_range_watch({"coin": "ARB", "tf": "4h", "range_high": 106.03, "range_low": 99.97, "first_at": "2025-03-03T10:00:00+00:00",
                                          "found_at": "2025-03-04T00:00:00+00:00", "atr": 1.0})
        repo.mark_range_watch_edge(old, "high")
        self.run_at(130)
        kinds = [k for k, _ in self.kinds()]
        self.assertEqual(kinds, ["gevonden"])
        states = {(w["tf"], w["first_at"][:10]): w["state"] for w in repo.list_range_watches(("actief", "verlopen", "gebroken"))}
        self.assertEqual(states[("4h", "2025-03-03")], "verlopen")
        new = [w for w in repo.list_range_watches() if w["tf"] == "4h"][0]
        self.assertIsNotNone(new["edge_high_at"])

    def test_ended_range_is_closed_without_a_push(self):
        self.known_coin()
        gone, _ = repo.upsert_range_watch({"coin": "ARB", "tf": "2h", "range_high": 60.0, "range_low": 50.0, "first_at": "2025-03-01T00:00:00+00:00",
                                           "found_at": "2025-03-02T00:00:00+00:00", "atr": 1.0})
        self.run_at(130)
        end = {w["id"]: w["state"] for w in repo.list_range_watches(("verlopen", "gebroken"))}
        self.assertEqual(end[gone], "gebroken")
        self.assertNotIn("einde", [k for k, _ in self.kinds()])

    def test_failing_coin_does_not_stop_the_others(self):
        self.known_coin()
        with mock.patch.object(rw, "COINS", ("ARB", "BTC")), mock.patch("app.exchange.fetch_ohlcv", side_effect=RuntimeError("beurs weg")):
            self.run_at(130)
        self.assertIsNotNone(repo.get_beat("range_watch"))


class WatchUrlTest(unittest.TestCase):
    def test_a_range_notification_opens_the_ranges_tab_of_setups(self):
        # Radar (/smc) toont de ranges niet meer; een tik op de melding moet op het tabblad Ranges van Setups landen.
        from app import range_watch
        self.assertEqual(range_watch.WATCH_URL, "/structuur#tab-ranges")
