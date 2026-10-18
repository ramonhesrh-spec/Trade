import unittest
from unittest import mock

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs


class ContainUntilLastTouchTest(unittest.TestCase):
    def setUp(self):
        n = 61
        self.close = np.full(n, 105.0)
        self.close[41:] = 113.0                     # na de laatste aanraking naar het aanbod boven de range
        self.high, self.low = self.close + 1, self.close - 1
        self.ph, self.pl = np.zeros(n, bool), np.zeros(n, bool)
        for k in (10, 20, 30):
            self.high[k], self.ph[k] = 110.0, True
        for k in (15, 25, 35):
            self.low[k], self.pl[k] = 100.0, True
        ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC").to_numpy()
        self.cols = (self.high, self.low, self.close, np.ones(n), ts)

    def run_range(self):
        return rs.range_at(None, 60, "1h", self.ph, self.pl, self.cols)

    def test_standaard_wijst_een_slot_buiten_na_de_laatste_aanraking_af(self):
        rng, why = self.run_range()
        self.assertIsNone(rng)
        self.assertIn("slot buiten", why)

    def test_met_de_instelling_telt_alleen_tot_de_laatste_aanraking(self):
        with mock.patch.object(rs, "CONTAIN_UNTIL_LAST_TOUCH", True):
            rng, why = self.run_range()
        self.assertIsNotNone(rng, why)
        self.assertEqual((rng.high, rng.low), (110.0, 100.0))

    def test_een_slot_buiten_tussen_de_aanrakingen_blijft_een_afwijzing(self):
        self.close[22] = 113.0
        with mock.patch.object(rs, "CONTAIN_UNTIL_LAST_TOUCH", True):
            rng, why = self.run_range()
        self.assertIsNone(rng)


if __name__ == "__main__":
    unittest.main()
