import io
import unittest
import zipfile

import numpy as np
import pandas as pd

from app.replay import lab, positioning


def make_zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", text)
    return buf.getvalue()


METRICS_CSV = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
               "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
               "2026-09-20 00:05:00,BTCUSDT,100,1,1.5,1.4,2.0,0.9\n2026-09-20 00:10:00,BTCUSDT,101,1,1.6,1.4,2.1,1.1\n")
FUNDING_CSV = "calc_time,funding_interval_hours,last_funding_rate\n1758326400000,8,0.0001\n1758355200000,8,-0.0002\n"


def synthetic_metrics(days=40, seed=3):
    rng = np.random.default_rng(seed)
    n = days * 288
    ts = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "oi": 1000 + np.cumsum(rng.normal(0, 3, n)), "top_ratio": 1.5 + rng.normal(0, .1, n),
                         "global_ratio": 2 + rng.normal(0, .2, n), "taker_ratio": 1 + rng.normal(0, .1, n)})


def synthetic_funding(days=40, seed=4):
    rng = np.random.default_rng(seed)
    n = days * 3
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="8h", tz="UTC"), "funding": rng.normal(0.0001, 0.00005, n)})


class ParseTests(unittest.TestCase):
    def test_metrics_en_funding_parsen(self):
        m = positioning.parse_metrics_zip(make_zip(METRICS_CSV))
        self.assertEqual(list(m.columns), ["timestamp", "oi", "top_ratio", "global_ratio", "taker_ratio"])
        self.assertEqual(m["oi"].tolist(), [100, 101])
        self.assertEqual(str(m["timestamp"].iloc[0]), "2026-09-20 00:05:00+00:00")
        f = positioning.parse_funding_zip(make_zip(FUNDING_CSV))
        self.assertEqual(f["funding"].tolist(), [0.0001, -0.0002])
        self.assertEqual(f["timestamp"].iloc[0], pd.Timestamp("2025-09-20 00:00:00", tz="UTC"))

    def test_download_slaat_ontbrekende_dagen_over_en_ontdubbelt(self):
        calls = []

        def get(url):
            calls.append(url)
            return make_zip(METRICS_CSV) if "2026-09-20" in url or "2026-09-21" in url else None

        m = positioning.download_metrics("btc", pd.Timestamp("2026-09-19", tz="UTC"), pd.Timestamp("2026-09-22", tz="UTC"), get=get)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("BTCUSDT-metrics" in c for c in calls))
        self.assertEqual(len(m), 2)  # twee dagen met dezelfde twee tijdstempels
        self.assertTrue(m["timestamp"].is_unique)


class FeatureTests(unittest.TestCase):
    def setUp(self):
        from tests.replay.fixtures import make_smc_prone_1m
        self.f = make_smc_prone_1m(days=40, start="2026-01-01", seed=2, spike_prob=0.01, spike_scale=0.01)
        self.metrics, self.funding = synthetic_metrics(), synthetic_funding()

    def test_geen_vooruitkijken_in_positioneringskenmerken(self):
        bars = lab.add_indicators(lab.make_bars(self.f, 15))
        full = lab.attach_positioning(bars, self.metrics, self.funding)
        cut = bars["close_time"].iloc[-800]
        part = lab.attach_positioning(bars[bars["close_time"] <= cut].reset_index(drop=True),
                                      self.metrics[self.metrics["timestamp"] <= cut], self.funding[self.funding["timestamp"] <= cut])
        ref = full[full["close_time"] <= cut].reset_index(drop=True)
        for col in ("oi_chg_1h", "oi_chg_4h", "taker_z", "global_z", "top_z", "funding_z"):
            np.testing.assert_allclose(part[col].to_numpy(), ref[col].to_numpy(), equal_nan=True, err_msg=col)

    def test_meting_geldt_pas_na_de_vertraging(self):
        bars = lab.add_indicators(lab.make_bars(self.f, 15))
        m = self.metrics.copy()
        m.loc[m["timestamp"] == pd.Timestamp("2026-01-20 12:10", tz="UTC"), "oi"] = 1e9  # piek in één meting, geldig vanaf 12:15
        b = lab.attach_positioning(bars, m, self.funding)
        row = b[b["close_time"] == pd.Timestamp("2026-01-20 12:00", tz="UTC")]
        self.assertLess(abs(float(row["oi_chg_1h"].iloc[0])), 50)  # de piek van 12:10 is er om 12:00 nog niet
        later = b[b["close_time"] == pd.Timestamp("2026-01-20 12:15", tz="UTC")]
        self.assertGreater(abs(float(later["oi_chg_1h"].iloc[0])), 1e6)

    def test_regels_zonder_positionering_geven_geen_signalen(self):
        bars = lab.add_indicators(lab.make_bars(self.f, 15))
        trend = lab.trend_on(bars, lab.make_bars(self.f, 240))
        for rule in lab.POSITIONING_RULES:
            self.assertEqual(lab.signal_bars(bars, trend, rule), [], rule)

    def test_regelrichting(self):
        n = 40
        base = pd.DataFrame({"close_time": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"), "close": np.linspace(100, 100, n)})
        for c in ("oi_chg_1h", "taker_z", "global_z", "funding_z"):
            base[c] = 0.0
        b = base.copy(); b.loc[20, "taker_z"] = 3.0
        up, down = lab._rule_pos_taker_flow(b, None); self.assertTrue(up[20] and not down[20])
        up, down = lab._rule_pos_taker_fade(b, None); self.assertTrue(down[20] and not up[20])
        b = base.copy(); b.loc[20, "global_z"] = 3.0
        up, down = lab._rule_pos_crowd_fade(b, None); self.assertTrue(down[20] and not up[20])
        b = base.copy(); b.loc[20, "funding_z"] = -3.0
        up, down = lab._rule_pos_funding_fade(b, None); self.assertTrue(up[20] and not down[20])
        b = base.copy(); b.loc[20, "oi_chg_1h"] = 2.0; b["close"] = 100.0; b.loc[20, "close"] = 101.0
        up, down = lab._rule_pos_oi_trend(b, None); self.assertTrue(up[20] and not down[20])
        b = base.copy(); b.loc[20, "oi_chg_1h"] = -2.0; b["close"] = 100.0; b.loc[20, "close"] = 99.0
        up, down = lab._rule_pos_oi_flush(b, None); self.assertTrue(up[20] and not down[20])

    def test_evaluate_coin_met_positionering(self):
        start, end = self.f["timestamp"].iloc[20 * 1440], self.f["timestamp"].iloc[-1440 * 2]
        rows = lab.evaluate_coin("BTC", self.f, (15,), list(lab.POSITIONING_RULES), start, end, 0.02, 0.01,
                                 positioning=(self.metrics, self.funding))
        self.assertGreater(len(rows), 0)
        self.assertTrue(set(pd.DataFrame(rows)["rule"]) <= set(lab.POSITIONING_RULES))


if __name__ == "__main__":
    unittest.main()
