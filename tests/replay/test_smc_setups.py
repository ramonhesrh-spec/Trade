import unittest

import pandas as pd

from app.replay import smc_setups


def frame(rows, start="2026-01-01 00:00"):
    ts = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
                         "low": [r[2] for r in rows], "close": [r[3] for r in rows], "volume": 1.0})


def setup(direction="long", **kw):
    base = {"coin": "BTC", "direction": direction, "zone_low": 99.0, "zone_high": 100.0, "structure_level": 101.0,
            "sweep_price": 98.0, "liquidity_target": 110.0, "atr": 1.0, "created_at": "2026-01-01T00:00:00+00:00"}
    base.update(kw)
    return base


class SimulateSetupTests(unittest.TestCase):
    def test_long_wordt_gevuld_en_haalt_take(self):
        # entry 100, stop 98 - 0.25 = 97.75, risico 2.25, take 1R = 102.25
        rows = [(103, 103, 102, 102.5)] * 3 + [(102, 102.5, 99.9, 100.5)] + [(100.5, 103, 100.4, 102.8)]
        r = smc_setups.simulate_setup(setup(), frame(rows), rr_list=(1.0,), fee_pct=0, slippage_pct=0)
        self.assertEqual(r["status"], "gevuld")
        self.assertEqual(r["entry"], 100.0)
        self.assertAlmostEqual(r["stop"], 97.75)
        self.assertEqual(r["outcomes"][1.0].result, "take_profit")
        self.assertAlmostEqual(r["outcomes"][1.0].r_gross, 1.0)
        self.assertEqual(r["minutes_to_fill"], 3)

    def test_take_in_de_fill_candle_telt_niet_mee(self):
        # fill-candle raakt entry 100 en heeft high 102.5, maar die high kan voor de fill zijn geweest
        rows = [(103, 103, 102, 102.5), (102, 102.5, 99.9, 100.2), (100.2, 101.0, 100.0, 100.5)]
        r = smc_setups.simulate_setup(setup(), frame(rows), rr_list=(1.0,), fee_pct=0, slippage_pct=0)
        self.assertEqual(r["outcomes"][1.0].result, "expired")

    def test_long_stopt_uit(self):
        rows = [(103, 103, 102, 102.5), (102, 102.5, 99.9, 100.5), (100, 100.5, 97.0, 97.5)]
        r = smc_setups.simulate_setup(setup(), frame(rows), rr_list=(1.0,), fee_pct=0, slippage_pct=0)
        self.assertEqual(r["outcomes"][1.0].result, "stop_loss")

    def test_zelfde_candle_stop_en_take_telt_als_stop(self):
        rows = [(103, 103, 102, 102.5), (102, 120, 90, 100)]
        r = smc_setups.simulate_setup(setup(), frame(rows), rr_list=(1.0,), fee_pct=0, slippage_pct=0)
        self.assertEqual(r["outcomes"][1.0].result, "stop_loss")

    def test_niet_gevuld_als_koers_de_zone_niet_raakt(self):
        rows = [(105, 106, 104, 105)] * 30
        r = smc_setups.simulate_setup(setup(), frame(rows))
        self.assertEqual(r["status"], "niet_gevuld")

    def test_niet_gevuld_na_vervaltijd(self):
        rows = [(105, 106, 104, 105)] * 30 + [(105, 105, 99, 100)]
        r = smc_setups.simulate_setup(setup(), frame(rows), max_fill=pd.Timedelta(minutes=10))
        self.assertEqual(r["status"], "niet_gevuld")

    def test_short_spiegelt(self):
        s = setup("short", zone_low=100.0, zone_high=101.0, sweep_price=102.0, liquidity_target=90.0)
        # entry 100, stop 102.25, take 1R = 97.75
        rows = [(97, 98, 96, 97)] * 2 + [(98, 100.2, 97.9, 99.5)] + [(99.5, 99.6, 97.0, 97.5)]
        r = smc_setups.simulate_setup(s, frame(rows), rr_list=(1.0,), fee_pct=0, slippage_pct=0)
        self.assertEqual(r["entry"], 100.0)
        self.assertAlmostEqual(r["stop"], 102.25)
        self.assertEqual(r["outcomes"][1.0].result, "take_profit")

    def test_geen_atr_of_stop_aan_verkeerde_kant_geeft_none(self):
        self.assertIsNone(smc_setups.simulate_setup(setup(atr=None), frame([(1, 1, 1, 1)])))
        self.assertIsNone(smc_setups.simulate_setup(setup(sweep_price=101.0), frame([(1, 1, 1, 1)])))

    def test_doel_alleen_als_voorbij_een_stopafstand(self):
        rows = [(103, 103, 102, 102.5), (102, 102.5, 99.9, 100.5)] * 2
        near = smc_setups.simulate_setup(setup(liquidity_target=101.0), frame(rows))
        far = smc_setups.simulate_setup(setup(liquidity_target=110.0), frame(rows))
        self.assertNotIn(smc_setups.TARGET, near["outcomes"])
        self.assertIn(smc_setups.TARGET, far["outcomes"])


class FeatureTests(unittest.TestCase):
    def test_trend_en_geen_vooruitkijken(self):
        from tests.replay.fixtures import make_smc_prone_1m
        f = make_smc_prone_1m(days=40, start="2026-01-01", seed=3)
        at = f["timestamp"].iloc[-3000]
        s = setup(created_at=at.isoformat())
        feats = smc_setups.setup_features(s, {"BTC": f})
        self.assertIn(feats["trend_4u"], (True, False))
        self.assertIn(feats["trend_dag"], (True, False, None))
        # dezelfde setup met data die na `at` is afgekapt geeft dezelfde kenmerken
        cut = f[f["timestamp"] < at]
        self.assertEqual(feats, smc_setups.setup_features(s, {"BTC": cut}))


if __name__ == "__main__":
    unittest.main()
