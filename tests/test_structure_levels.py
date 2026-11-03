"""Structuur per tijdframe voor "Groot" (app/structure_levels.py): alleen gesloten candles, de naam draagt het tijdframe, premium boven en
discount onder het evenwicht, en de route /api/structuur."""
import unittest
from unittest import mock

from app import structure_levels as sl
from tests.hespulse_model.test_model import random_rows

T0 = 1_760_000_000


def rows(seed=5, n=600, tf_s=3600):
    return [[T0 + tf_s * i, *r] for i, r in enumerate(random_rows(seed, n))]


class Levels(unittest.TestCase):
    def test_namen_dragen_het_tijdframe_en_premium_ligt_boven_discount(self):
        for tf, sec in (("1h", 3600), ("4h", 14400), ("15m", 900), ("1d", 86400)):
            out = sl.levels(rows(tf_s=sec), tf, T0 + sec * 600 + 1)
            word = sl.TF_TEXT[tf]
            labels = [l["label"] for l in out["lines"]] + [z["label"] for z in out["zones"]]
            self.assertIn(f"{word} range high", labels, tf)
            self.assertIn(f"{word} evenwicht 0,5", labels, tf)
            z = {x["kind"]: x for x in out["zones"]}
            self.assertAlmostEqual(z["premium"]["low"], z["discount"]["high"])
            self.assertGreater(z["premium"]["high"], z["discount"]["low"])
            for x in out["lines"] + out["zones"]:
                if x["kind"] not in ("premium", "discount"):
                    self.assertTrue(x["label"].startswith(word) or x["label"] in ("premium", "discount"), x["label"])

    def test_een_candle_die_nog_loopt_telt_niet(self):
        r = rows()
        done = sl.levels(r, "1h", T0 + 3600 * 600 + 1)
        forming = r + [[T0 + 3600 * 600, r[-1][4], r[-1][4] * 1.5, r[-1][4] * 0.5, r[-1][4] * 1.4]]
        self.assertEqual(sl.levels(forming, "1h", T0 + 3600 * 600 + 60), done)

    def test_te_weinig_candles_of_onbekend_tijdframe_is_leeg(self):
        self.assertEqual(sl.levels(rows(n=20), "1h", T0 + 3600 * 21), {"lines": [], "zones": [], "trend": None, "herstel": False})
        self.assertEqual(sl.levels(rows(), "1w", T0 + 3600 * 601), {"lines": [], "zones": [], "trend": None, "herstel": False})


class TopDownLikeTheModel(unittest.TestCase):
    """B-2026-11-03-09: met de richting van de dag tekent Groot dezelfde 4u-range als het model (model.Context4h topdown), ook opgerekt na
    een slot door de rand. Zonder richting de oude regel (elke breuk)."""

    def model_range(self, r, bias, now_s):
        import pandas as pd
        from app import model
        df = pd.DataFrame([x[:5] for x in r], columns=["t", "open", "high", "low", "close"])
        df.insert(0, "timestamp", pd.to_datetime(df.pop("t"), unit="s", utc=True))
        df = model.closed(df, pd.Timestamp(now_s, unit="s", tz="UTC"), "4h")
        fr = model._frame(df, "4h", bias == "short")
        ctx = model.Context4h(fr, bias, topdown=True).at(int(fr.ct[-1]))
        if ctx is None:
            return None
        return (-ctx.H, -ctx.L) if bias == "short" else (ctx.L, ctx.H)

    def test_zelfde_range_als_het_model_in_beide_richtingen(self):
        checked = 0
        for seed in (1, 3, 5, 7, 9, 11):
            for n in (300, 420, 560):
                r = rows(seed=seed, n=n, tf_s=14400)
                now_s = T0 + 14400 * n + 1
                for bias in ("long", "short"):
                    want = self.model_range(r, bias, now_s)
                    if want is None:
                        continue
                    got = {l["short"]: l["value"] for l in sl.levels(r, "4h", now_s, bias=bias)["lines"] if l["kind"] == "range"}
                    self.assertAlmostEqual(got["RL"], want[0], msg=(seed, n, bias))
                    self.assertAlmostEqual(got["RH"], want[1], msg=(seed, n, bias))
                    checked += 1
        self.assertGreater(checked, 5)

    def test_herstel_alleen_als_de_laatste_breuk_tegen_de_dag_ingaat(self):
        r = rows(seed=3, n=420, tf_s=14400)
        now_s = T0 + 14400 * 420 + 1
        last = sl.levels(r, "4h", now_s)["trend"]
        same = "long" if last == "bullish" else "short"
        other = "short" if same == "long" else "long"
        self.assertFalse(sl.levels(r, "4h", now_s, bias=same)["herstel"])
        self.assertTrue(sl.levels(r, "4h", now_s, bias=other)["herstel"])
        self.assertFalse(sl.levels(r, "4h", now_s)["herstel"])          # zonder dag: geen oordeel


class Route(unittest.TestCase):
    def test_route(self):
        from tests.test_web_focus import Base
        from web import main

        class R(Base):
            def runTest(self):
                pass
        t = R()
        t.setUp()
        try:
            with mock.patch.object(main, "_cached_candles", mock.AsyncMock(return_value=rows())), \
                    mock.patch.object(main.time, "time", return_value=T0 + 3600 * 601):
                ok = t.client.get("/api/structuur/BTC?tf=1h")
                self.assertEqual(ok.status_code, 200)
                self.assertTrue(ok.json()["lines"])
                self.assertEqual(t.client.get("/api/structuur/BTC?tf=1w").status_code, 422)
                self.assertEqual(t.client.get("/api/structuur/NIETBESTAAND?tf=1h").status_code, 404)
                tr = t.client.get("/api/trend/BTC").json()["trend"]
                self.assertEqual([x["word"] for x in tr], ["D", "4u", "1u", "15m"])
                self.assertTrue(all(x["trend"] in ("bullish", "bearish", None) for x in tr))
                self.assertFalse(tr[0]["herstel"])                  # de dag zelf is nooit een herstel
                self.assertTrue(all(isinstance(x["herstel"], bool) for x in tr))
            with mock.patch.object(main, "_cached_candles", mock.AsyncMock(return_value=None)):
                self.assertEqual({x["trend"] for x in t.client.get("/api/trend/BTC").json()["trend"]}, {"onbekend"})
        finally:
            t.doCleanups()
