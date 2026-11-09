"""Obstakels vanaf de instap (CEO, v2-plan punt 2): het doel van de zone-radar en de POC-radar wordt gezocht vanaf de limiet, niet vanaf de koers
op het ontdekkingsmoment, zodat een tegenovergesteld niveau tussen limiet en koers niet buiten beeld valt. Elk niveau draagt zijn herkomst en
het moment waarop het bekend werd. De zone-sweep houdt target_for (vooraf vastgelegd, niets afstellen)."""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import config, db, poc, radar, repo, security
from app import poc_radar as pr
from app import zone_radar as zr
from tests.test_zone_radar import HOUR, START, now_after, tia_like

T0 = pd.Timestamp("2026-10-20T00:00:00Z")


def Z(kind, low, high, tf="1h", atr=0.4, known_at=""):
    return zr.ZoneLevel(tf, kind, low, high, atr, f"{tf}:{kind}:{low}", known_at)


def lv(price, period="day", days=0, touched=None):
    return poc.PocLevel(period, T0 + pd.Timedelta(days=days), price, touched)


class KnownAtTests(unittest.TestCase):
    def test_known_at_is_het_slot_van_de_candle_waarop_de_zone_bekend_werd(self):
        df = tia_like()
        zones = {z.kind: z for z in zr.active_zones(df, "1h", now_after(df))}
        # aanbod: order block-candle 60, de val op candle 61 maakt hem bekend, die sluit om START + 62u
        self.assertEqual(zones["bear"].known_at, (START + 62 * HOUR).isoformat())
        self.assertEqual(zones["bull"].known_at, (START + 82 * HOUR).isoformat())

    def test_bestaande_aanroepen_zonder_known_at_blijven_werken(self):
        self.assertEqual(zr.ZoneLevel("1h", "bull", 1.0, 2.0, 0.1, "k").known_at, "")


class ObstacleListTests(unittest.TestCase):
    ZONES = [Z("bear", 101.0, 102.0, known_at="2026-10-27T13:00:00+00:00"), Z("bear", 98.0, 98.5, tf="4h"), Z("bear", 104.0, 105.0),
             Z("bull", 90.0, 91.0), Z("bull", 94.0, 94.5, tf="4h"), Z("bear", 95.0, 96.0)]

    def test_long_aanbod_boven_de_instap_oplopend(self):
        obs = zr.obstacles("long", self.ZONES, 97.0, stop=96.0)
        self.assertEqual([o["rand"] for o in obs], [98.0, 101.0, 104.0])
        first = obs[0]
        self.assertEqual((first["soort"], first["tf"], first["low"], first["high"], first["key"]), ("aanbod", "4h", 98.0, 98.5, "4h:bear:98.0"))
        self.assertAlmostEqual(first["r"], 1.0)
        self.assertEqual(obs[1]["known_at"], "2026-10-27T13:00:00+00:00")
        self.assertEqual(first["label"], "Aanbod 4u")

    def test_short_vraag_onder_de_instap_aflopend(self):
        obs = zr.obstacles("short", self.ZONES, 97.0, stop=98.0)
        self.assertEqual([o["rand"] for o in obs], [94.5, 91.0])        # de rand die de koers als eerste raakt: de bovenkant
        self.assertEqual(obs[0]["soort"], "vraag")
        self.assertAlmostEqual(obs[0]["r"], 2.5)

    def test_zonder_stop_geen_r(self):
        self.assertIsNone(zr.obstacles("long", self.ZONES, 97.0)[0]["r"])

    def test_target_for_blijft_vanaf_de_koers_voor_de_zone_sweep(self):
        self.assertEqual(zr.target_for("long", self.ZONES, 99.0).low, 101.0)


class ZoneRadarPlanTests(unittest.TestCase):
    # long op de vraagzone 95-96 (stop 94,9), koers 97,0 staat in een aanbodzone 96,8-97,3 die tussen limiet en koers begint
    ZONES = [Z("bull", 95.0, 96.0), Z("bear", 96.8, 97.3, tf="4h"), Z("bear", 100.0, 101.0), Z("bear", 102.0, 103.0), Z("bear", 104.0, 105.0),
             Z("bear", 106.0, 107.0), Z("bear", 108.0, 109.0)]

    def test_obstakel_tussen_limiet_en_koers_wordt_het_doel(self):
        plan = zr.plan_for("long", self.ZONES, 97.0)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["take_profit"], 96.8)                       # vroeger 100,0: de eerste aanbodzone boven de koers
        self.assertEqual((plan["target_tf"], plan["target_low"], plan["target_high"]), ("4h", 96.8, 97.3))

    def test_plan_draagt_hoogstens_vijf_obstakels_en_het_eerste_is_het_doel(self):
        plan = zr.plan_for("long", self.ZONES, 97.0)
        self.assertEqual(len(plan["obstacles"]), zr.MAX_OBSTACLES)
        self.assertEqual(plan["obstacles"][0]["rand"], plan["take_profit"])
        self.assertAlmostEqual(plan["obstacles"][0]["r"], plan["rr"])
        self.assertTrue(plan["obstacles"][0]["tussen"])                    # lag bij het ontstaan tussen limiet en koers
        self.assertFalse(plan["obstacles"][1]["tussen"])

    def test_short_spiegel(self):
        zones = [Z("bear", 104.0, 105.0), Z("bull", 102.6, 103.2), Z("bull", 99.0, 100.0)]
        plan = zr.plan_for("short", zones, 103.0)
        self.assertEqual(plan["take_profit"], 103.2)
        self.assertEqual([o["rand"] for o in plan["obstacles"]], [103.2, 100.0])

    def test_geen_tegenovergestelde_zone_voorbij_de_instap_geen_kaart(self):
        self.assertIsNone(zr.plan_for("long", [Z("bull", 95.0, 96.0), Z("bear", 93.0, 94.0)], 97.0))

    def test_tussen_doel_maakt_de_kaart_niet_gemist(self):
        plan = zr.plan_for("long", self.ZONES, 97.0)
        row = {**plan, "id": 1, "coin": "X", "created_at": "2026-10-27T13:00:00+00:00", "obstacles": json.dumps(plan["obstacles"])}
        self.assertIsNone(zr.miss_take(row))
        card = radar.setup_card(zr.radar_setup(row), 97.0)
        self.assertEqual(card["state"], "wacht")
        self.assertEqual(card["plan"].take, 96.8)

    def test_doel_voorbij_de_koers_houdt_gemist(self):
        plan = zr.plan_for("long", [Z("bull", 95.0, 96.0), Z("bear", 100.0, 101.0)], 97.0)
        row = {**plan, "obstacles": json.dumps(plan["obstacles"])}
        self.assertEqual(zr.miss_take(row), 100.0)
        self.assertEqual(zr.miss_take({"take_profit": 100.0, "obstacles": None}), 100.0)       # oude rij zonder obstakels


class PocRadarPlanTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(config, "SMC_MIN_STOP_PCT", 0.2)
        p.start()
        self.addCleanup(p.stop)

    def test_geraakte_poc_tussen_limiet_en_koers_wordt_het_doel(self):
        # limiet 97, stop 96; geraakte POC 99,5 (2,5R) ligt onder de koers 100. Vroeger telde pas 103.
        levels = [lv(97.0), lv(99.5, days=1, touched=T0 + pd.Timedelta(days=3)), lv(103.0, days=2)]
        long = pr.plan_for("long", levels, [], 100.0, 4.0)
        self.assertEqual(long["take_profit"], 99.5)
        self.assertAlmostEqual(long["rr"], 2.5)

    def test_eerste_niveau_vanaf_de_limiet_onder_2r_geeft_geen_doel(self):
        levels = [lv(97.0), lv(97.5, days=1, touched=T0 + pd.Timedelta(days=3)), lv(103.0, days=2)]
        long = pr.plan_for("long", levels, [], 100.0, 4.0)
        self.assertIsNone(long["take_profit"])
        self.assertEqual(long["obstacles"][0]["rand"], 97.5)               # het niveau staat wel in de lijst

    def test_niveaus_met_bron_prijs_en_known_at(self):
        zone = Z("bear", 101.0, 102.0, tf="4h", known_at="2026-10-21T08:00:00+00:00")
        levels = [lv(97.0), lv(103.0, "week", days=-7)]
        long = pr.plan_for("long", levels, [zone], 100.0, 4.0)
        obs = long["obstacles"]
        self.assertEqual([(o["bron"], o["rand"]) for o in obs], [("zone 4u", 101.0), ("POC week", 103.0)])
        self.assertEqual(obs[0]["known_at"], "2026-10-21T08:00:00+00:00")
        self.assertEqual(obs[1]["known_at"], (T0 - pd.Timedelta(days=7) + pd.Timedelta(days=7)).isoformat())   # einde van de week
        self.assertEqual(obs[1]["label"], "Week-POC week 42")
        self.assertAlmostEqual(obs[0]["r"], 4.0)
        self.assertEqual(long["take_profit"], 101.0)

    def test_geen_niveau_voorbij_de_limiet_geen_doel(self):
        long = pr.plan_for("long", [lv(97.0)], [], 100.0, 4.0)
        self.assertIsNone(long["take_profit"])
        self.assertEqual(long["obstacles"], [])

    def test_short_spiegel(self):
        levels = [lv(103.0), lv(100.5, days=1, touched=T0 + pd.Timedelta(days=3)), lv(97.0, days=2)]
        short = pr.plan_for("short", levels, [], 100.0, 4.0)       # stop 104, 100,5 is 2,5R vanaf 103
        self.assertEqual(short["take_profit"], 100.5)
        self.assertEqual([o["rand"] for o in short["obstacles"]], [100.5, 97.0])

    def test_tussen_doel_maakt_de_kaart_niet_gemist(self):
        levels = [lv(97.0), lv(99.5, days=1, touched=T0 + pd.Timedelta(days=3))]
        long = pr.plan_for("long", levels, [], 100.0, 4.0)
        row = {**long, "id": 3, "coin": "X", "created_at": "2026-10-27T13:00:00+00:00", "obstacles": json.dumps(long["obstacles"])}
        card = radar.setup_card(pr.radar_setup(row), 100.0)
        self.assertEqual(card["state"], "wacht")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "o.db")
        p = mock.patch.object(config, "DATABASE_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_migratie_op_een_oude_database(self):
        conn = sqlite3.connect(self.path)
        conn.executescript("""
            CREATE TABLE zone_radar_setups (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT NOT NULL, direction TEXT NOT NULL, tf TEXT NOT NULL,
                zone_key TEXT NOT NULL, zone_low REAL NOT NULL, zone_high REAL NOT NULL, stop_loss REAL NOT NULL, take_profit REAL NOT NULL,
                rr REAL NOT NULL, atr REAL NOT NULL, target_tf TEXT NOT NULL, target_low REAL NOT NULL, target_high REAL NOT NULL,
                created_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'waiting', ended_at TEXT, signal_id INTEGER, alert_sent INTEGER NOT NULL DEFAULT 0,
                UNIQUE (coin, zone_key));
            CREATE TABLE poc_radar_setups (id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT NOT NULL, direction TEXT NOT NULL, period TEXT NOT NULL,
                period_start TEXT NOT NULL, level_key TEXT NOT NULL, level REAL NOT NULL, limit_price REAL NOT NULL, stop_loss REAL NOT NULL,
                take_profit REAL, rr REAL, atr REAL NOT NULL, target_kind TEXT, target_text TEXT, target_tf TEXT, target_low REAL, target_high REAL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'waiting', ended_at TEXT, alert_sent INTEGER NOT NULL DEFAULT 0,
                signal_id INTEGER, UNIQUE (coin, level_key));
            INSERT INTO zone_radar_setups (coin, direction, tf, zone_key, zone_low, zone_high, stop_loss, take_profit, rr, atr, target_tf, target_low,
                target_high, created_at) VALUES ('SOL', 'long', '1h', 'k', 95, 97, 94, 105, 2.7, 1, '4h', 105, 106, '2026-10-27T10:00:00+00:00');
        """)
        conn.commit()
        conn.close()
        db.init_db()
        db.init_db()                                                       # idempotent
        with db.session() as c:
            for table in ("zone_radar_setups", "poc_radar_setups"):
                self.assertIn("obstacles", {r["name"] for r in c.execute(f"PRAGMA table_info({table})")})
        self.assertIsNone(repo.list_zone_radar_setups()[0]["obstacles"])  # oude rij blijft leeg

    def test_repo_schrijft_obstakels_als_json(self):
        db.init_db()
        obs = [{"soort": "aanbod", "tf": "4h", "rand": 105.0, "r": 2.7, "known_at": "2026-10-27T13:00:00+00:00", "label": "Aanbod 4u"}]
        row = {"coin": "SOL", "direction": "long", "tf": "1h", "zone_key": "1h:bull:x", "zone_low": 95.0, "zone_high": 97.0, "stop_loss": 94.0,
               "take_profit": 105.0, "rr": 2.7, "atr": 1.0, "target_tf": "4h", "target_low": 105.0, "target_high": 106.0, "obstacles": obs}
        repo.insert_zone_radar_setup(row, "2026-10-27T14:00:00+00:00")
        self.assertEqual(json.loads(repo.list_zone_radar_setups()[0]["obstacles"]), obs)
        prow = {"coin": "XRP", "direction": "long", "period": "day", "period_start": T0.isoformat(), "level_key": "day:x", "level": 100.3,
                "limit_price": 100.3, "stop_loss": 99.8, "take_profit": None, "rr": None, "atr": 2.0, "expires_at": "2026-10-30T00:00:00+00:00",
                "obstacles": []}
        repo.insert_poc_radar_setup(prow, "2026-10-27T14:00:00+00:00")
        self.assertEqual(json.loads(repo.list_poc_radar_setups()[0]["obstacles"]), [])


class TextTests(unittest.TestCase):
    OBS = [{"label": "Aanbod 4u", "rand": 0.4512, "r": 1.6, "known_at": "2026-10-27T13:00:00+00:00"},
           {"label": "Aanbod 1u", "rand": 0.4621, "r": 2.3, "known_at": ""},
           {"label": "Week-POC week 43", "rand": 0.47, "r": None, "known_at": ""},
           {"label": "Aanbod 4u", "rand": 0.49, "r": 4.0, "known_at": ""}]

    def test_regels_in_gewone_taal(self):
        from app import kansen
        lines = kansen.obstacle_lines(json.dumps(self.OBS), now=datetime(2026, 10, 31, 12, tzinfo=timezone.utc))
        self.assertEqual(lines, ["Eerste obstakel: Aanbod 4u 0,4512 (1,6\u00a0R) · bekend sinds 27 okt 14:00",
                                 "Daarna: Aanbod 1u 0,4621 (2,3\u00a0R), Week-POC week 43 0,4700"])

    def test_zonder_obstakels_geen_regel(self):
        from app import kansen
        self.assertEqual(kansen.obstacle_lines(None), [])
        self.assertEqual(kansen.obstacle_lines("[]"), [])


class WebDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db")),):
            p.start()
            self.addCleanup(p.stop)
        db.init_db()
        from fastapi.testclient import TestClient
        from web import main
        main._price_cache.clear()
        self.client = TestClient(main.app)
        uid = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
        for p in (mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 0.43),
                  mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen netwerk"))):
            p.start()
            self.addCleanup(p.stop)

    def row(self, **kw):
        row = {"coin": "WLD", "direction": "long", "tf": "4h", "zone_key": "4h:bull:2026-10-20T08:00:00+00:00", "zone_low": 0.4007,
               "zone_high": 0.4174, "stop_loss": 0.4, "take_profit": 0.4512, "rr": 1.6, "atr": 0.0183, "target_tf": "4h", "target_low": 0.4512,
               "target_high": 0.4582}
        row.update(kw)
        return row

    def test_detailblad_toont_de_obstakels(self):
        known = (datetime.now(timezone.utc) - timedelta(days=4)).replace(hour=13, minute=0, second=0, microsecond=0)
        obs = [{"label": "Aanbod 4u", "rand": 0.4512, "r": 1.6, "known_at": known.isoformat()},
               {"label": "Aanbod 1u", "rand": 0.4621, "r": 2.3, "known_at": known.isoformat()}]
        sid = repo.insert_zone_radar_setup(self.row(obstacles=obs), datetime.now(timezone.utc).isoformat())
        text = self.client.get("/smc").text
        sheet = text.split(f'data-kd-item="zone:{sid}"')[1].split("</section>")[0]
        self.assertIn("Eerste obstakel: Aanbod 4u 0,4512 (1,6\u00a0R) · bekend sinds", sheet)
        self.assertIn("Daarna: Aanbod 1u 0,4621 (2,3\u00a0R)", sheet)

    def test_oude_kaart_zonder_obstakels_geen_regel(self):
        sid = repo.insert_zone_radar_setup(self.row(), datetime.now(timezone.utc).isoformat())
        text = self.client.get("/smc").text
        sheet = text.split(f'data-kd-item="zone:{sid}"')[1].split("</section>")[0]
        self.assertNotIn("obstakel", sheet.lower())


if __name__ == "__main__":
    unittest.main()
