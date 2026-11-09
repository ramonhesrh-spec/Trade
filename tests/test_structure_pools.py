"""Liquiditeit voor "Groot" (structure_levels.pools en pool_lines): de dichtstbijzijnde onaangeroerde BSL en SSL van 1u en 4u. Een Python-versie
in precies de stappen van f_pools uit tradingview/hespulse_clean.pine (lijsten, lussen, geen numpy) moet op willekeurige candles hetzelfde geven."""
import unittest
from unittest import mock

from app import structure_levels as sl
from tests.hespulse_model.test_model import random_rows

T0 = 1_760_000_000
EQUAL_ATR = 0.1


def rows(seed=5, n=600, tf_s=3600):
    return [[T0 + tf_s * i, *r] for i, r in enumerate(random_rows(seed, n))]


def flat(n, spikes=None, tf_s=3600):
    """Een vlakke reeks (high 101, low 99) met pieken: {index: ("h", 110) of ("l", 90)}."""
    out = []
    for i in range(n):
        o, h, l, c = 100.0, 101.0, 99.0, 100.0
        kind, v = (spikes or {}).get(i, (None, None))
        if kind == "h":
            h = v
        if kind == "l":
            l = v
        out.append([T0 + tf_s * i, o, h, l, c])
    return out


def pine_pools(r, k, atr):
    """De stappen van f_pools op alle gesloten candles; geeft de toestand na de laatste candle."""
    H, L = [x[2] for x in r], [x[3] for x in r]
    hs, ls = [], []
    for b in range(len(r)):
        hs = [p for p in hs if not (H[b] >= p[0] or b - p[1] >= sl.POOL_AGE)]
        ls = [p for p in ls if not (L[b] <= p[0] or b - p[1] >= sl.POOL_AGE)]
        if b - 2 * k >= 0:
            okh = okl = True
            for j in range(1, k + 1):
                if not H[b - k - j] < H[b - k]:
                    okh = False
                if not H[b - k + j] <= H[b - k]:
                    okh = False
                if not L[b - k - j] > L[b - k]:
                    okl = False
                if not L[b - k + j] >= L[b - k]:
                    okl = False
            if okh:
                hs.append((H[b - k], b - k))
            if okl:
                ls.append((L[b - k], b - k))
    out = {}
    for name, items, nearest in (("bsl", hs, min), ("ssl", ls, max)):
        if not items:
            out[name] = None
            continue
        best = nearest(items, key=lambda p: p[0])
        eq = any(p is not best and abs(p[0] - best[0]) <= EQUAL_ATR * atr for p in items)
        out[name] = (best[0], r[best[1]][0], eq)
    return out


class Pools(unittest.TestCase):
    def test_zelfde_als_f_pools_op_willekeurige_candles(self):
        seen = 0
        for tf, sec in (("1h", 3600), ("4h", 14400)):
            for seed in range(60):
                r = rows(seed=seed, n=500, tf_s=sec)
                now = T0 + sec * 500 + 1
                got = sl.pools(r, tf, now)
                want = pine_pools(r, sl.POOL_TFS[tf], got["atr"])
                with self.subTest(tf=tf, seed=seed):
                    for side in ("bsl", "ssl"):
                        if want[side] is None:
                            self.assertIsNone(got[side])
                        else:
                            self.assertEqual((got[side]["value"], got[side]["time"], got[side]["eq"]), want[side])
                            seen += 1
        self.assertGreater(seen, 100)

    def test_een_aanraking_verbruikt_de_pool_en_na_120_candles_vervalt_hij(self):
        r = flat(40, {10: ("h", 110.0), 20: ("l", 90.0)})
        p = sl.pools(r, "1h", T0 + 3600 * 40 + 1)
        self.assertEqual((p["bsl"]["value"], p["bsl"]["time"]), (110.0, T0 + 3600 * 10))
        self.assertEqual((p["ssl"]["value"], p["ssl"]["time"]), (90.0, T0 + 3600 * 20))
        touched = flat(41, {10: ("h", 110.0), 20: ("l", 90.0), 40: ("h", 111.0)})
        self.assertIsNone(sl.pools(touched, "1h", T0 + 3600 * 41 + 1)["bsl"])
        self.assertIsNotNone(sl.pools(flat(130, {10: ("h", 110.0)}), "1h", T0 + 3600 * 130 + 1)["bsl"])
        self.assertIsNone(sl.pools(flat(131, {10: ("h", 110.0)}), "1h", T0 + 3600 * 131 + 1)["bsl"])

    def test_de_pivot_zelf_en_de_candles_rechts_ervan_tellen_niet_als_aanraking(self):
        # Twee gelijke toppen rechts van een pivot (gelijk mag): de pool blijft staan.
        r = flat(30, {10: ("h", 110.0), 12: ("h", 110.0)})
        self.assertEqual(sl.pools(r, "1h", T0 + 3600 * 30 + 1)["bsl"]["value"], 110.0)

    def test_een_tweede_pivot_binnen_een_tiende_atr_maakt_een_eqh(self):
        # De tweede top ligt vlak onder de eerste (raakt hem niet) en binnen 0,1 ATR: samen een EQH, de laagste telt als dichtstbijzijnde BSL.
        r = flat(40, {10: ("h", 110.0), 20: ("h", 109.9)})
        p = sl.pools(r, "1h", T0 + 3600 * 40 + 1)
        self.assertEqual(p["bsl"]["value"], 109.9)
        self.assertTrue(p["bsl"]["eq"])
        far = flat(40, {10: ("h", 110.0), 20: ("h", 108.0)})
        self.assertFalse(sl.pools(far, "1h", T0 + 3600 * 40 + 1)["bsl"]["eq"])

    def test_geen_pools_voor_een_ander_tijdframe_of_te_weinig_candles(self):
        self.assertEqual(sl.pools(rows(), "15m", T0 + 3600 * 601)["bsl"], None)
        self.assertEqual(sl.pools(rows(n=20), "1h", T0 + 3600 * 21)["ssl"], None)
        self.assertEqual(sl.pools(None, "1h", T0)["bsl"], None)


class Lines(unittest.TestCase):
    def test_welke_tijdframes_op_welke_grafiek(self):
        by = {"4h": rows(seed=3, n=500, tf_s=14400), "1h": rows(seed=4, n=500, tf_s=3600)}
        now = T0 + 14400 * 501
        names = lambda tf: {l["label"][:2] for l in sl.pool_lines(by, tf, now)}
        self.assertEqual(names("4h"), {"4u"})
        self.assertEqual(names("1d"), set())
        self.assertTrue(names("1h") <= {"4u", "1u"} and "4u" in names("1h"))
        self.assertTrue(all(l["kind"] == "pool" and l["side"] in ("bsl", "ssl") for l in sl.pool_lines(by, "1h", now)))

    def test_een_niveau_van_1u_op_dat_van_4u_blijft_weg(self):
        same = flat(60, {10: ("h", 110.0), 20: ("l", 90.0)}, tf_s=3600)
        four = flat(60, {10: ("h", 110.0), 20: ("l", 90.0)}, tf_s=14400)
        lines = sl.pool_lines({"1h": same, "4h": four}, "1h", T0 + 14400 * 61)
        self.assertEqual({l["label"] for l in lines}, {"4u BSL", "4u SSL"})
        other = flat(60, {10: ("h", 120.0), 20: ("l", 80.0)}, tf_s=3600)
        lines = sl.pool_lines({"1h": other, "4h": four}, "1h", T0 + 14400 * 61)
        self.assertEqual({l["label"] for l in lines}, {"4u BSL", "4u SSL", "1u BSL", "1u SSL"})


class Route(unittest.TestCase):
    def test_de_route_geeft_de_pools_mee_zonder_levels_te_veranderen(self):
        from tests.test_web_focus import Base
        from web import main

        class R(Base):
            def runTest(self):
                pass
        t = R()
        t.setUp()
        try:
            with mock.patch.object(main, "_cached_candles", mock.AsyncMock(return_value=rows(seed=3, n=500))), \
                    mock.patch.object(main.time, "time", return_value=T0 + 3600 * 501):
                out = t.client.get("/api/structuur/BTC?tf=1h").json()
                self.assertIn("pools", out)
                self.assertTrue(all({"value", "time", "label", "side"} <= set(p) for p in out["pools"]))
                self.assertEqual(t.client.get("/api/structuur/BTC?tf=1d").json()["pools"], [])
                for k in ("lines", "zones", "trend", "herstel"):
                    self.assertIn(k, out)
        finally:
            t.doCleanups()


if __name__ == "__main__":
    unittest.main()
