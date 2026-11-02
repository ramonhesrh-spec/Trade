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
        self.assertEqual(sl.levels(rows(n=20), "1h", T0 + 3600 * 21), {"lines": [], "zones": [], "trend": None})
        self.assertEqual(sl.levels(rows(), "1w", T0 + 3600 * 601), {"lines": [], "zones": [], "trend": None})


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
            with mock.patch.object(main, "_cached_candles", mock.AsyncMock(return_value=None)):
                self.assertEqual({x["trend"] for x in t.client.get("/api/trend/BTC").json()["trend"]}, {"onbekend"})
        finally:
            t.doCleanups()
