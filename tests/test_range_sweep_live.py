import asyncio
import json
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from app import chance_checks, config, db, level_check, push_notify, range_sweep_live as live, repo, rule_live
from app.replay import rangesweep as rs, rangesweep_lab as rl
from tests.replay.rangesweep_fixtures import FIRST_SHORT_ZONE_SETUP_HOUR, START, frames
from tests.test_samenval import DbCase

TEST_VARIANT = rl.RSVariant("RZ_T", "zone", "1h", "zone", "slot", False, False)
SHORT_PLACED = START + pd.Timedelta(hours=FIRST_SHORT_ZONE_SETUP_HOUR + 1)     # 17:00 op 7 maart: de limiet staat op 105,375
LONG_PLACED = START + pd.Timedelta(hours=103)
SWEEP_AT = START + pd.Timedelta(hours=174)


class VariantTest(unittest.TestCase):
    def test_variant_from_the_lab_row(self):
        v, stop = live.live_variant({"lab_passes": 1, "lab_json": {"variant": "RZ_2H", "stop_name": "zone_05"}})
        self.assertEqual((v.name, stop), ("RZ_2H", "zone_05"))
        self.assertIsNone(live.live_variant({"lab_passes": 0, "lab_json": {"variant": "RZ_2H"}}))
        self.assertIsNone(live.live_variant(None))

    def test_variant_from_the_repo_row_shape(self):
        # repo.get_rule_lab geeft de inhoud onder "summary", niet onder "lab_json".
        v, stop = live.live_variant({"lab_passes": True, "summary": {"variant": "RS_1H", "stop_name": "wick_025"}})
        self.assertEqual((v.name, stop), ("RS_1H", "wick_025"))

    def test_a_stop_the_variant_never_tested_is_refused(self):
        self.assertIsNone(live.live_variant({"lab_passes": True, "summary": {"variant": "RZ_2H", "stop_name": "wick_025"}}))
        self.assertIsNone(live.live_variant({"lab_passes": True, "summary": {"variant": "BESTAAT_NIET", "stop_name": "zone_025"}}))


class FreshTest(unittest.TestCase):
    def test_only_setups_placed_in_the_last_20_minutes(self):
        b15, b1h, b4h = frames()
        v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        placed = b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)

        def at(now):
            cut = lambda df: df[df["timestamp"] < now]
            return rs.build_frames(cut(b15), cut(b1h), cut(b4h))
        now = placed + pd.Timedelta(minutes=5)
        self.assertEqual([s["direction"] for s in live.fresh_setups(at(now), v, now)], ["short"])
        later = placed + pd.Timedelta(minutes=40)
        self.assertEqual(live.fresh_setups(at(later), v, later), [])

    def test_a_forming_candle_in_the_frames_changes_nothing(self):
        b15, b1h, b4h = frames()
        v = TEST_VARIANT
        before = SHORT_PLACED - pd.Timedelta(minutes=5)       # de kaars van 16:00 vormt nog; de setup ontstaat pas bij het slot
        full = rs.build_frames(b15, b1h, b4h)                 # inclusief de hele toekomst
        self.assertEqual(live.fresh_setups(full, v, before), [])


class LiquidationTest(unittest.TestCase):
    def test_short_counts_liquidated_shorts(self):
        t = pd.Timestamp("2026-10-15 14:00", tz="UTC")
        buckets = [{"bucket": (t + pd.Timedelta(minutes=5 * k)).isoformat(), "long_usd": 0.0, "short_usd": 50_000.0} for k in range(12)]
        base = [{"bucket": (t - pd.Timedelta(hours=h)).isoformat(), "long_usd": 0.0, "short_usd": 10_000.0} for h in range(1, 169)]
        out = live.liquidation_check("short", buckets, t, t + pd.Timedelta(hours=1), base)
        self.assertEqual(out["usd"], 600_000.0)
        self.assertTrue(out["ok"])

    def test_no_data_is_not_a_pass(self):
        t = pd.Timestamp("2026-10-15 14:00", tz="UTC")
        self.assertFalse(live.liquidation_check("long", [], t, t + pd.Timedelta(hours=1), [])["ok"])

    def test_the_other_side_does_not_count(self):
        t = pd.Timestamp("2026-10-15 14:00", tz="UTC")
        buckets = [{"bucket": t.isoformat(), "long_usd": 900_000.0, "short_usd": 0.0}]
        base = [{"bucket": (t - pd.Timedelta(hours=h)).isoformat(), "long_usd": 1.0, "short_usd": 10_000.0} for h in range(1, 169)]
        self.assertFalse(live.liquidation_check("short", buckets, t, t + pd.Timedelta(hours=1), base)["ok"])


class FollowTest(unittest.TestCase):
    def frame(self, rows):
        df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
        df.insert(0, "timestamp", pd.date_range("2026-10-15 15:00", periods=len(df), freq="15min", tz="UTC"))
        return df

    def trade(self):
        base = {"direction": "short", "entry": 105.0, "stop": 106.0, "filled_at": "2026-10-15T15:00:00+00:00", "checked_until": "2026-10-15T14:45:00+00:00",
                "mae_r": 0.0, "mfe_r": 0.0, "stop_hit_at": None, "ref_stop": 106.0, "ref_extreme": 105.0, "ref_r": None, "ref_closed_at": None}
        return {**base, **{f"reached_{k}r_at": None for k in range(1, 7)}}

    def test_reaches_one_r_and_records_the_time(self):
        c = self.frame([(105, 105.1, 104.9, 105), (105, 105.1, 103.9, 104.0)])
        out = live.follow_step(self.trade(), c, np.ones(len(c)))
        self.assertIsNotNone(out["reached_1r_at"])
        self.assertIsNone(out["stop_hit_at"])
        self.assertAlmostEqual(out["mfe_r"], 1.1)

    def test_stop_closes_reference_too(self):
        c = self.frame([(105, 105.1, 104.9, 105), (105, 106.2, 104.9, 106.1)])
        out = live.follow_step(self.trade(), c, np.ones(len(c)))
        self.assertIsNotNone(out["stop_hit_at"])
        self.assertAlmostEqual(out["ref_r"], -1.0)

    def test_already_checked_candles_are_skipped(self):
        c = self.frame([(105, 106.2, 104.9, 106.1)])
        self.assertIsNone(live.follow_step({**self.trade(), "checked_until": c["timestamp"].iloc[0].isoformat()}, c, np.ones(1))["stop_hit_at"])

    def test_the_fill_candle_only_counts_against_the_trade(self):
        # De vulcandle: een gunstige beweging daarin telt niet (de volgorde binnen de candle is onbekend), een stop wel.
        c = self.frame([(105, 105.1, 103.0, 105)])
        out = live.follow_step(self.trade(), c, np.ones(1))
        self.assertEqual(out["mfe_r"], 0.0)
        self.assertIsNone(out["reached_1r_at"])
        gap = self.frame([(106.5, 106.8, 106.4, 106.6)])
        out = live.follow_step(self.trade(), gap, np.ones(1))
        self.assertAlmostEqual(out["ref_r"], -1.5)             # een gat door de stop vult op de open

    def test_a_split_measures_from_the_last_fill(self):
        t = {**self.trade(), "legs_filled": json.dumps([[0.4, 105.0, "2026-10-15T15:00:00+00:00"], [0.6, 104.0, "2026-10-15T15:15:00+00:00"]])}
        c = self.frame([(105, 105.1, 103.0, 105), (105, 105.1, 103.0, 105), (105, 105.1, 103.0, 104)])
        out = live.follow_step(t, c, np.ones(3))
        self.assertEqual(out["checked_until"], c["timestamp"].iloc[2].isoformat())
        self.assertIsNotNone(out["reached_1r_at"])
        self.assertEqual(out["reached_1r_at"], c["timestamp"].iloc[2].isoformat())     # pas de candle na de laatste vulling

    def test_the_reference_trails_in_the_favourable_direction_only(self):
        c = self.frame([(105, 105.1, 104.9, 105), (105, 105.0, 102.0, 102.5), (102.5, 103.4, 102.4, 103.0)])
        out = live.follow_step(self.trade(), c, np.full(3, 0.5))
        self.assertAlmostEqual(out["ref_stop"], 102.0 + 3.0 * 0.5)       # het uiterste 102,0 plus 3 ATR; de hogere low van daarna schuift niets terug
        self.assertIsNone(out["ref_r"])
        c2 = self.frame([(105, 105.1, 104.9, 105), (105, 105.0, 102.0, 102.5), (102.5, 103.4, 102.4, 103.0), (103.0, 103.6, 102.9, 103.5)])
        out = live.follow_step(self.trade(), c2, np.full(4, 0.5))
        self.assertAlmostEqual(out["ref_r"], 1.5)                          # uit op de trailing stop 103,5
        self.assertEqual(out["ref_closed_at"], c2["timestamp"].iloc[3].isoformat())
        self.assertIsNone(out["stop_hit_at"])                               # de echte stop (106) is niet geraakt: de meting loopt door


class BodyTest(unittest.TestCase):
    def test_alert_says_choose_your_own_target(self):
        row = {"coin": "ARB", "direction": "short", "family": "zone", "range_tf": "2h", "legs": "[[1.0, 0.199]]", "stop": 0.2052, "range_high": 0.2045,
               "range_low": 0.17, "grade": "A", "score": 85.0, "liq_json": '{"ok": false}'}
        body = live.alert_body(row, 0.1985)
        self.assertIn("Limiet 0.1990", body)
        self.assertIn("Stop 0.2052", body)
        self.assertIn("doel kies je zelf", body)
        self.assertIn("Overkant 0.1700", body)
        self.assertIn("Zone-retest 2u", body)
        self.assertIn("Ongetest", body)
        self.assertNotIn("—", body)

    def test_a_long_points_at_the_upper_edge_and_a_split_names_its_shares(self):
        row = {"coin": "ARB", "direction": "long", "family": "sweep", "range_tf": "1h", "legs": "[[0.4, 0.17], [0.6, 0.18]]", "stop": 0.165,
               "range_high": 0.2045, "range_low": 0.17, "grade": "B", "score": 70.0, "liq_json": '{"ok": true}'}
        body = live.alert_body(row, None)
        self.assertIn("Overkant 0.2045", body)
        self.assertIn("Limiet 0.1700 (40%)", body)
        self.assertIn("Limiet 0.1800 (60%)", body)
        self.assertIn("liquidaties", body)
        self.assertIn("Range sweep 1u", body)


class EngineCase(DbCase):
    """De motor tegen de kunstmatige markt van de lab-fixture. De beurs is een naad (fetch_bars) die ALLE candles teruggeeft, ook die na `now`: wat
    de motor niet mag zien moet hij zelf wegsnijden."""

    def setUp(self):
        super().setUp()
        self.student = repo.create_user("b", "x", 0, 1)
        self.ceo = repo.get_user_by_username("a")["id"]
        self.b15, self.b1h, self.b4h = frames()
        self.bars = {"15m": self.b15, "1h": self.b1h, "4h": self.b4h}
        self.pushed = []
        for p in (mock.patch.object(config, "CEO_USERNAME", ""), mock.patch.object(config, "RANGE_SWEEP_ENABLED", True),
                  mock.patch.object(config, "RANGE_SWEEP_PUBLIC", False),
                  mock.patch.object(rl, "VARIANTS", rl.VARIANTS + (TEST_VARIANT,)),
                  mock.patch.object(live, "COINS", ("BTC",)), mock.patch.object(live, "fetch_bars", self.fetch),
                  mock.patch("app.push_notify.send_push", self.fake_push)):
            p.start()
            self.addCleanup(p.stop)
        self.open_gate()

    def open_gate(self, stop_ok=True, edge_ok=False):
        # De poort leest de toets op stopkwaliteit; de strenge toets op een voordeel is geen voorwaarde voor een proef.
        repo.set_rule_lab(live.STOP_KEY, stop_ok, {"variant": "RZ_T", "stop_name": "zone_025"}, db.now_iso())
        repo.set_rule_lab(live.EDGE_KEY, edge_ok, {"variant": "RZ_T", "stop_name": "zone_025"}, db.now_iso())

    def fetch(self, coin, timeframe, limit):
        # De laatste `limit` candles, maar met een stuk toekomst erbij: wat na `now` komt mag de motor nooit zien en moet hij zelf wegsnijden.
        df = self.bars[timeframe]
        return df[df["timestamp"] < pd.Timestamp(self.now) + pd.Timedelta(hours=12)].tail(limit).reset_index(drop=True)

    async def fake_push(self, user_id, title, body, url, silent=False, tag=None, badge=None):
        self.pushed.append({"user": user_id, "title": title, "body": body, "url": url, "silent": silent, "tag": tag})

    def run_(self, fn, now):
        self.now = now.to_pydatetime() if isinstance(now, pd.Timestamp) else now
        asyncio.run(fn(self.now))

    def scan(self, now):
        self.run_(live.scan, now)

    def track(self, now):
        self.run_(live.track, now)

    def follow(self, now):
        self.run_(live.follow, now)

    def setups(self, *states):
        return repo.list_range_sweep_setups(states or ("waiting", "niet_gemeld", "filled", "verlopen", "weggelopen", "stop_voor_vulling"))

    def signals(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM signals WHERE trade_type = ? ORDER BY id", (live.TRADE_TYPE,))]

    def notifications(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM notifications ORDER BY id")]


class GateTest(EngineCase):
    def test_no_lab_row_creates_nothing(self):
        with db.session() as conn:
            conn.execute("DELETE FROM rule_status")
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(self.setups(), [])
        self.assertEqual(self.pushed, [])

    def test_failed_stop_quality_creates_nothing_even_when_the_edge_test_passed(self):
        self.open_gate(stop_ok=False, edge_ok=True)
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(self.setups(), [])

    def test_passed_stop_quality_is_enough_without_the_edge_test(self):
        self.open_gate(stop_ok=True, edge_ok=False)
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(len(self.setups("waiting")), 1)

    def test_the_flag_switches_the_engine_off(self):
        with mock.patch.object(config, "RANGE_SWEEP_ENABLED", False):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(self.setups(), [])

    def test_only_shortly_after_a_closed_15m_candle(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=11))
        self.assertEqual(self.setups(), [])

    def test_a_negative_series_switches_the_engine_off_and_says_so(self):
        for k in range(config.RANGE_SWEEP_MAX_NEGATIVE):
            sid = repo.insert_signal({"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": live.TRADE_TYPE, "price": 100.0,
                                      "stop_loss": 101.0, "take_profit": None, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}, chain_it=False)
            repo.set_trade_result(sid, -1.0, db.now_iso())
            repo.mark_signal_auto_outcome(sid, "stop_loss", db.now_iso())
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(self.setups(), [])
        self.assertTrue(any("Range sweep staat uit" in n["title"] for n in self.notifications()))


class ScanTest(EngineCase):
    def test_nothing_before_the_candle_that_makes_the_setup_has_closed(self):
        # In de fixture ligt de setup al in de toekomstige candles; die mag de motor niet zien.
        self.scan(SHORT_PLACED - pd.Timedelta(minutes=55))
        self.scan(SHORT_PLACED - pd.Timedelta(minutes=5))
        self.assertEqual(self.setups(), [])

    def test_one_setup_once_and_only_for_the_ceo(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        rows = self.setups()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["coin"], r["direction"], r["variant"], r["family"], r["state"]), ("BTC", "short", "RZ_T", "zone", "waiting"))
        self.assertEqual(json.loads(r["legs"]), [[1.0, 105.375]])
        self.assertAlmostEqual(r["stop"], rs.final_stop(rs.find_setups(rs.build_frames(self.b15, self.b1h, self.b4h), "1h", "zone", "zone", "slot", False)[0][1], "zone_025"))
        self.assertEqual(pd.Timestamp(r["placed_at"]), SHORT_PLACED)
        self.assertEqual(pd.Timestamp(r["expires_at"]), SHORT_PLACED + pd.Timedelta(hours=24))
        self.assertIn("✓", r["reason"])
        plan = json.loads(r["plan"])
        self.assertLessEqual(len(plan["candles"]), 80)
        self.assertEqual(json.loads(r["liq_json"])["ok"], False)
        self.assertEqual(set(p["user"] for p in self.pushed), {self.ceo} if self.pushed else set())

    def test_repeated_runs_and_a_restart_do_not_duplicate_or_respam(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        first_pushes = len(self.pushed)
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=15))
        self.assertEqual(len(self.setups()), 1)
        self.assertEqual(len(self.pushed), first_pushes)

    def test_the_same_zone_is_not_announced_twice_for_a_different_placing_time(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        row = self.setups()[0]
        with db.session() as conn:
            conn.execute("UPDATE range_sweep_setups SET placed_at = ? WHERE id = ?", ((SHORT_PLACED - pd.Timedelta(hours=1)).isoformat(), row["id"]))
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(len(self.setups()), 1)

    def grade_pushes(self, grade):
        with mock.patch.object(chance_checks, "grade_of", return_value=grade):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        return [p for p in self.pushed if "wacht" in p["title"]]

    def test_grade_a_is_loud_b_is_silent_c_has_no_push(self):
        a = self.grade_pushes("A")
        self.assertEqual([(p["user"], p["silent"]) for p in a], [(self.ceo, False)])
        self.assertEqual(a[0]["tag"], f"range-sweep-{self.setups()[0]['id']}")
        self.assertEqual(a[0]["url"], f"/structuur#range-sweep-{self.setups()[0]['id']}")

    def test_grade_b_is_silent(self):
        b = self.grade_pushes("B")
        self.assertEqual([(p["user"], p["silent"]) for p in b], [(self.ceo, True)])

    def test_grade_c_waits_without_a_push_but_is_stored(self):
        self.assertEqual(self.grade_pushes("C"), [])
        self.assertEqual(len(self.setups("waiting")), 1)

    def test_the_daily_cap_keeps_the_setup_but_sends_nothing(self):
        self.scan(LONG_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(len(self.setups("waiting")), 1)
        before = len(self.pushed)
        with mock.patch.object(config, "RANGE_SWEEP_MAX_PER_DAY", 1):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual([r["direction"] for r in self.setups("niet_gemeld")], ["short"])
        self.assertEqual(len(self.pushed), before)

    def test_the_push_policy_applies_to_the_setup_push(self):
        # Pauze: geen push, wel een rustige melding (send_kans_push).
        with db.session() as conn:
            conn.execute("UPDATE users SET push_paused_until = ? WHERE id = ?", ((pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=1)).isoformat(), self.ceo))
        with mock.patch.object(chance_checks, "grade_of", return_value="A"):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual([p for p in self.pushed if "wacht" in p["title"]], [])
        self.assertTrue(any("pauze" in n["body"] for n in self.notifications()))

    def test_one_failing_viewer_does_not_block_the_setup(self):
        async def boom(*a, **k):
            raise RuntimeError("push stuk")
        with mock.patch("app.push_notify.send_push", boom), mock.patch.object(chance_checks, "grade_of", return_value="A"):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual(len(self.setups("waiting")), 1)
        with mock.patch.object(chance_checks, "grade_of", return_value="A"):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual([p for p in self.pushed if "wacht" in p["title"]], [])      # de vlag stond al: geen herhaling



def setup_row(**kw):
    row = {"coin": "BTC", "direction": "short", "variant": "RZ_T", "family": "zone", "stop_name": "zone_025", "range_tf": "1h", "range_high": 90.0,
           "range_low": 80.0, "range_first_at": "2025-03-04T00:00:00+00:00", "zone_low": 120.0, "zone_high": 121.0, "zone_at": "2025-03-04T12:00:00+00:00",
           "sweep_at": None, "extreme": None, "placed_at": "2025-03-08T00:00:00+00:00", "legs": json.dumps([[1.0, 120.0]]), "stop": 125.0, "atr_t": 1.0,
           "score": 85.0, "grade": "A", "reason": "✓ x", "features": "{}", "liq_json": "{}", "expires_at": "2025-03-09T00:00:00+00:00", "plan": "{}"}
    row.update(kw)
    return row


class TrackTest(EngineCase):
    def fill_short(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))        # de limiet van 105,375 raakt in de candle van 17:45
        return self.setups("filled")[0]

    def test_a_fill_makes_one_signal_a_trade_a_journal_line_and_a_push(self):
        s = self.fill_short()
        sigs = self.signals()
        self.assertEqual(len(sigs), 1)
        sig = sigs[0]
        self.assertEqual((sig["direction"], sig["trade_type"], sig["pattern_name"], sig["take_profit"], sig["category"]), ("short", "range_sweep", "RZ_T", None, "day_trading"))
        self.assertAlmostEqual(sig["price"], 105.375)
        self.assertAlmostEqual(sig["stop_loss"], s["stop"])
        self.assertIsNone(repo.get_chain_link(sig["id"]))
        self.assertEqual(s["signal_id"], sig["id"])
        with db.session() as conn:
            users = [r["user_id"] for r in conn.execute("SELECT user_id FROM journal_entries WHERE signal_id = ?", (sig["id"],))]
        self.assertEqual(users, [self.ceo])
        trade = repo.list_open_range_sweep_trades()[0]
        self.assertEqual((trade["signal_id"], trade["setup_id"]), (sig["id"], s["id"]))
        self.assertAlmostEqual(trade["entry"], 105.375)
        self.assertEqual(pd.Timestamp(trade["filled_at"]), SHORT_PLACED + pd.Timedelta(minutes=45))
        self.assertEqual(json.loads(trade["legs_filled"]), [[1.0, 105.375, (SHORT_PLACED + pd.Timedelta(minutes=45)).isoformat()]])
        filled = [p for p in self.pushed if "gevuld" in p["title"]]
        self.assertEqual([p["user"] for p in filled], [self.ceo])
        self.assertIn("doel kies je zelf", filled[0]["body"])
        self.assertIn("Limiet geraakt op 105.38", filled[0]["body"].replace("105.3750", "105.38").replace("105.375", "105.38"))
        self.assertEqual(filled[0]["tag"], f"range-sweep-{s['id']}")

    def test_a_weak_chance_still_gets_its_fill_notification(self):
        with mock.patch.object(chance_checks, "grade_of", return_value="C"):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.assertEqual([p for p in self.pushed if "wacht" in p["title"]], [])
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))
        self.assertEqual(len([p for p in self.pushed if "gevuld" in p["title"]]), 1)

    def test_a_fill_while_the_viewer_paused_leaves_a_calm_notification(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        with db.session() as conn:
            conn.execute("UPDATE users SET push_paused_until = ? WHERE id = ?", ((pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=1)).isoformat(), self.ceo))
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))
        self.assertTrue(any("gevuld" in n["title"] and "pauze" in n["body"] for n in self.notifications()))

    def test_repeated_tracking_changes_nothing(self):
        self.fill_short()
        pushes = len(self.pushed)
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=20))
        self.assertEqual(len(self.signals()), 1)
        self.assertEqual(len(repo.list_open_range_sweep_trades()), 1)
        self.assertEqual(len(self.pushed), pushes)

    def test_nothing_before_the_limit_is_touched(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.track(SHORT_PLACED + pd.Timedelta(minutes=35))                # 17:30 vormt nog; het hoog is dan 105,275
        self.assertEqual(self.signals(), [])
        self.assertEqual(len(self.setups("waiting")), 1)

    def test_a_filled_candle_still_forming_counts_as_a_fill(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.track(SHORT_PLACED + pd.Timedelta(minutes=50))                # 17:45 vormt nog, het hoog 105,425 raakte de limiet al
        self.assertEqual(len(self.signals()), 1)

    def insert_row(self, **kw):
        return repo.insert_range_sweep_setup(setup_row(**kw))

    def test_unfilled_order_expires_after_24_hours_with_a_calm_notice(self):
        sid = self.insert_row()
        self.track(pd.Timestamp("2025-03-08 23:00", tz="UTC"))
        self.assertEqual(repo.list_range_sweep_setups(("waiting",))[0]["id"], sid)         # nog geen 24 uur
        self.track(pd.Timestamp("2025-03-09 00:05", tz="UTC"))
        self.assertEqual([r["state"] for r in self.setups()], ["verlopen"])
        self.assertEqual(self.signals(), [])
        self.assertEqual(self.pushed, [])
        self.assertTrue(any("verlopen" in n["title"] or "verlopen" in n["body"] for n in self.notifications()))
        n = len(self.notifications())
        self.track(pd.Timestamp("2025-03-09 00:20", tz="UTC"))
        self.assertEqual(len(self.notifications()), n)

    def test_a_weak_or_unannounced_setup_that_expires_is_not_announced(self):
        self.insert_row(grade="C")
        self.track(pd.Timestamp("2025-03-09 00:05", tz="UTC"))
        self.assertEqual([r["state"] for r in self.setups()], ["verlopen"])
        self.assertEqual(self.notifications(), [])

    def test_price_reaching_the_middle_before_the_fill_cancels(self):
        self.insert_row(range_high=140.0, range_low=104.0, legs=json.dumps([[1.0, 120.0]]))      # midden 122 ligt boven de koers: geraakt
        self.track(pd.Timestamp("2025-03-08 02:00", tz="UTC"))
        self.assertEqual([r["state"] for r in self.setups()], ["weggelopen"])

    def test_a_candle_opening_past_the_stop_cancels_before_the_fill(self):
        self.insert_row(stop=100.0)
        self.track(pd.Timestamp("2025-03-08 02:00", tz="UTC"))
        self.assertEqual([r["state"] for r in self.setups()], ["stop_voor_vulling"])

    def test_a_split_updates_the_entry_when_the_second_order_fills(self):
        self.insert_row(legs=json.dumps([[0.4, 106.0], [0.6, 105.4]]), stop=108.0, range_high=90.0, range_low=80.0,
                        placed_at="2025-03-07T17:00:00+00:00", expires_at="2025-03-08T17:00:00+00:00")
        self.track(pd.Timestamp("2025-03-07 17:50", tz="UTC"))              # 105,4 raakt in 17:45, 106,0 nog niet (hoog 105,425)
        sig = self.signals()[0]
        self.assertAlmostEqual(sig["price"], 105.4)
        self.track(pd.Timestamp("2025-03-07 18:50", tz="UTC"))              # 106,0 raakt in 18:30 (hoog 105,875 niet) of 18:45 (106,025)
        sig = repo.get_signal(sig["id"])
        self.assertAlmostEqual(sig["price"], 0.4 * 106.0 + 0.6 * 105.4)
        trade = repo.list_open_range_sweep_trades()[0]
        self.assertAlmostEqual(trade["entry"], 0.4 * 106.0 + 0.6 * 105.4)
        self.assertEqual(len(json.loads(trade["legs_filled"])), 2)
        self.assertEqual(len(self.signals()), 1)
        self.assertEqual(len([p for p in self.pushed if "gevuld" in p["title"]]), 1)
        self.track(pd.Timestamp("2025-03-07 19:05", tz="UTC"))
        self.assertAlmostEqual(repo.get_signal(sig["id"])["price"], 0.4 * 106.0 + 0.6 * 105.4)


class FollowEngineTest(EngineCase):
    def filled(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))
        return self.signals()[0]

    def outcome(self, sid):
        with db.session() as conn:
            row = conn.execute("SELECT * FROM trade_results WHERE signal_id = ?", (sid,)).fetchone()
        return repo.get_signal(sid), (dict(row) if row else None)

    def test_the_stop_is_hit_once_and_closes_the_signal_as_a_stop_loss(self):
        sig = self.filled()
        pushes = len(self.pushed)
        self.follow(SWEEP_AT + pd.Timedelta(hours=1, minutes=5))             # de prik van 06:15 (hoog 106,5) raakt de stop van 106,19
        trade = [t for t in repo.list_range_sweep_trades(5)][0]
        self.assertIsNotNone(trade["stop_hit_at"])
        self.assertIsNotNone(trade["closed_at"])
        self.assertIsNotNone(trade["ref_r"])
        self.assertEqual(repo.list_open_range_sweep_trades(), [])
        s, res = self.outcome(sig["id"])
        self.assertIn(s["auto_outcome"], ("take_profit", "stop_loss"))
        self.assertEqual(res["r_value"], trade["ref_r"])
        self.assertEqual(s["auto_outcome"], "take_profit" if trade["ref_r"] > 0 else "stop_loss")
        stops = [p for p in self.pushed[pushes:] if "stop geraakt" in p["title"].lower()]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["user"], self.ceo)
        self.assertIn("R", stops[0]["body"])
        n = len(self.pushed)
        self.follow(SWEEP_AT + pd.Timedelta(hours=1, minutes=20))
        self.assertEqual(len(self.pushed), n)

    def test_a_stop_on_the_forming_candle_is_reported_once(self):
        sig = self.filled()
        pushes = len(self.pushed)
        self.follow(SWEEP_AT + pd.Timedelta(minutes=20))                     # 06:15 vormt nog en staat al voorbij de stop
        trade = repo.list_range_sweep_trades(5)[0]
        self.assertEqual(pd.Timestamp(trade["stop_hit_at"]), SWEEP_AT + pd.Timedelta(minutes=15))
        self.assertEqual(len([p for p in self.pushed[pushes:] if "stop geraakt" in p["title"].lower()]), 1)
        self.follow(SWEEP_AT + pd.Timedelta(hours=2))
        self.assertEqual(len([p for p in self.pushed[pushes:] if "stop geraakt" in p["title"].lower()]), 1)
        self.assertIsNotNone(self.outcome(sig["id"])[1])

    def test_nothing_while_the_stop_is_not_reached(self):
        sig = self.filled()
        pushes = len(self.pushed)
        self.follow(SHORT_PLACED + pd.Timedelta(hours=3))
        trade = repo.list_range_sweep_trades(5)[0]
        self.assertIsNone(trade["stop_hit_at"])
        self.assertGreater(trade["mae_r"], 0.0)
        self.assertEqual(len(self.pushed), pushes)
        self.assertIsNone(self.outcome(sig["id"])[0]["auto_outcome"])

    def test_follow_does_not_see_the_future(self):
        self.filled()
        self.follow(SHORT_PLACED + pd.Timedelta(hours=3))
        trade = repo.list_range_sweep_trades(5)[0]
        self.assertLessEqual(pd.Timestamp(trade["checked_until"]), SHORT_PLACED + pd.Timedelta(hours=3))
        self.assertIsNone(trade["stop_hit_at"])

    def _flat_market(self, price=100.5, n=1500):
        idx = pd.date_range("2025-03-01", periods=n, freq="15min", tz="UTC")
        b15 = pd.DataFrame({"timestamp": idx, "open": price, "high": price + 0.1, "low": price - 0.1, "close": price, "volume": 1.0})
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        b1h = b15.set_index("timestamp").resample("1h").agg(agg).dropna().reset_index()
        b4h = b15.set_index("timestamp").resample("4h").agg(agg).dropna().reset_index()
        self.bars = {"15m": b15, "1h": b1h, "4h": b4h}
        return b15

    def _synthetic_long(self):
        self._flat_market()
        repo.insert_range_sweep_setup(setup_row(direction="long", legs=json.dumps([[1.0, 100.4]]), stop=99.0, range_high=105.0, range_low=95.0,
                                                placed_at="2025-03-07T00:00:00+00:00", expires_at="2025-03-08T00:00:00+00:00"))
        self.track(pd.Timestamp("2025-03-07 01:00", tz="UTC"))
        return self.signals()[0]["id"]

    def test_after_seven_days_the_reference_closes_on_the_last_candle_inside_the_horizon(self):
        sid = self._synthetic_long()
        self.follow(pd.Timestamp("2025-03-10 00:00", tz="UTC"))
        self.assertIsNone(self.outcome(sid)[1])                              # nog binnen de 7 dagen: open
        self.assertEqual(len(repo.list_open_range_sweep_trades()), 1)
        pushes = len(self.pushed)
        self.follow(pd.Timestamp("2025-03-15 00:05", tz="UTC"))              # 8 dagen na de vulling
        s, res = self.outcome(sid)
        self.assertEqual(s["auto_outcome"], "take_profit")
        self.assertAlmostEqual(res["r_value"], (100.5 - 100.4) / 1.4, places=6)
        trade = repo.list_range_sweep_trades(5)[0]
        self.assertIsNotNone(trade["closed_at"])
        self.assertIsNone(trade["stop_hit_at"])
        self.assertEqual(repo.list_open_range_sweep_trades(), [])
        calm = self.pushed[pushes:]
        self.assertEqual(len(calm), 1)
        self.assertIn("Meting klaar", calm[0]["body"])
        self.assertIn("beslis je zelf", calm[0]["body"])
        self.follow(pd.Timestamp("2025-03-15 00:20", tz="UTC"))
        self.assertEqual(len(self.pushed), pushes + 1)


class VisibilityAndLevelCheckTest(EngineCase):
    def test_a_student_never_sees_the_trial_but_the_ceo_does(self):
        rows = [{"trade_type": live.TRADE_TYPE}, {"trade_type": "day_trading"}]
        self.assertEqual(rule_live.for_viewer(rows, False), [{"trade_type": "day_trading"}])
        self.assertEqual(rule_live.for_viewer(rows, True), rows)

    def test_the_student_gets_no_journal_line_and_no_push(self):
        self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
        self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))
        sid = self.signals()[0]["id"]
        with db.session() as conn:
            users = {r["user_id"] for r in conn.execute("SELECT user_id FROM journal_entries WHERE signal_id = ?", (sid,))}
        self.assertNotIn(self.student, users)
        self.assertTrue(all(p["user"] != self.student for p in self.pushed))

    def test_public_flag_widens_the_audience(self):
        with mock.patch.object(config, "RANGE_SWEEP_PUBLIC", True):
            self.scan(SHORT_PLACED + pd.Timedelta(minutes=5))
            self.track(SHORT_PLACED + pd.Timedelta(hours=1, minutes=5))
        self.assertIn(self.student, {p["user"] for p in self.pushed})

    def test_level_check_leaves_the_trial_alone(self):
        sid = repo.insert_signal({"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": live.TRADE_TYPE, "price": 105.0,
                                  "stop_loss": 106.0, "take_profit": 99.0, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}, chain_it=False)
        crash = pd.DataFrame({"timestamp": [pd.Timestamp.now(tz="UTC")], "open": [90.0], "high": [107.0], "low": [90.0], "close": [90.0], "volume": [1.0]})
        # Zelfs als de query het signaal teruggeeft (met een doel erop) telt het filter op trade_type: de motor zet uitkomst en R zelf.
        row = {**repo.get_signal(sid), "id": sid}
        with mock.patch.object(repo, "list_unresolved_signals_with_levels", lambda: [row]), \
                mock.patch.object(repo, "list_open_entries_with_levels", lambda: [{**row, "signal_id": sid, "entry_price": 105.0, "user_id": self.ceo}]), \
                mock.patch.object(level_check, "_fetch_since", lambda coin, since: crash), \
                mock.patch.object(level_check.exchange, "fetch_ohlcv", lambda *a, **k: crash):
            asyncio.run(level_check.check_signal_outcomes())
            asyncio.run(level_check.check_open_trades())
        self.assertIsNone(repo.get_signal(sid)["auto_outcome"])
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()
