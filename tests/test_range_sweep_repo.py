import importlib
import json
import os
import sqlite3
import tempfile
import unittest

NEW_TABLES = ("range_watches", "range_watch_log", "range_sweep_setups", "range_sweep_trades")


class RangeSweepRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = os.path.join(self.tmp.name, "t.db")
        from app import config, db, repo
        importlib.reload(config); importlib.reload(db); importlib.reload(repo)
        self.repo, self.db = repo, db
        db.init_db()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self.old
        self.tmp.cleanup()

    def watch(self, **kw):
        return {"coin": "ARB", "tf": "2h", "range_high": 0.2045, "range_low": 0.17, "first_at": "2026-10-05T00:00:00+00:00",
                "found_at": "2026-10-10T00:00:00+00:00", "atr": 0.003, **kw}

    def setup_row(self, **kw):
        return {"coin": "ARB", "direction": "short", "variant": "RZ_2H", "family": "zone", "stop_name": "zone_025", "range_tf": "2h",
                "range_high": 0.2045, "range_low": 0.17, "range_first_at": "2026-10-05T00:00:00+00:00", "zone_low": 0.199, "zone_high": 0.2045,
                "zone_at": "2026-10-05T04:00:00+00:00", "sweep_at": None, "extreme": None, "placed_at": "2026-10-16T15:00:00+00:00",
                "legs": "[[1.0, 0.199]]", "stop": 0.2052, "atr_t": 0.003, "score": 85.0, "grade": "A", "reason": "✓ a", "features": "{}",
                "liq_json": "{}", "expires_at": "2026-10-17T15:00:00+00:00", "plan": "{}", **kw}

    def test_watch_is_unique_per_coin_tf_and_start(self):
        a, new_a = self.repo.upsert_range_watch(self.watch())
        b, new_b = self.repo.upsert_range_watch(self.watch(range_high=0.205))
        self.assertEqual((a == b, new_a, new_b), (True, True, False))
        self.assertEqual(self.repo.list_range_watches()[0]["range_high"], 0.205)
        self.assertTrue(self.repo.mark_range_watch_edge(a, "high"))
        self.assertFalse(self.repo.mark_range_watch_edge(a, "high"))
        self.assertTrue(self.repo.mark_range_watch_edge(a, "low"))

    def test_other_start_is_other_watch_and_state_filters(self):
        a, _ = self.repo.upsert_range_watch(self.watch())
        b, new = self.repo.upsert_range_watch(self.watch(first_at="2026-10-06T00:00:00+00:00"))
        self.assertTrue(new)
        self.assertNotEqual(a, b)
        self.repo.set_range_watch_state(a, "gebroken")
        self.assertEqual([w["id"] for w in self.repo.list_range_watches()], [b])
        self.assertEqual({w["id"] for w in self.repo.list_range_watches(("actief", "gebroken"))}, {a, b})
        self.assertIsNotNone([w for w in self.repo.list_range_watches(("gebroken",))][0]["ended_at"])

    def test_ended_watch_is_not_reopened_by_upsert(self):
        a, _ = self.repo.upsert_range_watch(self.watch())
        self.repo.set_range_watch_state(a, "gesweept")
        _, new = self.repo.upsert_range_watch(self.watch())
        self.assertFalse(new)
        self.assertEqual(self.repo.list_range_watches(), [])

    def test_push_budget_count(self):
        w, _ = self.repo.upsert_range_watch(self.watch())
        self.repo.log_range_watch_push(1, w, "gevonden", "2026-10-16T10:00:00+00:00", True)
        self.repo.log_range_watch_push(1, w, "rand_high", "2026-10-16T11:00:00+00:00", False)
        self.repo.log_range_watch_push(1, w, "rand_low", "2026-10-15T11:00:00+00:00", True)
        self.repo.log_range_watch_push(2, w, "gevonden", "2026-10-16T10:00:00+00:00", True)
        self.assertEqual(self.repo.count_range_watch_pushes(1, "2026-10-16T00:00:00+00:00"), 1)

    def test_setup_is_unique(self):
        row = self.setup_row()
        self.assertIsNotNone(self.repo.insert_range_sweep_setup(row))
        self.assertIsNone(self.repo.insert_range_sweep_setup(row))
        self.assertEqual(len(self.repo.list_range_sweep_setups(("waiting",))), 1)

    def test_setup_state_and_since_filter(self):
        a = self.repo.insert_range_sweep_setup(self.setup_row())
        b = self.repo.insert_range_sweep_setup(self.setup_row(placed_at="2026-10-16T16:00:00+00:00"))
        self.repo.set_range_sweep_setup_state(a, "filled", signal_id=7)
        got = self.repo.list_range_sweep_setups(("filled",))
        self.assertEqual((got[0]["id"], got[0]["signal_id"]), (a, 7))
        self.repo.set_range_sweep_setup_state(b, "expired")
        self.assertIsNone(self.repo.list_range_sweep_setups(("expired",))[0]["signal_id"])
        self.assertEqual(len(self.repo.list_range_sweep_setups(("filled", "expired"), since_iso="2026-10-16T15:30:00+00:00")), 1)

    def test_trade_roundtrip(self):
        sid = self.repo.insert_signal({"coin": "ARB", "direction": "short", "category": "day_trading", "trade_type": "range_sweep",
                                       "price": 0.199, "confidence": "laag", "technical_confirmed": 0}, chain_it=False)
        setup = self.repo.insert_range_sweep_setup(self.setup_row())
        self.repo.insert_range_sweep_trade(sid, setup, json.dumps([[1.0, 0.199]]), 0.199, 0.2052, "2026-10-16T16:00:00+00:00")
        open_ = self.repo.list_open_range_sweep_trades()
        self.assertEqual([t["signal_id"] for t in open_], [sid])
        self.assertEqual(open_[0]["checked_until"], "2026-10-16T16:00:00+00:00")
        self.assertEqual((open_[0]["mae_r"], open_[0]["ref_stop"], open_[0]["ref_extreme"]), (0, 0.2052, 0.199))
        self.repo.update_range_sweep_trade(sid, mae_r=0.4, reached_1r_at="2026-10-16T17:00:00+00:00", checked_until="2026-10-16T17:00:00+00:00")
        self.repo.update_range_sweep_trade(sid, closed_at="2026-10-17T00:00:00+00:00", ref_r=1.5)
        got = self.repo.list_range_sweep_trades(10)
        self.assertEqual((got[0]["mae_r"], got[0]["ref_r"], got[0]["coin"]), (0.4, 1.5, "ARB"))
        self.assertEqual(self.repo.list_open_range_sweep_trades(), [])
        self.repo.set_signal_price(sid, 0.2)
        self.assertEqual(self.repo.get_signal(sid)["price"], 0.2)

    def test_update_trade_refuses_unknown_field(self):
        with self.assertRaises(ValueError):
            self.repo.update_range_sweep_trade(1, setup_id=2)
        with self.assertRaises(ValueError):
            self.repo.update_range_sweep_trade(1, **{"mae_r = 0, stop": 1})

    def test_migration_is_idempotent_and_adds_tables_to_an_old_database(self):
        a, _ = self.repo.upsert_range_watch(self.watch())
        with self.db.session() as conn:
            for t in NEW_TABLES:
                conn.execute(f"DROP TABLE {t}")
        raw = sqlite3.connect(os.environ["DATABASE_PATH"])
        self.assertEqual(raw.execute("SELECT count(*) FROM sqlite_master WHERE name IN (%s)" % ",".join("?" * 4), NEW_TABLES).fetchone()[0], 0)
        raw.close()
        self.db.init_db()
        self.db.init_db()
        self.assertEqual(self.repo.list_range_watches(), [])
        self.repo.upsert_range_watch(self.watch())
        self.assertEqual(len(self.repo.list_range_watches()), 1)

    def test_range_sweep_is_ceo_only_by_default(self):
        from app import rule_live
        importlib.reload(rule_live)
        self.assertIn("range_sweep", rule_live.CEO_ONLY_TYPES)

    def test_options_default_off(self):
        from app import config
        self.assertEqual((config.RANGE_SWEEP_ENABLED, config.RANGE_WATCH_ENABLED, config.RANGE_SWEEP_PUBLIC), (False, False, False))
        self.assertEqual((config.RANGE_WATCH_MAX_PER_DAY, config.RANGE_SWEEP_MAX_PER_DAY, config.RANGE_SWEEP_MAX_NEGATIVE), (3, 6, 30))
