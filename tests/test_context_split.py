"""H1-meting (app/context_split.py): mee/tegen/neutraal met de 4u-context van het model, zonder vooruitkijken."""
import unittest

import pandas as pd

from app import context_split as cs
from tests.hespulse_model import synth as S


def zigzag(up: bool, n_legs: int = 40) -> pd.DataFrame:
    legs, p = [], 100.0
    for i in range(n_legs):
        p = p + (6 if i % 2 == 0 else -3) * (1 if up else -1)
        legs.append((4, p))
    return S.frame(S.path(legs, wick=0.3), tf="4h")


def mirrored(df: pd.DataFrame, around: float = 200.0) -> pd.DataFrame:
    out = df.copy()
    out["open"], out["close"] = around - df["open"], around - df["close"]
    out["high"], out["low"] = around - df["low"], around - df["high"]
    return out


class ContextSplit(unittest.TestCase):
    def times(self, df):
        return [df["timestamp"].iloc[i] + pd.Timedelta(hours=4) for i in range(0, len(df), 3)]

    def test_stijgende_trap_geeft_long_mee_en_short_tegen(self):
        df = zigzag(True)
        b = cs.Bias(df)
        late = df["timestamp"].iloc[-1] + pd.Timedelta(hours=4)
        self.assertEqual(b.side(late), "long")
        self.assertEqual(b.group("long", late), cs.MEE)
        self.assertEqual(b.group("short", late), cs.TEGEN)

    def test_spiegelen_draait_de_kant_om(self):
        df = zigzag(True)
        a, m = cs.Bias(df), cs.Bias(mirrored(df))
        flip = {"long": "short", "short": "long", None: None, cs.ONBEKEND: cs.ONBEKEND}
        self.assertGreaterEqual(sum(a.side(t) == "long" for t in self.times(df)), 5)       # de toets is niet leeg
        for t in self.times(df):
            self.assertEqual(m.side(t), flip[a.side(t)], t)

    def test_latere_candles_veranderen_eerdere_groepen_niet(self):
        df = zigzag(True)
        full = cs.Bias(df)
        cut = len(df) * 2 // 3
        changed = df.copy()
        changed.loc[cut:, ["open", "high", "low", "close"]] = changed.loc[cut:, ["open", "high", "low", "close"]] * 0.5
        other = cs.Bias(changed)
        for t in self.times(df):
            if t <= df["timestamp"].iloc[cut]:
                self.assertEqual(full.side(t), other.side(t), t)

    def test_te_weinig_candles_is_onbekend_nooit_neutraal(self):
        df = zigzag(True)
        self.assertEqual(cs.Bias(None).group("long", df["timestamp"].iloc[-1]), cs.ONBEKEND)
        self.assertEqual(cs.Bias(df.iloc[:30]).group("long", df["timestamp"].iloc[-1]), cs.ONBEKEND)
        self.assertEqual(cs.Bias(df).group("long", df["timestamp"].iloc[5]), cs.ONBEKEND)


if __name__ == "__main__":
    unittest.main()
