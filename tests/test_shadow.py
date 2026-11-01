"""Schaduwvarianten (app/shadow.py, app/shadow_live.py, scripts/schaduw.py): register, promotieregel, meting zonder melding of signaal,
promoveren naar de config-overlay die de motor leest, en terugdraaien."""
import asyncio
import importlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

from app import db, push_notify, repo, shadow, shadow_live
from app import zone_radar as zr
from app import zone_radar_live
from app.replay import stats
from tests.test_samenval import DbCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
schaduw = importlib.import_module("schaduw")

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 1, 3, 17, tzinfo=timezone.utc)


def results(arm: str, values: list[float], start=START, spacing_h: float = 20.0) -> list[dict]:
    return [{"arm": arm, "state": "take_profit" if v > 0 else "stop_loss", "r_net": v,
             "outcome_at": (start + timedelta(hours=spacing_h * i)).isoformat()} for i, v in enumerate(values)]


def put(variant_id: str, r: dict) -> None:
    """Een afgeronde schaduwtrade rechtstreeks in de tabel: de promotieregel leest alleen arm, stand, R en moment."""
    with db.session() as conn:
        n = conn.execute("SELECT COUNT(*) FROM shadow_results").fetchone()[0]
        conn.execute("""INSERT INTO shadow_results (variant_id, arm, plan_key, coin, direction, created_at, expires_at, limit_price, stop_loss,
                        take_profit, state, outcome_at, r_net) VALUES (?, ?, ?, 'BTC', 'long', ?, ?, 100, 99, 102, ?, ?, ?)""",
                     (variant_id, r["arm"], f"k{n}", START.isoformat(), START.isoformat(), r["state"], r["outcome_at"], r["r_net"]))


def alternating(n: int, win: float, loss: float = -1.0) -> list[float]:
    return [win if i % 2 == 0 else loss for i in range(n)]


class DiffBootstrapTest(unittest.TestCase):
    def test_duidelijk_verschil_geeft_marge_boven_nul(self):
        weeks = [f"2026-W{w:02d}" for w in range(30, 40) for _ in range(6)]
        lo, hi = stats.cluster_bootstrap_diff([1.0, 0.5] * 30, weeks, [0.0, -0.5] * 30, weeks)
        self.assertGreater(lo, 0)
        self.assertGreaterEqual(hi, lo)

    def test_een_week_geeft_het_puntverschil(self):
        self.assertEqual(stats.cluster_bootstrap_diff([1.0], ["w"], [0.5], ["w"]), (0.5, 0.5))


class VerdictTest(unittest.TestCase):
    def test_te_weinig_trades_wacht(self):
        v = shadow.verdict(results("variant", alternating(49, 2.0)) + results("hoofd", alternating(60, 0.5)))
        self.assertEqual(v["verdict"], "wachten")
        self.assertEqual(v["n_variant"], 49)

    def test_beter_in_beide_helften_en_marge_promoveert(self):
        v = shadow.verdict(results("variant", alternating(60, 2.0)) + results("hoofd", alternating(60, 0.5)))
        self.assertEqual(v["verdict"], "promoveren")
        self.assertGreater(v["verschil"], 0)
        self.assertTrue(all(h["beter"] for h in v["helften"]))

    def test_alleen_beter_in_de_tweede_helft_wacht(self):
        variant = alternating(30, 0.5) + alternating(30, 3.0)
        v = shadow.verdict(results("variant", variant) + results("hoofd", alternating(60, 1.0)))
        self.assertNotEqual(v["verdict"], "promoveren")
        self.assertFalse(v["helften"][0]["beter"])

    def test_duidelijk_slechter_na_vijftig_valt_af(self):
        v = shadow.verdict(results("variant", alternating(50, 0.2)) + results("hoofd", alternating(50, 2.0)))
        self.assertEqual(v["verdict"], "afvallen")

    def test_na_honderd_niet_beter_valt_af(self):
        same = alternating(100, 1.0)
        v = shadow.verdict(results("variant", same) + results("hoofd", same))
        self.assertEqual(v["verdict"], "afvallen")

    def test_ruis_zonder_marge_wacht(self):
        import random
        rnd = random.Random(1)
        variant, hoofd = [rnd.choice([2.0, -1.0]) for _ in range(60)], [rnd.choice([2.0, -1.0]) for _ in range(60)]
        v = shadow.verdict(results("variant", variant) + results("hoofd", hoofd))
        self.assertLess(v["marge"][0], 0)
        self.assertGreater(v["marge"][1], 0)
        self.assertEqual(v["verdict"], "wachten")

    def test_open_en_vervallen_tellen_niet(self):
        rows = results("variant", alternating(60, 2.0)) + results("hoofd", alternating(60, 0.5))
        rows += [{"arm": "variant", "state": "verlopen", "r_net": None, "outcome_at": None}] * 10
        self.assertEqual(shadow.verdict(rows)["n_variant"], 60)


class StepTest(unittest.TestCase):
    ROW = {"direction": "long", "limit_price": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "state": "waiting",
           "created_at": "2026-10-31T00:00:00+00:00", "expires_at": "2026-11-03T00:00:00+00:00", "filled_at": None, "checked_until": None}

    def candles(self, rows):
        t0 = pd.Timestamp("2026-10-31T00:00:00Z")
        return pd.DataFrame([{"timestamp": t0 + pd.Timedelta(minutes=5 * i), "open": o, "high": h, "low": low, "close": c, "volume": 1.0}
                             for i, (o, h, low, c) in enumerate(rows)])

    def test_vulling_dan_doel(self):
        c = self.candles([(100.5, 100.6, 100.2, 100.4), (100.4, 100.4, 99.9, 100.1), (100.1, 102.1, 100.0, 102.0)])
        upd = shadow.step(self.ROW, c, NOW, cost_pct=0.06)
        self.assertEqual(upd["state"], "take_profit")
        self.assertAlmostEqual(upd["r_gross"], 2.0)
        self.assertAlmostEqual(upd["r_net"], 2.0 - 0.06)

    def test_stop_en_doel_in_een_candle_telt_als_stop(self):
        c = self.candles([(100.4, 100.4, 99.9, 100.1), (100.1, 102.5, 98.5, 101.0)])
        self.assertEqual(shadow.step(self.ROW, c, NOW, cost_pct=0.06)["state"], "stop_loss")

    def test_doel_voor_vulling_is_gemist(self):
        c = self.candles([(101.0, 102.2, 100.8, 102.0)])
        self.assertEqual(shadow.step(self.ROW, c, NOW, cost_pct=0.06)["state"], "gemist")

    def test_zonder_doel_wordt_niet_gevolgd(self):
        c = self.candles([(100.4, 100.4, 99.9, 100.1)])
        self.assertEqual(shadow.step({**self.ROW, "take_profit": None}, c, NOW, cost_pct=0.06)["state"], "zonder_doel")

    def test_vormende_candle_telt_niet(self):
        c = self.candles([(100.4, 100.4, 99.9, 100.1)])
        upd = shadow.step(self.ROW, c, pd.Timestamp("2026-10-31T00:03:00Z").to_pydatetime(), cost_pct=0.06)
        self.assertEqual(upd["state"], "waiting")

    def test_verloopt_zonder_vulling(self):
        upd = shadow.step(self.ROW, self.candles([(101.0, 101.2, 100.8, 101.0)]), datetime(2026, 11, 4, tzinfo=timezone.utc), cost_pct=0.06)
        self.assertEqual(upd["state"], "verlopen")


class RegistryTest(DbCase):
    def test_hoogstens_een_actieve_schaduw_per_soort(self):
        shadow.register("zr-stop-040", "zone_radar", "Stop 0,4 ATR", "lek: stops die later het doel haalden", {"stop_atr": 0.4}, NOW)
        with self.assertRaises(ValueError):
            shadow.register("zr-afstand-8", "zone_radar", "Afstand 8%", "reden", {"max_distance_pct": 8.0}, NOW)
        shadow.register("poc-stop-040", "poc_radar", "Stop 0,4 ATR", "reden", {"stop_atr": 0.4}, NOW)

    def test_onbekende_parameter_of_soort_weigert(self):
        with self.assertRaises(ValueError):
            shadow.register("x", "zone_radar", "x", "x", {"min_rr": 3.0}, NOW)
        with self.assertRaises(ValueError):
            shadow.register("y", "smc", "y", "y", {"stop_atr": 0.4}, NOW)
        with self.assertRaises(ValueError):
            shadow.register("z", "zone_radar", "z", "z", {"stop_atr": -1}, NOW)
        with self.assertRaises(ValueError):
            shadow.register("w", "zone_radar", "w", "", {"stop_atr": 0.4}, NOW)      # elke variant heeft een reden

    def test_standaardwaarden_zijn_de_constanten(self):
        self.assertEqual(shadow.live_params("zone_radar"), {"stop_atr": zr.STOP_ATR, "max_distance_pct": zr.MAX_DISTANCE_PCT})
        self.assertEqual(set(shadow.live_params("structuur")), {"stop_atr"})
        self.assertEqual(set(shadow.live_params("zone_sweep")), {"stop_buffer_atr"})
        self.assertEqual(set(shadow.live_params("poc_radar")), {"stop_atr"})


def zones():
    return [zr.ZoneLevel("1h", "bull", 95.0, 96.0, 1.0, "1h:bull:a"), zr.ZoneLevel("1h", "bear", 104.5, 105.5, 1.0, "1h:bear:b")]


class LiveTest(DbCase):
    def setUp(self):
        super().setUp()
        shadow.register("zr-stop-050", "zone_radar", "Stop 0,5 ATR", "reden vooraf", {"stop_atr": 0.5}, START)

    def scan(self, params=None):
        async def fake_zones(coin, now):
            return zones(), 98.0
        with mock.patch.object(zone_radar_live, "_zones", fake_zones):
            return asyncio.run(zone_radar_live._scan("BTC", pd.Timestamp(NOW), [], params=params))

    def test_motor_maakt_beide_armen_als_schaduw(self):
        plans = self.scan()
        self.assertEqual([p["stop_loss"] for p in plans], [95.0 - zr.STOP_ATR])
        rows = repo.list_shadow_results("zr-stop-050")
        self.assertEqual(sorted((r["arm"], r["stop_loss"]) for r in rows), [("hoofd", 95.0 - zr.STOP_ATR), ("variant", 94.5)])
        self.scan()                                             # volgende cyclus: dezelfde zone, geen dubbele rij
        self.assertEqual(len(repo.list_shadow_results("zr-stop-050")), 2)
        self.assertEqual(repo.list_zone_radar_setups(), [])

    def test_schaduw_maakt_geen_melding_en_geen_signaal(self):
        self.scan()
        t0 = pd.Timestamp(NOW)
        candles = pd.DataFrame([{"timestamp": t0 + pd.Timedelta(minutes=5 * i), "open": o, "high": h, "low": low, "close": c, "volume": 1.0}
                                for i, (o, h, low, c) in enumerate([(97.0, 97.0, 95.9, 96.2), (96.2, 96.3, 94.0, 94.2)])])
        boom = mock.AsyncMock(side_effect=AssertionError("geen melding vanuit de schaduw"))
        with mock.patch.object(push_notify, "send_push", boom), mock.patch.object(push_notify, "send_kans_push", boom):
            shadow_live.track(NOW + timedelta(hours=1), fetch=lambda coin, **k: candles)
        states = {r["arm"]: r["state"] for r in repo.list_shadow_results("zr-stop-050")}
        self.assertEqual(states, {"hoofd": "stop_loss", "variant": "stop_loss"})
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0], 0)
        boom.assert_not_called()

    def test_zonder_actieve_schaduw_niets(self):
        repo.set_shadow_status("zr-stop-050", "afgevallen", NOW.isoformat(), "test")
        self.scan()
        self.assertEqual(repo.list_shadow_results("zr-stop-050"), [])


class PromoteTest(DbCase):
    def setUp(self):
        super().setUp()
        shadow.register("zr-stop-040", "zone_radar", "Stop 0,4 ATR", "reden vooraf", {"stop_atr": 0.4}, START)
        for r in results("variant", alternating(63, 2.2)) + results("hoofd", alternating(63, 2.0)):
            put("zr-stop-040", r)
        self.pushes = []

        async def fake_push(user_id, title, body, url, **kw):
            self.pushes.append((user_id, title, body))
        patcher = mock.patch.object(push_notify, "send_push", fake_push)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_promoveren_zet_overlay_en_motor_leest_hem(self):
        schaduw.promote("zr-stop-040", NOW)
        self.assertEqual(shadow.live_params("zone_radar")["stop_atr"], 0.4)
        self.assertEqual(repo.get_shadow_variant("zr-stop-040")["status"], "gepromoveerd")
        self.assertEqual(len(self.pushes), 1)
        uid, title, body = self.pushes[0]
        self.assertEqual(uid, repo.list_ceo_user_ids()[0])
        self.assertIn("Zone-radar: stop 0,4 ATR in plaats van 0,25", body)
        self.assertIn("over 63 trades", body)
        self.assertIn("Terugdraaien: python3 scripts/schaduw.py --terug zr-stop-040", body)
        seen = {}

        async def spy(coin, stamp, waiting, params=None):
            seen["params"] = params
            return []
        with mock.patch.object(zone_radar_live, "_scan", spy), mock.patch.object(zone_radar_live, "_track", mock.AsyncMock()), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]):
            asyncio.run(zone_radar_live.run(NOW))
        self.assertEqual(seen["params"]["stop_atr"], 0.4)

    def test_terugdraaien(self):
        schaduw.promote("zr-stop-040", NOW)
        schaduw.revert("zr-stop-040", NOW)
        self.assertEqual(shadow.live_params("zone_radar")["stop_atr"], zr.STOP_ATR)
        self.assertEqual(repo.get_shadow_variant("zr-stop-040")["status"], "afgevallen")

    def test_auto_volgt_de_regel(self):
        shadow.register("poc-stop-040", "poc_radar", "Stop 0,4 ATR", "reden vooraf", {"stop_atr": 0.4}, START)
        for r in results("variant", alternating(50, 0.2)) + results("hoofd", alternating(50, 2.0)):
            put("poc-stop-040", r)
        done = schaduw.auto(NOW)
        self.assertEqual(done, {"zr-stop-040": "promoveren", "poc-stop-040": "afvallen"})
        self.assertEqual(repo.get_shadow_variant("poc-stop-040")["status"], "afgevallen")
        self.assertEqual(shadow.live_params("poc_radar")["stop_atr"], 0.25)


class ZoneRadarParamTest(unittest.TestCase):
    def test_standaard_onveranderd_en_injectie_werkt(self):
        base = zr.plan_for("long", zones(), 98.0)
        same = zr.plan_for("long", zones(), 98.0, stop_atr=zr.STOP_ATR, max_distance_pct=zr.MAX_DISTANCE_PCT)
        self.assertEqual(base, same)
        wider = zr.plan_for("long", zones(), 98.0, stop_atr=0.5)
        self.assertAlmostEqual(wider["stop_loss"], 94.5)
        self.assertIsNone(zr.plan_for("long", zones(), 98.0, max_distance_pct=1.0))


if __name__ == "__main__":
    unittest.main()
