import unittest

import numpy as np
import pandas as pd

from app.replay import lab
from app.replay.outcome import resolve
from tests.replay.fixtures import make_smc_prone_1m


def frame():
    return make_smc_prone_1m(days=60, start="2026-01-01", seed=21, start_price=100.0, spike_prob=0.01, spike_scale=0.01)


def all_signals(f, tf=15):
    bars = lab.add_indicators(lab.make_bars(f, tf))
    trend = lab.trend_on(bars, lab.make_bars(f, 240))
    return {rule: {(bars["close_time"].iloc[i], d) for i, d in lab.signal_bars(bars, trend, rule)} for rule in lab.RULES}


class LabTests(unittest.TestCase):
    def test_bars_alleen_gesloten_candles(self):
        f = frame().iloc[:1000]  # eindigt midden in een 15m-candle
        bars = lab.make_bars(f, 15)
        self.assertLessEqual(bars["close_time"].iloc[-1], f["timestamp"].iloc[-1] + pd.Timedelta(minutes=1))

    def test_geen_vooruitkijken_in_signalen(self):
        f = frame()
        cut = f["timestamp"].iloc[-3000]
        full = all_signals(f)
        part = all_signals(f[f["timestamp"] < cut])
        for rule in lab.RULES:
            self.assertEqual({x for x in full[rule] if x[0] <= cut}, {x for x in part[rule] if x[0] <= cut}, rule)
        self.assertGreater(sum(len(v) for v in full.values()), 20)

    def test_indicatoren_hangen_niet_af_van_latere_candles(self):
        f = frame()
        full = lab.add_indicators(lab.make_bars(f, 15))
        for k in (-9000, -5000, -1500):
            cut = f["timestamp"].iloc[k]
            part = lab.add_indicators(lab.make_bars(f[f["timestamp"] < cut], 15))
            ref = full[full["close_time"] <= part["close_time"].iloc[-1]].reset_index(drop=True)
            self.assertEqual(len(ref), len(part))
            for col in ("atr", "rsi", "ema21", "hh", "ll", "vol_avg"):
                np.testing.assert_allclose(part[col].to_numpy(), ref[col].to_numpy(), equal_nan=True, err_msg=col)

    def test_trend_gebruikt_alleen_gesloten_4u_candles(self):
        f = frame()
        bars = lab.make_bars(f, 15)
        full = lab.trend_on(bars, lab.make_bars(f, 240))
        cut = f["timestamp"].iloc[-7000]
        f2 = f[f["timestamp"] < cut]
        bars2 = lab.make_bars(f2, 15)
        part = lab.trend_on(bars2, lab.make_bars(f2, 240))
        np.testing.assert_array_equal(part, full[:len(part)])
        self.assertTrue(set(np.unique(full)) <= {-1, 0, 1} and (full == 0).sum() > 0 and (full != 0).sum() > 0)

    def test_resolve_many_gelijk_aan_outcome_resolve(self):
        f = frame()
        a = lab.Arrays.from_frame(f.assign(timestamp=f["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)))
        rng = np.random.default_rng(1)
        checked = 0
        for _ in range(60):
            s = int(rng.integers(0, len(f) - 3000))
            entry = float(f["open"].iloc[s])
            risk = entry * float(rng.uniform(0.001, 0.01))
            direction = "long" if rng.random() < 0.5 else "short"
            stop = entry - risk if direction == "long" else entry + risk
            e = s + 1440
            mine = lab.resolve_many(direction, entry, stop, lab.RR_LIST, a, s, e, 0.02, 0.01)
            at = f["timestamp"].iloc[s]
            for rr, (result, gross, net) in zip(lab.RR_LIST, mine):
                take = entry + (1 if direction == "long" else -1) * risk * rr
                ref = resolve(direction, entry, stop, take, f, at, pd.Timedelta(minutes=1440), 0.02, 0.01)
                self.assertEqual(result, ref.result)
                self.assertAlmostEqual(gross, ref.r_gross)
                self.assertAlmostEqual(net, ref.r_net)
                checked += 1
        self.assertEqual(checked, 180)

    def test_pullback_regel_op_gemaakte_data(self):
        f = frame()
        bars = lab.add_indicators(lab.make_bars(f, 15))
        up, down = lab._rule_pullback(bars, np.ones(len(bars)))
        # elke long-trigger: laag raakt EMA21 en sluit erboven op een groene candle
        for i in np.flatnonzero(up):
            self.assertLessEqual(bars["low"].iloc[i], bars["ema21"].iloc[i])
            self.assertGreater(bars["close"].iloc[i], bars["ema21"].iloc[i])
        for i in np.flatnonzero(down):
            self.assertGreaterEqual(bars["high"].iloc[i], bars["ema21"].iloc[i])
            self.assertLess(bars["close"].iloc[i], bars["ema21"].iloc[i])

    def test_summarize_kandidaat_en_afwijzing(self):
        start, end = pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2027-01-01", tz="UTC")
        rows = []
        for coin in ("A", "B", "C"):
            for k in range(60):
                rows.append({"coin": coin, "rule": "goed", "tf": 15, "rr": 1.0, "direction": "long", "result": "take_profit",
                             "r_gross": 1.0, "r_net": 0.9, "at": start + pd.Timedelta(days=5 * k)})
                rows.append({"coin": coin, "rule": "slecht", "tf": 15, "rr": 1.0, "direction": "long", "result": "stop_loss",
                             "r_gross": -1.0, "r_net": -1.1, "at": start + pd.Timedelta(days=5 * k)})
        res = lab.summarize(pd.DataFrame(rows), start, end).set_index("regel")
        self.assertTrue(res.loc["goed", "kandidaat"])
        self.assertFalse(res.loc["slecht", "kandidaat"])

    def test_evaluate_coin_geeft_trades(self):
        f = frame()
        start, end = f["timestamp"].iloc[20 * 1440], f["timestamp"].iloc[-1440 * 2]
        rows = lab.evaluate_coin("BTC", f, (15, 30), list(lab.RULES), start, end, 0.02, 0.01)
        df = pd.DataFrame(rows)
        self.assertGreater(len(df), 50)
        self.assertTrue(set(df["rr"]) == set(lab.RR_LIST))
        self.assertTrue((df["at"] >= start).all() and (df["at"] < end).all())


def ramp(n=3000, start="2026-03-01", slope=0.01, base=100.0):
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    close = base + slope * np.arange(n)
    open_ = np.concatenate([[base], close[:-1]])
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": np.maximum(open_, close) + 0.01,
                         "low": np.minimum(open_, close) - 0.01, "close": close, "volume": 1.0})


class CallTests(unittest.TestCase):
    def test_richting_en_vertraging_in_forward_returns(self):
        f = ramp()
        at = f["timestamp"].iloc[1000]
        calls = pd.DataFrame({"at": [at, at], "direction": ["long", "short"]})
        fr = lab.forward_returns(calls, f, delay_minutes=0, horizons=(60,))
        self.assertGreater(fr.loc[0, "pct_60"], 0)
        self.assertAlmostEqual(fr.loc[0, "pct_60"], -fr.loc[1, "pct_60"])
        self.assertAlmostEqual(fr.loc[0, "raw_60"], fr.loc[1, "raw_60"])
        self.assertAlmostEqual(fr.loc[0, "pct_60"], (0.01 * 60) / (100 + 0.01 * 999) * 100, places=2)
        late = lab.forward_returns(calls.iloc[:1], f, delay_minutes=30, horizons=(60,))
        self.assertNotAlmostEqual(late.loc[0, "pct_60"], fr.loc[0, "pct_60"], places=4)

    def test_call_zonder_candle_op_dat_moment_wordt_overgeslagen(self):
        f = ramp()
        calls = pd.DataFrame({"at": [f["timestamp"].iloc[-1] + pd.Timedelta(days=3)], "direction": ["long"]})
        self.assertTrue(lab.forward_returns(calls, f).empty)
        self.assertEqual(lab.trades_from_calls("BTC", calls, f, 0, 0.02, 0.01), [])

    def test_trades_from_calls_long_wint_in_stijgende_markt_short_verliest(self):
        f = ramp(n=6000, slope=0.02)
        at = f["timestamp"].iloc[2000]
        calls = pd.DataFrame({"at": [at, at], "direction": ["long", "short"], "category": ["day_trading", "day_trading"]})
        rows = pd.DataFrame(lab.trades_from_calls("BTC", calls, f, 0, 0.0, 0.0))
        self.assertEqual(len(rows), 6)
        longs = rows[rows["direction"] == "long"]
        shorts = rows[rows["direction"] == "short"]
        self.assertTrue((longs["result"] == "take_profit").all())
        self.assertTrue((shorts["result"] == "stop_loss").all())
        self.assertAlmostEqual(float(longs[longs["rr"] == 1.5]["r_gross"].iloc[0]), 1.5)


if __name__ == "__main__":
    unittest.main()
