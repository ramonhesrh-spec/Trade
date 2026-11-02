"""BTC-context op een modelkaart (app/btc_context.py): Pearson op log-rendementen van uitgelijnde 15m-candles, ontbrekende paren niet opgevuld,
'onvoldoende data' bij te weinig paren of nulvariantie, en de tekst zegt 'onbekend' als er niets gemeten is, nooit neutraal."""
import unittest

import numpy as np
import pandas as pd

from app import btc_context as bc
from tests.hespulse_model import synth as S
from tests.hespulse_model.test_model import base_rows

T0 = pd.Timestamp("2026-10-20T00:00:00Z")


def series(closes, start=T0):
    closes = np.asarray(closes, float)
    return pd.DataFrame({"timestamp": pd.date_range(start, periods=len(closes), freq="15min", tz="UTC"), "open": closes, "high": closes,
                         "low": closes, "close": closes})


def walk(n=700, seed=1):
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))


class CorrelationTest(unittest.TestCase):
    def setUp(self):
        self.now = T0 + 700 * bc.M15

    def test_same_series_is_plus_one(self):
        c = walk()
        m = bc.measure(series(c), series(c), None, self.now)
        self.assertAlmostEqual(m["corr_96"], 1.0)
        self.assertAlmostEqual(m["corr_672"], 1.0)
        self.assertAlmostEqual(m["rel_24h"], 0.0)

    def test_opposite_returns_are_minus_one(self):
        c = walk()
        opposite = c[0] ** 2 / c                     # elk log-rendement precies tegengesteld
        self.assertAlmostEqual(bc.measure(series(c), series(opposite), None, self.now)["corr_96"], -1.0)

    def test_constant_series_is_not_enough_data(self):
        m = bc.measure(series(walk()), series([100.0] * 700), None, self.now)
        self.assertIsNone(m["corr_96"])
        self.assertIsNone(m["corr_672"])

    def test_missing_candles_are_not_filled(self):
        c = walk()
        df = series(c)
        holes = df.drop(index=range(600, 640)).reset_index(drop=True)      # 40 kwartieren weg in de laatste 96
        m = bc.measure(holes, series(c), None, self.now)
        self.assertIsNone(m["corr_96"])                                      # minder dan 90% van de slots heeft een paar
        self.assertAlmostEqual(m["corr_672"], 1.0)                          # het 7-dagenvenster heeft er genoeg

    def test_no_data_says_unknown_never_neutral(self):
        m = bc.measure(None, None, None, self.now)
        self.assertEqual(m["btc_4h"], "onbekend")
        self.assertEqual(bc.text(m), "BTC-context onbekend")
        self.assertEqual(bc.text(None), "BTC-context onbekend")

    def test_text(self):
        t = bc.text({"btc_4h": "bearish", "corr_96": 0.82, "corr_672": 0.744, "rel_24h": None})
        self.assertEqual(t, "BTC 4u: bearish · correlatie 0,82 (24u) / 0,74 (7d)")


class BiasTest(unittest.TestCase):
    def test_btc_bias_uses_the_model_rule(self):
        fr = S.frames(base_rows())
        now = fr["15m"]["timestamp"].iloc[-1] + bc.M15
        self.assertEqual(bc.bias(fr["4h"], now), "bullish")
        mirrored = S.frames(S.mirror_rows(base_rows()))
        self.assertEqual(bc.bias(mirrored["4h"], now), "bearish")
        flat = S.frames(S.path([(400, 100.0)]))
        self.assertEqual(bc.bias(flat["4h"], now), "neutraal")
