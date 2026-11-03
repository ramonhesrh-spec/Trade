"""Hogere tijdframes als kenmerk (app/htf_zones.py, B-2026-11-03-09): alleen gesloten 12u- en dagcandles, onbekend is nooit 'nee', en de
splitsing op Bewijs telt alleen plannen die melden (A, B, B0, R)."""
import json
import unittest
from datetime import datetime, timezone

from app import htf_zones as hz, model_measure as mm

T0 = int(datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp())     # een maandag


def flat(n, tf_s, price=100.0, start=T0):
    return [[start + tf_s * i, price, price + 0.5, price - 0.5, price] for i in range(n)]


def with_gap(tf_s):
    """40 vlakke candles rond 100, dan een gap omlaag: candle 40 low 103, candle 42 high 101; de gap 101-103 blijft open."""
    r = flat(40, tf_s, 104.0)
    r += [[T0 + tf_s * 40, 104, 104.5, 103, 103.5], [T0 + tf_s * 41, 103.5, 103.6, 98, 98.5], [T0 + tf_s * 42, 98.5, 101, 97, 97.5]]
    r += [[T0 + tf_s * (43 + i), 97.5, 98, 97, 97.5] for i in range(10)]
    return r


class Features(unittest.TestCase):
    def test_limiet_in_een_open_12u_gap(self):
        r = with_gap(43200)
        now = T0 + 43200 * 53 + 1
        self.assertTrue(hz._in_zone(r, "12h", now, "short", 102.0))
        self.assertFalse(hz._in_zone(r, "12h", now, "short", 99.5))               # tegenvoorbeeld: onder de gap

    def test_een_lopende_candle_telt_niet(self):
        r = with_gap(43200)
        self.assertIsNone(hz._in_zone(r[:20], "12h", T0 + 43200 * 20 + 1, "short", 102.0))   # te weinig gesloten candles: onbekend

    def test_open_van_dag_en_week(self):
        days = flat(10, 86400, 100.0)
        now = T0 + 86400 * 9 + 3600                                               # woensdag van de tweede week
        self.assertTrue(hz._open(days, now, 100.2))
        self.assertFalse(hz._open(days, now, 101.0))
        self.assertIsNone(hz._open([], now, 100.0))

    def test_zonder_candles_alles_onbekend(self):
        f = hz.features("short", 100.0, None, None, T0)
        self.assertEqual(f, {"zone_12u": None, "zone_dag": None, "zone": None, "premium_dag": None, "open": None})


class Split(unittest.TestCase):
    def entry(self, code, r, htf):
        return {"code": code, "outcome": "take_profit" if r > 0 else "stop_loss", "r_gross": r, "limit_price": 100.0, "stop_loss": 99.0,
                "direction": "short", "filled_at": "2026-11-04T10:00:00+00:00", "outcome_at": "2026-11-04T12:00:00+00:00",
                "htf": json.dumps(htf) if htf is not None else None}

    def test_met_zonder_en_onbekend_apart_en_v1_p_tellen_niet(self):
        ents = [self.entry("B", 2.0, {"zone": True}), self.entry("B0", -1.0, {"zone": False}), self.entry("R", -1.0, None),
                self.entry("P", 3.0, {"zone": True})]
        (zone,) = [x for x in mm.htf_split([], [], ents, 0.0) if x["key"] == "zone"]
        self.assertEqual((zone["met"]["n"], zone["zonder"]["n"], zone["onbekend"]), (1, 1, 1))
        self.assertAlmostEqual(zone["met"]["mean"], 2.0)
