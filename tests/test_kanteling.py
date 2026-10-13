import unittest

import numpy as np
import pandas as pd

from app.replay import trendlab as tl


def frame(rows, minutes=5):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["timestamp"] = pd.date_range("2025-01-01", periods=len(df), freq=f"{minutes}min", tz="UTC")
    df["volume"] = 1.0
    df["atr"] = 1.0
    return df


def flat(k, c=110.0):
    return [(c, c + 0.5, c - 0.5, c)] * k


# Index: 0-29 vlak op 110, 30-32 scherpe daling (L0 = 32, low 100), 36 = H1 (high 108), 40 = L1 (low 103, bekend op 43),
# 44 = enkele doorbraak (slot 108,2), 47 = H2 (high 112), 52 = L2 (low 105, bekend op 55), 56 = dubbele doorbraak (slot 112,5).
HEAD = flat(30) + [
    (110, 110, 106, 106), (106, 106, 102, 102), (102, 102, 100, 101),                        # 30-32
    (101, 103, 100.5, 102.5), (102.5, 104, 101.5, 103.5), (103.5, 105, 102.5, 104.5),        # 33-35
    (104.5, 108, 104, 107), (107, 107.5, 105, 106), (106, 106.5, 104.5, 105), (105, 105.5, 103.5, 104),   # 36-39
    (104, 104.5, 103, 104), (104, 106, 103.5, 105.5), (105.5, 106.5, 104, 106), (106, 107, 104.5, 106.5),  # 40-43
]
BREAK1 = [(106.5, 108.5, 106, 108.2)]                                                        # 44
MID = [
    (108.2, 110, 107.5, 109.5), (109.5, 111, 108.5, 110.5), (110.5, 112, 109.5, 111.5),      # 45-47
    (111.5, 111.5, 109, 110), (110, 111, 108.5, 109), (109, 110, 107, 108),                  # 48-50
    (108, 109, 106, 107), (107, 108, 105, 107.5), (107.5, 109, 106, 108.5),                  # 51-53
    (108.5, 110, 106.5, 109.5), (109.5, 111, 107, 110.5),                                    # 54-55
]
BREAK2 = [(110.5, 113, 110, 112.5)]                                                          # 56
TAIL = [(112.5 + k, 113.5 + k, 112 + k, 113.5 + k) for k in range(0, 30)]                    # stijgt elke candle, geen pivots


def long_rows():
    return HEAD + BREAK1 + MID + BREAK2 + TAIL


def mirror(rows, pivot=220.0):
    return [(pivot - o, pivot - lo, pivot - h, pivot - c) for o, h, lo, c in rows]


def sigs(rows, confirmations, max_bars=None):
    mb = max_bars or (48 if confirmations == 1 else 96)
    return tl.kanteling_signals(frame(rows), confirmations, 3, 3.0, 24, mb)


class SignalTest(unittest.TestCase):
    def test_enkel_fires_on_first_break_and_dubbel_only_on_the_second(self):
        e, d = sigs(long_rows(), 1), sigs(long_rows(), 2)
        self.assertEqual([(i, s) for i, s, _ in e], [(44, 1)])
        self.assertEqual([(i, s) for i, s, _ in d], [(56, 1)])

    def test_stop_level_is_below_l1_or_l2_minus_a_quarter_atr(self):
        self.assertAlmostEqual(sigs(long_rows(), 1)[0][2], 103 - 0.25)
        self.assertAlmostEqual(sigs(long_rows(), 2)[0][2], 105 - 0.25)

    def test_pivot_is_never_used_before_it_is_known(self):
        rows = long_rows()
        rows[42] = (105.5, 108.8, 104, 108.5)      # sluit boven H1 terwijl L1 (40) pas op 43 bekend is
        rows[43] = (108.5, 108.6, 104.5, 107)
        self.assertEqual([i for i, _, _ in sigs(rows, 1)], [44])    # een implementatie met vooruitkijken zou 42 geven

    def test_undercutting_l1_resets_enkel_and_dubbel(self):
        rows = long_rows()
        control = HEAD + [(106.5, 107.5, 106, 107), (107, 109.5, 105.5, 109)]
        self.assertEqual([i for i, _, _ in sigs(control, 1)], [45])
        dip = HEAD + [(106.5, 107.5, 106, 107), (107, 107.5, 102.5, 106), (106, 109.5, 105.5, 109)]
        self.assertEqual(sigs(dip, 1), [])
        rows[49] = (109, 110, 102.5, 108.5)         # na de eerste doorbraak onder L1: geen dubbel
        self.assertEqual(sigs(rows, 2), [])

    def test_undercutting_l0_drops_the_old_sequence(self):
        rows = long_rows()
        rows[39] = (105, 105.5, 99, 104)            # onder L0 voor L1 bekend is
        self.assertNotIn(44, [i for i, _, _ in sigs(rows, 1)])

    def test_enkel_limit_is_48_candles_since_l0(self):
        def case(break_index):
            rows = HEAD + flat(break_index - 44, 105.0)
            rows += [(105, 109.5, 104.5, 109)] + [(109 + k, 110 + k, 108.5 + k, 109.5 + k) for k in range(5)]
            return [i for i, _, _ in sigs(rows, 1)]
        self.assertEqual(case(32 + 48), [80])
        self.assertEqual(case(32 + 49), [])

    def test_dubbel_limit_is_96_candles_since_l0(self):
        def case(break_index):
            rows = HEAD + BREAK1 + MID + [(109, 109.5, 108.5, 109)] * (break_index - 56) + [(109, 113, 108.5, 112.5)] + TAIL[:5]
            return [i for i, _, _ in sigs(rows, 2)]
        self.assertEqual(case(32 + 96), [128])
        self.assertEqual(case(32 + 97), [])

    def test_dubbel_is_a_subset_of_enkel_first_break_limit_is_48(self):
        # eerste doorbraak op L0+60: enkel weigert hem, dus dubbel mag er ook niet aan beginnen
        late = HEAD + flat(48, 105.0) + BREAK1 + MID + BREAK2 + TAIL[:5]
        self.assertEqual(sigs(late, 1), [])
        self.assertEqual(sigs(late, 2), [])

    def test_dubbel_second_break_may_come_after_48_but_before_96(self):
        rows = HEAD + BREAK1 + MID + [(109, 109.5, 108.5, 109)] * (102 - 56) + [(109, 113, 108.5, 112.5)] + TAIL[:5]
        self.assertEqual([i for i, _, _ in sigs(rows, 2)], [102])        # eerste doorbraak op L0+12, tweede op L0+70

    def test_short_is_the_exact_mirror(self):
        for conf, idx, raw in ((1, 44, 103 - 0.25), (2, 56, 105 - 0.25)):
            long_sig = sigs(long_rows(), conf)
            short_sig = sigs(mirror(long_rows()), conf)
            self.assertEqual([(i, s) for i, s, _ in short_sig], [(idx, -1)])
            self.assertAlmostEqual(short_sig[0][2], 220 - raw)
            self.assertEqual([s for _, s, _ in long_sig], [1])


class TradeTest(unittest.TestCase):
    def test_entry_is_next_open_stop_is_the_raw_level_and_target_is_two_r(self):
        b = frame(long_rows())
        i, sign, raw = sigs(long_rows(), 2)[0]
        v = next(x for x in tl.VARIANTS if x.name == "KANT_2_5M")
        t = tl._trade(v, b, i, sign, 0.0, raw)
        entry = b["open"].iloc[i + 1]
        self.assertEqual(entry, 112.5)
        self.assertAlmostEqual(t["risk_pct"], (entry - 104.75) / entry * 100)
        self.assertEqual(t["at"], b["timestamp"].iloc[i + 1])
        self.assertEqual((t["gross"], t["outcome"]), (2.0, "doel"))

    def test_short_trade_has_the_stop_above(self):
        b = frame(mirror(long_rows()))
        i, sign, raw = sigs(mirror(long_rows()), 2)[0]
        v = next(x for x in tl.VARIANTS if x.name == "KANT_2_5M")
        t = tl._trade(v, b, i, sign, 0.0, raw)
        self.assertEqual(t["direction"], "short")
        self.assertAlmostEqual(t["risk_pct"], (220 - 104.75 - 107.5) / 107.5 * 100)

    def test_stop_is_floored_when_too_tight(self):
        rows = long_rows()
        b = frame(rows)
        v = next(x for x in tl.VARIANTS if x.name == "KANT_2_5M")
        t = tl._trade(v, b, 56, 1, 0.0, 112.4)       # ruwe stop vlak onder de instap van 112,5
        self.assertGreaterEqual(t["risk_pct"], 0.4 - 1e-9)


class CoverageWarningTest(unittest.TestCase):
    def test_warns_only_when_the_span_is_more_than_14_days_short(self):
        from importlib.util import module_from_spec, spec_from_file_location
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "scripts" / "strategy_lab.py"
        spec = spec_from_file_location("strategy_lab_script", path)
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        first, end = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-04-01", tz="UTC")     # 91 dagen
        self.assertEqual(mod.coverage_warning("15m", first, end, 0.25), None)                     # gevraagd 91,25 dagen
        text = mod.coverage_warning("15m", first, end, 3.0)
        self.assertIn("let op: 15m dekt maar 91 dagen, gevraagd 1095", text)
        self.assertIsNone(mod.coverage_warning("15m", first, end, 91 / 365 + 13 / 365))


class CandleCacheTest(unittest.TestCase):
    def test_five_minute_candles_can_be_downloaded_like_the_others(self):
        from app.replay import candles
        now = pd.Timestamp("2025-01-02", tz="UTC")

        def fetch(coin, timeframe, limit, since):
            ts = pd.date_range(pd.to_datetime(since, unit="ms", utc=True), periods=3, freq="5min")
            return pd.DataFrame({"timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
        df = candles.download_candles("BTC", 0, fetch=fetch, now=now, timeframe="5m", since_ts=now - pd.Timedelta(minutes=20))
        self.assertGreaterEqual(len(df), 3)
        self.assertTrue((df["timestamp"].diff().dropna() == pd.Timedelta(minutes=5)).all())


class FamilyTest(unittest.TestCase):
    NAMES = ["KANT_1_5M", "KANT_2_5M", "KANT_1_15M", "KANT_2_15M", "KANT_1_1H", "KANT_2_1H"]

    def test_six_pre_registered_variants(self):
        ks = [v for v in tl.VARIANTS if v.family == "kanteling"]
        self.assertEqual([v.name for v in ks], self.NAMES)
        self.assertEqual([v.timeframe for v in ks], ["5m", "5m", "15m", "15m", "1h", "1h"])
        self.assertEqual([v.params for v in ks], [(1, 3, 3.0, 24, 48), (2, 3, 3.0, 24, 96)] * 3)
        self.assertEqual(len(tl.VARIANTS), 20)
        self.assertFalse(any(v.htf for v in ks))

    def test_run_variant_on_the_designed_frame(self):
        df = frame(long_rows())[["timestamp", "open", "high", "low", "close", "volume"]]
        for name, at in (("KANT_1_5M", 45), ("KANT_2_5M", 57)):
            v = next(x for x in tl.VARIANTS if x.name == name)
            r = tl.run_variant(v, df)
            self.assertEqual(list(r.columns), ["at", "direction", "risk_pct", "gross", "net", "bars", "outcome", "i", "sign"])
            self.assertEqual(r["at"].iloc[0], df["timestamp"].iloc[at])
            self.assertEqual(r["direction"].iloc[0], "long")

    def test_run_and_placebo_end_to_end_on_noisy_series(self):
        rng = np.random.default_rng(3)
        n = 6000
        ret = rng.normal(0, 0.004, n) + (rng.random(n) < 0.01) * rng.normal(0, 0.03, n)
        close = 100 * np.exp(np.cumsum(ret))
        open_ = np.concatenate([[100.0], close[:-1]])
        df = pd.DataFrame({"timestamp": pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC"), "open": open_,
                           "high": np.maximum(open_, close) * (1 + rng.uniform(0, 0.002, n)), "low": np.minimum(open_, close) * (1 - rng.uniform(0, 0.002, n)),
                           "close": close, "volume": 1.0})
        total = 0
        for name in self.NAMES:
            v = next(x for x in tl.VARIANTS if x.name == name)
            r = tl.run_variant(v, df)
            self.assertEqual(list(r.columns), ["at", "direction", "risk_pct", "gross", "net", "bars", "outcome", "i", "sign"])
            p = tl.placebo_variant(v, df, r)
            self.assertEqual(len(p), len(r))
            total += len(r)
            if len(r) > 1:
                self.assertTrue((r["i"].diff().dropna() > 0).all())
        self.assertGreater(total, 0)


if __name__ == "__main__":
    unittest.main()
