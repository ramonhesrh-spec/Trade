import asyncio
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from app import config, db, level_check, repo, rule_live, track_record
from app.replay import trendlab as tl
from tests.test_samenval import DbCase

DON = next(v for v in tl.VARIANTS if v.name == "DON55_TREND")
FOUR_H = pd.Timedelta(hours=4)


def flat(n=300, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.001, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * 1.001
    low = np.minimum(open_, close) * 0.999
    return pd.DataFrame({"timestamp": idx, "open": open_, "high": high, "low": low, "close": close, "volume": 1.0})


def append(b, factors):
    """Plakt candles aan b; elke factor is slot/open van die candle."""
    rows = []
    prev = float(b["close"].iloc[-1])
    ts = b["timestamp"].iloc[-1]
    for f in factors:
        ts = ts + FOUR_H
        close = prev * f
        rows.append({"timestamp": ts, "open": prev, "high": max(prev, close) * 1.001, "low": min(prev, close) * 0.999, "close": close, "volume": 1.0})
        prev = close
    return pd.concat([b, pd.DataFrame(rows)], ignore_index=True)


def breakout(n=260):
    """Vlakke reeks waarvan de laatste candle sluit boven het hoogste hoog van de vorige 55 en boven de EMA van 200."""
    return append(flat(n - 1), [1.03])


class NextStopTest(unittest.TestCase):
    def test_long_stop_only_moves_up(self):
        bars = pd.DataFrame({"high": [110.0, 120.0, 118.0], "low": [105.0, 112.0, 110.0]})
        s = rule_live.next_stop("long", 95.0, bars, atr=2.0, k_trail=3.0)
        self.assertEqual(s, 120.0 - 3 * 2.0)
        self.assertEqual(rule_live.next_stop("long", 130.0, bars, atr=2.0, k_trail=3.0), 130.0)

    def test_short_stop_only_moves_down(self):
        bars = pd.DataFrame({"high": [100.0, 99.0], "low": [90.0, 85.0]})
        self.assertEqual(rule_live.next_stop("short", 110.0, bars, atr=2.0, k_trail=3.0), 85.0 + 6.0)
        self.assertEqual(rule_live.next_stop("short", 80.0, bars, atr=2.0, k_trail=3.0), 80.0)

    def test_atr_per_candle_like_the_lab(self):
        bars = pd.DataFrame({"high": [110.0, 120.0], "low": [105.0, 112.0], "atr": [1.0, 4.0]})
        self.assertEqual(rule_live.next_stop("long", 95.0, bars, atr=2.0, k_trail=3.0), max(110.0 - 3.0, 120.0 - 12.0))


class CloseIfHitTest(unittest.TestCase):
    def test_long_stopped_out_with_profit_counts_as_take_profit(self):
        sig = {"direction": "long", "price": 100.0, "initial_stop": 95.0, "current_stop": 108.0}
        bars = pd.DataFrame({"high": [112.0], "low": [107.0]})
        r, outcome = rule_live.close_if_hit(sig, bars)
        self.assertEqual(outcome, "take_profit")
        self.assertAlmostEqual(r, (108.0 - 100.0) / 5.0)

    def test_initial_stop_is_minus_one_r(self):
        sig = {"direction": "long", "price": 100.0, "initial_stop": 95.0, "current_stop": 95.0}
        r, outcome = rule_live.close_if_hit(sig, pd.DataFrame({"high": [99.0], "low": [94.0]}))
        self.assertEqual((r, outcome), (-1.0, "stop_loss"))

    def test_not_hit_returns_none(self):
        sig = {"direction": "long", "price": 100.0, "initial_stop": 95.0, "current_stop": 95.0}
        self.assertIsNone(rule_live.close_if_hit(sig, pd.DataFrame({"high": [103.0], "low": [97.0]})))

    def test_gap_fills_at_the_open_and_short_mirrors(self):
        sig = {"direction": "short", "price": 100.0, "initial_stop": 105.0, "current_stop": 103.0}
        r, outcome = rule_live.close_if_hit(sig, pd.DataFrame({"open": [106.0], "high": [107.0], "low": [105.5]}))
        self.assertAlmostEqual(r, (100.0 - 106.0) / 5.0)
        self.assertEqual(outcome, "stop_loss")


class FollowTest(unittest.TestCase):
    def test_stop_for_a_candle_comes_from_the_candles_before_it(self):
        trade = {"direction": "long", "price": 100.0, "initial_stop": 96.0, "current_stop": 96.0, "atr": 1.0}
        closed = pd.DataFrame({"timestamp": pd.date_range("2025-01-01", periods=2, freq="4h", tz="UTC"),
                               "open": [100.0, 109.0], "high": [110.0, 109.5], "low": [99.0, 107.5], "atr": [1.0, 1.0]})
        stop, hit = rule_live.follow(trade, closed, None, k_trail=3.0)
        self.assertEqual(stop, 107.0)                                  # 110 - 3: pas geldig vanaf de tweede candle, die er niet onder kwam
        self.assertIsNone(hit)
        forming = pd.DataFrame({"timestamp": [closed["timestamp"].iloc[-1] + FOUR_H], "open": [108.0], "high": [108.0], "low": [106.0]})
        stop, hit = rule_live.follow(trade, closed, forming, k_trail=3.0)
        self.assertEqual(hit[:2], ((107.0 - 100.0) / 4.0, "take_profit"))
        self.assertEqual(hit[2], forming["timestamp"].iloc[0])


    def test_only_candles_after_checked_until_are_tested_but_the_extreme_still_counts(self):
        # Trade ouder dan het venster: de stop is al naar 107 getrokken. De oude candles (laag 99 en 105) zouden die raken, maar zijn al verwerkt.
        trade = {"direction": "long", "price": 100.0, "initial_stop": 96.0, "current_stop": 107.0, "atr": 1.0}
        ts = pd.date_range("2025-01-01", periods=3, freq="4h", tz="UTC")
        closed = pd.DataFrame({"timestamp": ts, "open": [100.0, 111.0, 109.0], "high": [112.0, 111.5, 109.8], "low": [99.0, 105.0, 108.5], "atr": [1.0] * 3})
        stop, hit = rule_live.follow(trade, closed, None, k_trail=3.0, checked_until=ts[1])
        self.assertIsNone(hit)
        self.assertEqual(stop, 112.0 - 3.0)                           # het uiterste van vóór het venster-einde telt nog mee, zoals in het lab
        stop, hit = rule_live.follow(trade, closed, None, k_trail=3.0)  # zonder checked_until: de oude candle zou de trade vals sluiten
        self.assertIsNotNone(hit)

    def test_first_run_tests_the_entry_candle(self):
        trade = {"direction": "long", "price": 100.0, "initial_stop": 96.0, "current_stop": 96.0, "atr": 1.0}
        ts = pd.date_range("2025-01-01", periods=2, freq="4h", tz="UTC")
        closed = pd.DataFrame({"timestamp": ts[1:], "open": [100.0], "high": [100.5], "low": [95.0], "atr": [1.0]})
        _, hit = rule_live.follow(trade, closed, None, k_trail=3.0, checked_until=ts[0])     # checked_until = de signaalcandle
        self.assertEqual(hit[:2], (-1.0, "stop_loss"))


class StopMovedTest(unittest.TestCase):
    def test_float_drift_and_a_lower_stop_are_not_a_move(self):
        self.assertFalse(rule_live.stop_moved("long", 107.0, 107.0 + 1e-12))
        self.assertFalse(rule_live.stop_moved("long", 107.0, 106.0))
        self.assertTrue(rule_live.stop_moved("long", 107.0, 107.5))
        self.assertTrue(rule_live.stop_moved("short", 107.0, 106.5))
        self.assertFalse(rule_live.stop_moved("short", 107.0, 107.5))


class LabelAndStatusTest(unittest.TestCase):
    def test_push_label_drops_in_proef_only_when_proven(self):
        self.assertEqual(rule_live.label(DON), "Trend 4u in proef")
        self.assertEqual(rule_live.label(DON, proven=True), "Trend 4u")
        self.assertNotIn("proef", track_record.TYPE_LABELS[rule_live.RULE])

    def test_lab_variant_without_engine_is_geen_motor(self):
        self.assertEqual(track_record.rule_status({"lab_passes": True}, [], has_engine=False)["status"], "Geen motor")
        self.assertEqual(track_record.rule_status({"lab_passes": True}, [])["status"], "In proef")

    def test_proof_line_uses_the_rule_status_and_never_says_doel(self):
        wins = [0.5] * 60
        self.assertEqual(track_record.rule_proof({"lab_passes": True}, wins)["label"], "Bewezen")
        self.assertEqual(track_record.rule_proof(None, wins)["label"], "In proef")          # zonder labtoets nooit bewezen (trust.status zou het wel zeggen)
        self.assertEqual(track_record.rule_proof({"lab_passes": False}, wins)["label"], "Negatief")
        p = track_record.rule_proof({"lab_passes": True}, [2.0, -1.0])
        self.assertEqual((p["state"], p["n"]), ("proef", 2))
        self.assertNotIn("doel", p["text"].lower())
        self.assertIn("R", p["text"])


class DetectTest(unittest.TestCase):
    def test_breakout_on_the_last_closed_candle_is_long(self):
        b = breakout()
        sig = rule_live.detect(b, DON)
        self.assertEqual(sig["direction"], "long")
        self.assertEqual(sig["entry"], float(b["close"].iloc[-1]))
        prepared = tl.prepare(b)
        self.assertAlmostEqual(sig["atr"], float(prepared["atr"].iloc[-1]))
        self.assertAlmostEqual(sig["stop"], sig["entry"] - tl.TRAIL_K_STOP * sig["atr"])

    def test_breakout_one_candle_earlier_is_none(self):
        self.assertIsNone(rule_live.detect(append(breakout(), [0.995]), DON))


class ShouldDisableTest(unittest.TestCase):
    def test_needs_thirty_closed_trades(self):
        self.assertFalse(rule_live.should_disable([-1.0] * 29))
        self.assertTrue(rule_live.should_disable([-1.0] * 30))

    def test_only_the_last_thirty_count_and_zero_is_not_negative(self):
        self.assertFalse(rule_live.should_disable([-5.0] * 10 + [0.5] * 30))
        self.assertTrue(rule_live.should_disable([5.0] * 10 + [-0.1] * 30))
        self.assertFalse(rule_live.should_disable([1.0, -1.0] * 15))

    def test_net_results_use_the_real_r_and_costs_oldest_first(self):
        rows = [{"price": 100.0, "stop_loss": 98.0, "take_profit": None, "auto_outcome": "take_profit", "r_override": 3.0},
                {"price": 100.0, "stop_loss": 98.0, "take_profit": None, "auto_outcome": "stop_loss", "r_override": -1.0}]
        self.assertEqual(rule_live.net_results(rows, 0.06), [-1.0 - 0.03, 3.0 - 0.03])


class ScanAndFollowTest(DbCase):
    def setUp(self):
        super().setUp()
        self.leerling = repo.create_user("b", "x", 0, 1)
        self.ceo = repo.get_user_by_username("a")["id"]
        # 299 vlakke candles, uitbraak op 299, dan 3 stijgende candles en een val: 300 is de instapcandle.
        self.series = append(append(flat(299), [1.03]), [1.04, 1.04, 1.04, 0.85, 1.0, 1.0])
        self.pushed = []
        for p in (mock.patch.object(config, "CEO_USERNAME", ""), mock.patch.object(rule_live, "COINS", ("BTC",)),
                  mock.patch.object(rule_live, "fetch_bars", self.fetch), mock.patch("app.push_notify.send_push", self.fake_push)):
            p.start()
            self.addCleanup(p.stop)
        repo.set_rule_lab(rule_live.RULE, True, {}, db.now_iso())        # nieuwe trades alleen na een geslaagde labtoets

    def at(self, i):
        return (self.series["timestamp"].iloc[i] + pd.Timedelta(minutes=5)).to_pydatetime()

    def fetch(self, coin, timeframe, limit):
        assert timeframe == "4h"
        return self.series[self.series["timestamp"] <= pd.Timestamp(self.now)].tail(limit).reset_index(drop=True)

    async def fake_push(self, user_id, title, body, url, silent=False, tag=None):
        self.pushed.append({"user": user_id, "title": title, "body": body, "tag": tag})

    def scan(self, i):
        self.now = self.at(i)
        asyncio.run(rule_live.scan(self.now))

    def follow(self, i):
        self.now = self.at(i)
        asyncio.run(rule_live.update_open(self.now))

    def signals(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM signals WHERE trade_type = ?", (rule_live.RULE,))]

    def test_one_signal_for_the_ceo_followed_and_closed_with_the_real_r(self):
        self.scan(300)                                      # 300 vormt nog, 299 is de laatste gesloten candle: de uitbraak
        sigs = self.signals()
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(rule_live.RULE, "don55_trend")
        self.assertEqual((s["direction"], s["price"], s["take_profit"]), ("long", float(self.series["close"].iloc[299]), None))
        with db.session() as conn:
            users = [r["user_id"] for r in conn.execute("SELECT user_id FROM journal_entries WHERE signal_id = ?", (s["id"],))]
        self.assertEqual(users, [self.ceo])
        self.assertEqual([(p["user"], p["tag"]) for p in self.pushed], [(self.ceo, f"trend-{s['id']}")])
        self.assertIn("Richtprijs", self.pushed[0]["body"])
        trade = repo.list_open_rule_trades(rule_live.RULE)[0]
        self.assertEqual((trade["initial_stop"], trade["current_stop"]), (s["stop_loss"], s["stop_loss"]))
        self.assertEqual(trade["checked_until"], self.series["timestamp"].iloc[299].isoformat())   # de signaalcandle: de instapcandle wordt getoetst
        self.assertIsNone(repo.get_chain_link(s["id"]))                                             # geen schakel in de openbare ketting

        self.scan(300)                                      # zelfde candle na een herstart: niets nieuws
        self.scan(301)                                      # open trade op deze coin: geen tweede
        self.assertEqual(len(self.signals()), 1)
        self.assertEqual(len(self.pushed), 1)

        # De 15-minutencheck laat deze soort met rust: geen vast doel en een stop die meeloopt.
        with db.session() as conn:
            conn.execute("UPDATE journal_entries SET entry_price = ?, status = 'open' WHERE signal_id = ?", (s["price"], s["id"]))
        crash = pd.DataFrame({"timestamp": [pd.Timestamp(self.at(300))], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
        with mock.patch.object(level_check, "_fetch_since", lambda coin, since: crash), \
                mock.patch.object(level_check.exchange, "fetch_ohlcv", lambda *a, **k: crash):
            asyncio.run(level_check.check_signal_outcomes())
            asyncio.run(level_check.check_open_trades())
        self.assertIsNone(repo.get_signal(s["id"])["auto_outcome"])
        self.assertEqual(len(self.pushed), 1)

        self.follow(302)                                    # 300 en 301 gesloten en gestegen: de stop schuift op
        trade = repo.list_open_rule_trades(rule_live.RULE)[0]
        self.assertEqual(trade["checked_until"], self.series["timestamp"].iloc[301].isoformat())
        self.assertGreater(trade["current_stop"], trade["initial_stop"])
        self.assertEqual(repo.get_signal(s["id"])["stop_loss"], trade["initial_stop"])     # het signaal houdt de eerste stop
        self.assertEqual(self.pushed[-1]["tag"], f"trend-{s['id']}")
        self.assertEqual(len(self.pushed), 2)
        self.follow(302)                                    # niets veranderd: geen nieuwe melding
        self.assertEqual(len(self.pushed), 2)

        self.follow(304)                                    # 303 valt door de meelopende stop
        sig = repo.get_signal(s["id"])
        self.assertEqual(sig["auto_outcome"], "take_profit")
        # Vastgesteld nu, nooit vóór de melding: de candletijd (2025) ligt hier vóór created_at.
        self.assertEqual(sig["auto_outcome_at"], max(pd.Timestamp(self.now), pd.Timestamp(sig["created_at"])).isoformat())
        self.assertGreaterEqual(pd.Timestamp(sig["auto_outcome_at"]), pd.Timestamp(sig["created_at"]))
        with db.session() as conn:
            tr = dict(conn.execute("SELECT * FROM trade_results WHERE signal_id = ?", (s["id"],)).fetchone())
        self.assertEqual(tr["closed_at"], sig["auto_outcome_at"])
        self.assertGreater(tr["r_value"], 0)
        self.assertEqual(repo.list_open_rule_trades(rule_live.RULE), [])
        self.assertEqual(self.pushed[-1]["tag"], f"trend-{s['id']}")
        self.assertIn("R", self.pushed[-1]["body"])
        self.assertTrue(all(p["user"] == self.ceo for p in self.pushed))

    def test_trade_older_than_the_window_is_not_closed_on_an_old_candle(self):
        # Instap lang vóór het opgehaalde venster, stop al opgetrokken tot boven de lows van de oude candles in het venster.
        stop = float(self.series["close"].iloc[298])
        sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": rule_live.RULE, "price": 90.0,
                                  "stop_loss": 85.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}, chain_it=False)
        repo.insert_rule_trade(sid, rule_live.RULE, "BTC", "2024-01-01T00:00:00+00:00", 85.0, 1.0, self.series["timestamp"].iloc[299].isoformat())
        repo.set_rule_progress(sid, stop, self.series["timestamp"].iloc[299].isoformat())
        self.assertLess(self.series["low"].iloc[:300].min(), stop)                  # een oude candle zou de stop raken
        self.follow(302)
        trade = repo.list_open_rule_trades(rule_live.RULE)[0]
        self.assertIsNone(repo.get_signal(sid)["auto_outcome"])
        self.assertEqual(trade["checked_until"], self.series["timestamp"].iloc[301].isoformat())
        self.assertGreaterEqual(trade["current_stop"], stop)

    def test_heartbeat_counts_the_proef_only_for_the_ceo(self):
        from app import heartbeat
        sid = repo.insert_signal({"coin": "ETH", "direction": "long", "category": "day_trading", "trade_type": rule_live.RULE, "price": 100.0,
                                  "stop_loss": 98.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}, chain_it=False)
        repo.set_trade_result(sid, 3.0, db.now_iso())
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        asyncio.run(heartbeat.send_heartbeats())
        bodies = {p["user"]: p["body"] for p in self.pushed}
        self.assertIn("1 kans gemeld, 1 afgerond", bodies[self.ceo])
        self.assertIn("0 kansen gemeld, 0 afgerond", bodies[self.leerling])

    def test_no_new_trades_without_a_passed_lab_test_but_open_ones_are_followed(self):
        with db.session() as conn:
            conn.execute("DELETE FROM rule_status")
        self.scan(300)                                                        # geen labrij
        self.assertEqual(self.signals(), [])
        repo.set_rule_lab(rule_live.RULE, False, {}, db.now_iso())
        self.scan(300)                                                        # labtoets niet geslaagd
        self.assertEqual(self.signals(), [])
        repo.set_rule_lab(rule_live.RULE, True, {}, db.now_iso())
        self.scan(300)
        self.assertEqual(len(self.signals()), 1)
        repo.set_rule_lab(rule_live.RULE, False, {}, db.now_iso())            # teruggezet: de lopende trade wordt toch gevolgd en gesloten
        self.follow(304)
        self.assertEqual(repo.get_signal(self.signals()[0]["id"])["auto_outcome"], "take_profit")

    def test_pending_directions_ignore_the_proef_and_resolved_signals(self):
        self.scan(300)
        self.assertEqual(repo.pending_directions_for_coin("BTC"), {"long"})
        self.assertEqual(repo.pending_directions_for_coin("BTC", exclude_types=rule_live.CEO_ONLY_TYPES), set())
        other = repo.insert_signal({"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": "smc", "price": 100.0,
                                    "stop_loss": 101.0, "take_profit": 98.0, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"})
        repo.create_journal_entry(other, self.leerling, None)
        repo.mark_signal_auto_outcome(other, "stop_loss", db.now_iso())
        self.assertEqual(repo.pending_directions_for_coin("BTC", exclude_types=rule_live.CEO_ONLY_TYPES), set())

    def test_outside_the_window_after_a_close_nothing_is_fetched(self):
        self.now = (self.series["timestamp"].iloc[300] + pd.Timedelta(hours=1)).to_pydatetime()
        with mock.patch.object(rule_live, "fetch_bars", side_effect=AssertionError("geen ophaalactie verwacht")):
            asyncio.run(rule_live.scan(self.now))
        self.assertEqual(self.signals(), [])

    def test_engine_switches_itself_off_after_thirty_negative_trades(self):
        for _ in range(30):
            sid = repo.insert_signal({"coin": "ETH", "direction": "long", "category": "day_trading", "trade_type": rule_live.RULE,
                                      "price": 100.0, "stop_loss": 98.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"})
            repo.set_trade_result(sid, -1.0, db.now_iso())
            repo.mark_signal_auto_outcome(sid, "stop_loss", db.now_iso())
        self.scan(300)
        self.assertEqual(len(self.signals()), 30)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications WHERE type = 'engine'").fetchone()[0], 1)


class WebVisibilityTest(DbCase):
    """Alleen de CEO ziet de proef: leerlingen krijgen de kans niet te zien en Bewijs telt hem voor hen niet mee."""
    def test_leerling_does_not_see_the_proef(self):
        from fastapi.testclient import TestClient
        from app import security
        from web import main
        leerling = repo.create_user("b", security.hash_password("wachtwoord-123456"), 0, 1)
        ceo = repo.get_user_by_username("a")["id"]
        sid = repo.insert_signal({"coin": "ADA", "direction": "long", "category": "day_trading", "trade_type": rule_live.RULE, "price": 100.0,
                                  "stop_loss": 97.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "In proef",
                                  "reason": "In proef: DON55_TREND, meelopende stop op 3 ATR"})
        repo.set_trade_result(sid, 2.0, db.now_iso())
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        main._ceo_cache.update(at=0.0, id=None)
        seen = {}
        with mock.patch.object(config, "CEO_USERNAME", ""), mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen netwerk")), \
                mock.patch.object(main.exchange, "fetch_last_price", side_effect=RuntimeError("geen netwerk")):
            for name, uid in (("ceo", ceo), ("leerling", leerling)):
                client = TestClient(main.app)
                client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
                seen[name] = {p: client.get(p) for p in (f"/kans/{sid}", "/bewijs", "/coins/ADA", "/api/coin_menu_activity")}
        self.assertEqual(seen["ceo"][f"/kans/{sid}"].status_code, 200)
        self.assertEqual(seen["leerling"][f"/kans/{sid}"].status_code, 404)
        self.assertIn("in proef", seen["ceo"]["/bewijs"].text)
        self.assertNotIn("in proef", seen["leerling"]["/bewijs"].text)
        self.assertIn("meelopende stop", seen["ceo"]["/coins/ADA"].text)
        self.assertNotIn("meelopende stop", seen["leerling"]["/coins/ADA"].text)
        self.assertEqual(seen["ceo"]["/api/coin_menu_activity"].json(), ["ADA"])
        self.assertEqual(seen["leerling"]["/api/coin_menu_activity"].json(), [])

    def test_rule_status_line_is_only_for_the_ceo(self):
        from fastapi.testclient import TestClient
        from app import security
        from web import main
        leerling = repo.create_user("b2", security.hash_password("wachtwoord-123456"), 0, 1)
        ceo = repo.get_user_by_username("a")["id"]
        sid = repo.insert_signal({"coin": "ADA", "direction": "long", "category": "day_trading", "trade_type": rule_live.RULE, "price": 100.0,
                                  "stop_loss": 97.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "In proef"})
        repo.set_trade_result(sid, 2.0, db.now_iso())
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        main._ceo_cache.update(at=0.0, id=None)
        seen = {}
        with mock.patch.object(config, "CEO_USERNAME", ""):
            for name, uid in (("ceo", ceo), ("leerling", leerling)):
                client = TestClient(main.app)
                client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
                seen[name] = client.get("/bewijs").text
        self.assertIn("Status per regel", seen["ceo"])
        self.assertIn("1 afgeronde live trades", seen["ceo"])
        self.assertNotIn("Status per regel", seen["leerling"])
        self.assertNotIn("afgeronde live trades", seen["leerling"])

    def test_other_lab_variants_are_invisible_to_a_leerling(self):
        from fastapi.testclient import TestClient
        from app import security
        from web import main
        leerling = repo.create_user("b3", security.hash_password("wachtwoord-123456"), 0, 1)
        ceo = repo.get_user_by_username("a")["id"]
        with db.session() as conn:
            conn.execute("INSERT INTO rule_status (rule, lab_passes, lab_json, lab_at) VALUES ('don20', 0, '{}', ?)", (db.now_iso(),))
        main._ceo_cache.update(at=0.0, id=None)
        seen = {}
        with mock.patch.object(config, "CEO_USERNAME", ""):
            for name, uid in (("ceo", ceo), ("leerling", leerling)):
                client = TestClient(main.app)
                client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
                seen[name] = client.get("/bewijs").text
        self.assertIn("don20", seen["ceo"])
        self.assertNotIn("don20", seen["leerling"])
        self.assertNotIn("Status per regel", seen["leerling"])

    def test_public_chain_skips_the_proef_and_still_verifies(self):
        from fastapi.testclient import TestClient
        from app import chain
        from web import main
        base = {"coin": "BTC", "direction": "long", "category": "day_trading", "price": 100.0, "stop_loss": 97.0, "take_profit": 106.0,
                "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}
        repo.insert_signal({**base, "trade_type": "smc"})
        proef = repo.insert_signal({**base, "trade_type": rule_live.RULE, "take_profit": None}, chain_it=False)
        repo.insert_signal({**base, "trade_type": "smc"})
        anon = TestClient(main.app)
        rows = anon.get("/keten.json").json()
        self.assertEqual(len(rows), 2)
        self.assertNotIn(proef, [r["signal_id"] for r in rows])
        self.assertEqual(chain.verify(rows), (True, None))
        page = anon.get("/keten")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(rule_live.RULE, page.text + anon.get("/keten.json").text)


class KansAndBewijsTest(DbCase):
    def client(self, uid):
        from fastapi.testclient import TestClient
        from app import security
        from web import main
        main._ceo_cache.update(at=0.0, id=None)
        main._proof_cache.update(at=0.0)
        c = TestClient(main.app)
        c.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
        return c

    def test_kans_of_a_trailing_trade_has_no_doel_and_the_rule_status(self):
        from web import main
        ceo = repo.get_user_by_username("a")["id"]
        sid = repo.insert_signal({"coin": "ADA", "direction": "long", "category": "day_trading", "trade_type": rule_live.RULE, "price": 100.0,
                                  "stop_loss": 97.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "In proef",
                                  "reason": "In proef"}, chain_it=False)
        repo.set_trade_result(sid, 2.5, db.now_iso())
        repo.mark_signal_auto_outcome(sid, "take_profit", db.now_iso())
        repo.set_rule_lab(rule_live.RULE, False, {}, db.now_iso())
        with mock.patch.object(config, "CEO_USERNAME", ""), mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen netwerk")), \
                mock.patch.object(main.exchange, "fetch_last_price", side_effect=RuntimeError("geen netwerk")):
            page = self.client(ceo).get(f"/kans/{sid}").text
        self.assertIn("Afgesloten met winst, +2.50R", page)
        self.assertNotIn("Doel geraakt", page)
        self.assertNotIn("raakten het doel", page)
        self.assertIn("Slaagde niet in de test", page)                  # de status van Bewijs, niet die van trust.status

    def test_bewijs_shows_geen_motor_and_the_caveat_for_the_ceo(self):
        ceo = repo.get_user_by_username("a")["id"]
        repo.set_rule_lab("don20", True, {}, db.now_iso())
        repo.set_rule_lab(rule_live.RULE, True, {}, db.now_iso())
        with mock.patch.object(config, "CEO_USERNAME", ""):
            page = self.client(ceo).get("/bewijs").text
        self.assertIn("Geen motor", page)
        self.assertIn("50 live trades kunnen een voordeel van 0,1R", page)
        self.assertIn("Jij ziet ook de regels in proef", page)


class MigrationTest(unittest.TestCase):
    def test_old_rule_trades_get_checked_until_from_the_signal_candle(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE rule_trades (signal_id INTEGER PRIMARY KEY, rule TEXT NOT NULL, coin TEXT NOT NULL, entered_at TEXT NOT NULL,
                            initial_stop REAL NOT NULL, current_stop REAL NOT NULL, atr REAL NOT NULL, UNIQUE (rule, coin, entered_at))""")
            conn.execute("INSERT INTO rule_trades VALUES (1, 'don55_trend', 'BTC', '2026-10-09T04:00:00+00:00', 95, 97, 1.5)")
            conn.execute("INSERT INTO rule_trades VALUES (2, 'onbekend', 'ETH', '2026-10-09T04:00:00+00:00', 95, 97, 1.5)")
            conn.commit()
            conn.close()
            with mock.patch.object(config, "DATABASE_PATH", path):
                db.init_db()
                db.init_db()                                                   # idempotent
                with db.session() as c:
                    rows = {r["signal_id"]: r["checked_until"] for r in c.execute("SELECT signal_id, checked_until FROM rule_trades")}
        self.assertEqual(rows, {1: "2026-10-09T00:00:00+00:00", 2: "2026-10-09T04:00:00+00:00"})


if __name__ == "__main__":
    unittest.main()
