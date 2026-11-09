"""Limiet, market of stop-order (B-2026-11-03-13): de drie instappen per plan, met dezelfde stop, hetzelfde doel en de uitkomstregel van het
model. Elke regel met een tegenvoorbeeld."""
import sys
import unittest
from pathlib import Path

import pandas as pd

from app import entry_compare as ec
from tests.hespulse_model import synth as S

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import instap_vergelijking as iv  # noqa: E402

T0 = pd.Timestamp("2026-10-10T00:00Z")


def b5(rows, start=T0):
    return S.frame(rows, "5min", start)


class MarketTest(unittest.TestCase):
    def test_open_van_de_eerste_candle(self):
        f = ec.market_fill("long", 99.0, 103.0, T0, b5([[100.2, 100.5, 100.0, 100.3]]))
        self.assertEqual((f["state"], f["entry"]), ("gevuld", 100.2))

    def test_tegenvoorbeeld_al_voorbij_het_doel(self):
        self.assertEqual(ec.market_fill("long", 99.0, 103.0, T0, b5([[103.5, 104, 103, 103.5]]))["state"], "voorbij")


class StopOrderTest(unittest.TestCase):
    def test_vult_pas_strikt_door_de_trigger(self):
        candles = b5([[100.0, 100.5, 99.8, 100.2], [100.2, 100.6, 100.1, 100.5]])
        f = ec.stop_fill("long", 100.5, 99.0, 103.0, T0, None, candles)
        self.assertEqual((f["state"], f["entry"], f["at"]), ("gevuld", 100.5, T0 + pd.Timedelta(minutes=5)))

    def test_gap_vult_op_de_open(self):
        f = ec.stop_fill("long", 100.5, 99.0, 103.0, T0, None, b5([[101.0, 101.2, 100.9, 101.1]]))
        self.assertEqual(f["entry"], 101.0)

    def test_tegenvoorbeeld_eerst_de_stop_dan_vervalt_de_order(self):
        f = ec.stop_fill("long", 100.5, 99.0, 103.0, T0, None, b5([[100.0, 100.2, 98.9, 99.2], [99.2, 101, 99, 100.8]]))
        self.assertEqual(f["state"], "stop_eerst")

    def test_short_gespiegeld_en_vervaltijd(self):
        candles = b5([[100.0, 100.2, 99.6, 99.8], [99.8, 99.9, 99.4, 99.5]])
        self.assertEqual(ec.stop_fill("short", 99.5, 101.0, 97.0, T0, None, candles)["state"], "gevuld")
        self.assertEqual(ec.stop_fill("short", 99.5, 101.0, 97.0, T0, T0 + pd.Timedelta(minutes=5), candles)["state"], "vervallen")


class PlanTest(unittest.TestCase):
    def test_drie_armen_zelfde_stop_en_doel(self):
        known = T0 + pd.Timedelta(minutes=15)
        b15 = S.frame([[100.0, 100.4, 99.9, 100.3]], "15min", T0)
        candles = b5([[100.3, 100.3, 100.3, 100.3]] * 3 + [[100.3, 100.5, 99.8, 100.0], [100.0, 100.2, 99.9, 100.1], [100.1, 103.2, 100.1, 103.0]])
        plan = {"known_at": known, "limit": 99.9, "stop": 99.0, "take": 103.0, "expires_at": known + pd.Timedelta(hours=6)}
        res = ec.compare_plan("long", plan, candles, b15)
        self.assertEqual({k: v["outcome"] for k, v in res.items()}, {"limiet": "take_profit", "market": "take_profit", "stop": "take_profit"})
        self.assertEqual((res["limiet"]["entry"], res["market"]["entry"], res["stop"]["entry"]), (99.9, 100.3, 100.4))
        self.assertGreater(res["limiet"]["r"], res["market"]["r"])           # dezelfde winst op een kleiner risico
        self.assertEqual(ec.compare_plan("long", {**plan, "take": None}, candles, b15), {})    # tegenvoorbeeld: zonder doel niets


class SummaryTest(unittest.TestCase):
    def test_per_plan_telt_niet_gevuld_als_nul(self):
        t = pd.Timestamp("2026-10-12T10:00Z")
        plan = {"stop": 99.0}
        win = {"state": "gevuld", "entry": 100.0, "outcome": "take_profit", "r": 2.0, "end": t}
        miss = {"state": "vervallen"}
        rows = [{"code": "B", "direction": "long", "known_at": t, "plan": plan, "arms": {"limiet": win, "market": miss, "stop": miss}},
                {"code": "B", "direction": "long", "known_at": t, "plan": plan, "arms": {"limiet": miss, "market": win, "stop": miss}}]
        s = {(x["code"], x["arm"]): x for x in iv.summarize(rows, 0.0)}
        self.assertEqual((s[("B", "limiet")]["filled"], s[("B", "limiet")]["per_plan"]), (1, 1.0))
        self.assertEqual(s[("B", "stop")]["per_plan"], 0.0)
        self.assertIsNotNone(s[("B", "market")]["diff"])
        self.assertIn("verschil met limiet", iv.report(list(s.values()), 1, 30, 2))


if __name__ == "__main__":
    unittest.main()


class EndToEndTest(unittest.TestCase):
    def test_het_script_vindt_het_plan_van_het_model(self):
        from tests.hespulse_model.test_model import TAIL_FROM, base_rows
        from tests.test_model_live import BACK, five_minutes, at
        fr = S.frames(base_rows(after=0) + BACK)
        fr["5m"] = five_minutes(fr["15m"])
        fetch = lambda coin, tf, since, until: fr[tf] if tf in fr else None
        now = at(TAIL_FROM + 30)
        rows = iv.plans_of("BTC", now, 60, fetch=fetch)
        self.assertTrue(any(r["code"] == "A" for r in rows))
        a = next(r for r in rows if r["code"] == "A")
        self.assertEqual(set(a["arms"]), set(ec.ARMS))
        self.assertEqual(a["arms"]["limiet"]["state"], "gevuld")             # de vulling die het live-model ook ziet
