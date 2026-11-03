"""De vier metingen tijdens de bevriezing (preregistratie, aanvulling 2026-11-03 avond; B-2026-11-03-12): strenge vulling, MAE/MFE en
stopslip, placebo en de auto-misser voor het model. Alleen meting; elke regel met een tegenvoorbeeld."""
import unittest
from datetime import datetime, timezone

import pandas as pd

from app import auto_misser as am, db, model, model_live, model_measure, model_placebo as mp, repo
from tests.hespulse_model import synth as S
from tests.test_model_live import Case, at
from tests.hespulse_model.test_model import TAIL_FROM

T0 = pd.Timestamp("2026-10-10T00:00Z")


def b5(rows, start=T0):
    return S.frame(rows, "5min", start)


class StrictFillTest(unittest.TestCase):
    def test_aanraken_vult_gewoon_maar_niet_streng(self):
        candles = b5([[100.5, 100.6, 100.0, 100.4], [100.4, 100.5, 100.2, 100.3]])
        self.assertEqual(model.walk_fill("long", 100.0, 103.0, T0, T0 + pd.Timedelta(hours=6), candles)["state"], "gevuld")
        self.assertIsNone(model.walk_fill("long", 100.0, 103.0, T0, T0 + pd.Timedelta(hours=6), candles, strict=True)["state"])

    def test_tegenvoorbeeld_door_de_limiet_vult_ook_streng(self):
        candles = b5([[100.5, 100.6, 100.0, 100.4], [100.4, 100.5, 99.9, 100.3]])
        res = model.walk_fill("long", 100.0, 103.0, T0, T0 + pd.Timedelta(hours=6), candles, strict=True)
        self.assertEqual((res["state"], res["at"]), ("gevuld", T0 + pd.Timedelta(minutes=5)))

    def test_short_gespiegeld(self):
        candles = b5([[99.5, 100.0, 99.4, 99.6]])
        self.assertIsNone(model.walk_fill("short", 100.0, 97.0, T0, None, candles, strict=True)["state"])
        candles = b5([[99.5, 100.1, 99.4, 99.6]])
        self.assertEqual(model.walk_fill("short", 100.0, 97.0, T0, None, candles, strict=True)["state"], "gevuld")


class SlipTest(unittest.TestCase):
    def test_gap_over_de_stop_is_slip_in_r(self):
        self.assertAlmostEqual(model.slip_r("long", 100.0, 98.0, "stop_loss", 97.0), 0.5)
        self.assertAlmostEqual(model.slip_r("short", 100.0, 102.0, "stop_loss", 103.0), 0.5)

    def test_tegenvoorbeelden_geen_gap_of_geen_stop(self):
        self.assertEqual(model.slip_r("long", 100.0, 98.0, "stop_loss", 99.0), 0.0)
        self.assertIsNone(model.slip_r("long", 100.0, 98.0, "take_profit", 97.0))

    def test_outcome_geeft_de_open_van_de_uitgangscandle(self):
        out = model.outcome("long", 100.0, 98.0, 106.0, T0, b5([[100, 100.5, 99.5, 100], [97.0, 97.5, 96.5, 97.0]]))
        self.assertEqual((out["state"], out["exit_open"]), ("stop_loss", 97.0))


class PlaceboTest(unittest.TestCase):
    def test_vaste_willekeurige_momenten_in_de_week_ervoor(self):
        start = pd.Timestamp("2026-10-20T12:00Z")
        a, b = mp.sample_times("E:7", start), mp.sample_times("E:7", start)
        self.assertEqual(a, b)
        self.assertEqual(len(set(a)), mp.N)
        self.assertTrue(all(start - mp.WINDOW <= t <= start - mp.GAP and t.minute % 5 == 0 for t in a))
        self.assertNotEqual(a, mp.sample_times("E:8", start))          # tegenvoorbeeld: ander id, andere momenten

    def test_dezelfde_geometrie_vanaf_de_open(self):
        start = pd.Timestamp("2026-10-08T00:00Z")
        n = int(mp.WINDOW / mp.STEP) + 20
        rows = [[100 + k * 0.01, 100 + k * 0.01 + 0.005, 100 + k * 0.01 - 0.005, 100 + k * 0.01] for k in range(n)]
        candles = b5(rows, start - mp.WINDOW - mp.STEP)
        rs = mp.placebo_rs("A:1", "long", 100.0, 99.0, 100.5, start, candles)          # stop 1%, doel 0,5%: stijgende markt haalt het doel
        self.assertEqual(len(rs), mp.N)
        self.assertTrue(all(abs(r - 0.5) < 1e-9 for r in rs))
        self.assertEqual(mp.placebo_rs("A:1", "short", 100.0, 101.0, 99.5, start, candles), [-1.0] * mp.N)    # tegenvoorbeeld: short verliest

    def test_meting_verschil_per_trade(self):
        pairs = [{"net": 1.0, "end": datetime(2026, 11, 5, tzinfo=timezone.utc), "cost_r": 0.1, "rs": [0.1, 0.1]},
                 {"net": -1.1, "end": datetime(2026, 11, 12, tzinfo=timezone.utc), "cost_r": 0.1, "rs": [-0.9]},
                 {"net": 0.5, "end": datetime(2026, 11, 12, tzinfo=timezone.utc), "cost_r": 0.1, "rs": None}]
        p = model_measure.placebo(pairs)
        self.assertEqual((p["n"], p["missing"]), (2, 1))
        self.assertAlmostEqual(p["diff"], ((1.0 - 0.0) + (-1.1 + 1.0)) / 2)


class StrictCompareTest(unittest.TestCase):
    def row(self, **kw):
        base = {"code": "B", "counter": 0, "limit_price": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "n_filled_at": "x", "n_outcome": "take_profit",
                "filled_at": None, "outcome": None, "known": None, "detected": None}
        return {**base, **kw}

    def test_zelfde_plannen_naast_elkaar(self):
        rows = [self.row(), self.row(filled_at="y", outcome="stop_loss"), self.row(code="B", counter=1)]
        (b,) = model_measure.strict_compare(rows, 0.0)["main"]
        self.assertEqual((b["plans"], b["fill_n"], b["fill_s"], b["done_n"], b["done_s"]), (2, 2, 1, 2, 1))
        self.assertAlmostEqual(b["mean_n"], 2.0)
        self.assertAlmostEqual(b["mean_s"], -1.0)
        self.assertEqual(len(model_measure.strict_compare(rows, 0.0)["tegen"]), 1)          # tegen de dag apart


class ModelMisserTest(unittest.TestCase):
    begin = pd.Timestamp("2026-11-01T10:00Z")

    def sc(self, direction="short", status="wacht_shift", entry=None, hours=0):
        return {"direction": direction, "status": status, "entry": entry, "discovered_at": self.begin + pd.Timedelta(hours=hours)}

    def test_redenen(self):
        self.assertIn("plan", am.model_reason("short", "short", [self.sc(entry={"limit": 1})], [], self.begin))
        self.assertIn("wachtte op de breuk", am.model_reason("short", "short", [self.sc()], [], self.begin))
        self.assertIn("de dag wees long", am.model_reason("short", "long", [], [self.sc()], self.begin))
        self.assertIn("geen dagbreuk", am.model_reason("short", None, [], [], self.begin))
        self.assertIn("geen 4u-range", am.model_reason("short", "short", [], [], self.begin))

    def test_tegenvoorbeeld_scenario_te_ver_weg_of_andere_richting_telt_niet(self):
        far = [self.sc(hours=13), self.sc(direction="long")]
        self.assertIn("geen 4u-range", am.model_reason("short", "short", far, [], self.begin))


class SeedAndSeenTest(Case):
    def test_alleen_plannen_na_het_startmoment_krijgen_een_strenge_arm(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 4))
        row = self.scenario()
        self.assertEqual(repo.seed_model_strict(pd.Timestamp(row["entry_detected_at"]).isoformat()), 1)
        self.assertEqual(repo.seed_model_strict(pd.Timestamp(row["entry_detected_at"]).isoformat()), 0)        # één keer
        (t,) = repo.list_model_strict()
        self.assertEqual((t["kind"], t["code"], t["limit_price"], t["start_at"]), ("A", "A", row["limit_price"], row["entry_detected_at"]))
        with db.session() as conn:
            conn.execute("DELETE FROM model_strict")
        later = (pd.Timestamp(row["entry_detected_at"]) + pd.Timedelta(minutes=1)).isoformat()
        self.assertEqual(repo.seed_model_strict(later), 0)                       # tegenvoorbeeld: ouder plan niet

    def test_strenge_arm_volgt_en_komt_naast_de_gewone(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 4))
        row = self.scenario()
        with db.session() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (repo.MODEL_STRICT_KEY, row["entry_detected_at"]))
        self.cycle(at(TAIL_FROM + 12))
        (t,) = repo.list_model_strict_compare()
        self.assertEqual(self.scenario()["entry_state"], "gevuld")
        self.assertIsNotNone(t["n_filled_at"])
        self.assertEqual(t["state"], "gevuld")             # de koers ging strikt door de limiet

    def test_model_scenario_telt_als_gezien(self):
        self.cycle(at(TAIL_FROM - 5))
        row = self.scenario()
        t = pd.Timestamp(row["detected_at"])
        rows = repo.auto_misser_seen_rows("BTC", (t - pd.Timedelta(hours=1)).isoformat(), (t + pd.Timedelta(hours=1)).isoformat())
        self.assertIn({"source": "hespulse_model", "direction": row["direction"], "at": row["detected_at"]}, rows)
        self.assertEqual(repo.auto_misser_seen_rows("BTC", (t + pd.Timedelta(hours=1)).isoformat(), (t + pd.Timedelta(hours=2)).isoformat()), [])


class EntryExcursionTest(Case):
    def test_instappunt_krijgt_mae_mfe_en_slip(self):
        self.cycle(at(TAIL_FROM - 5))
        sid = self.scenario()["id"]
        sc = {"direction": "long", "b": {"known_at": T0, "limit": 100.0, "stop": 99.0, "take": 103.0, "rr": 3.0, "expires_at": T0 + pd.Timedelta(hours=6),
                                         "extreme": 99.5}, "b0": None, "p": None}
        model_live.store_entries(sid, "BTC", sc, T0)
        (e,) = repo.list_model_entries()
        candles = b5([[100.5, 100.6, 100.4, 100.5], [100.5, 100.5, 99.9, 100.1], [100.1, 101.5, 99.6, 101.0], [98.5, 98.8, 98.4, 98.6]])
        model_live.track_entry(e, candles, [], T0 + pd.Timedelta(minutes=25))
        (e,) = repo.list_model_entries()
        self.assertEqual(e["outcome"], "stop_loss")
        self.assertAlmostEqual(e["mae_r"], 1.0)
        self.assertAlmostEqual(e["mfe_r"], 1.5)
        self.assertAlmostEqual(e["slip_r"], 0.5)
        (x,) = model_measure.excursions([], [e], {})
        self.assertEqual((x["code"], x["loss_1r"], x["slip_mean"]), ("B", 1.0, 0.5))


if __name__ == "__main__":
    unittest.main()
