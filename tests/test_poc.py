"""Het volumeprofiel en de POC (app/poc.py): vaste bakken van 0,05% van de prijs, volume gelijk verdeeld over de bakken tussen low en high, een POC
per gesloten UTC-dag en ISO-week, naakt zolang geen latere 5m-candle hem raakte (een lont telt als geraakt)."""
import unittest

import pandas as pd

from app import poc

T0 = pd.Timestamp("2026-10-12T00:00:00Z")      # een maandag


def m5(rows, start=T0):
    """rows: (high, low, close, volume); open is de close van de vorige (de eerste: de close zelf)."""
    out = []
    prev = None
    for i, (h, low, c, v) in enumerate(rows):
        o = c if prev is None else prev
        out.append({"timestamp": start + i * poc.BAR, "open": o, "high": h, "low": low, "close": c, "volume": v})
        prev = c
    return pd.DataFrame(out)


def flat_day(price, n=288, start=T0, vol=1.0):
    return m5([(price * 1.0001, price, price, vol)] * n, start=start)


class ProfileTests(unittest.TestCase):
    def test_volume_gelijk_over_de_bakken_tussen_low_en_high(self):
        width = 1.0
        prof = poc.volume_profile(m5([(12.5, 10.2, 11.0, 6.0)]), width)
        self.assertEqual(prof, {10: 2.0, 11: 2.0, 12: 2.0})

    def test_poc_is_het_midden_van_de_zwaarste_bak(self):
        # bakbreedte 0,05% van de eerste open (100): 0,05; de candle met veel volume ligt rond 101
        df = m5([(100.02, 99.98, 100.0, 1.0), (101.01, 101.0, 101.0, 50.0), (100.02, 99.98, 100.0, 1.0)])
        price = poc.poc_of(df)
        self.assertAlmostEqual(price, 101.025, places=6)

    def test_gelijke_bakken_kiezen_de_dichtst_bij_het_slot(self):
        df = m5([(100.0, 100.0, 100.0, 0.0), (100.01, 100.01, 100.01, 5.0), (105.01, 105.01, 105.01, 5.0), (104.0, 104.0, 104.0, 0.0)])
        self.assertAlmostEqual(poc.poc_of(df), 105.025, places=6)

    def test_geen_volume_geen_poc(self):
        self.assertIsNone(poc.poc_of(m5([(100.0, 99.0, 99.5, 0.0)])))
        self.assertIsNone(poc.poc_of(m5([])))


class PeriodTests(unittest.TestCase):
    def test_start_van_dag_en_isoweek(self):
        ts = pd.Timestamp("2026-10-15T13:20:00Z")      # donderdag
        self.assertEqual(poc.period_start("day", ts), pd.Timestamp("2026-10-15T00:00:00Z"))
        self.assertEqual(poc.period_start("week", ts), pd.Timestamp("2026-10-12T00:00:00Z"))

    def test_alleen_gesloten_periodes_in_het_venster(self):
        now = pd.Timestamp("2026-10-28T10:00:00Z")      # woensdag
        days = poc.closed_starts("day", now)
        self.assertEqual(days[-1], pd.Timestamp("2026-10-27T00:00:00Z"))       # vandaag loopt nog
        self.assertEqual(days[0], pd.Timestamp("2026-10-14T00:00:00Z"))        # 14 dagen terug
        self.assertEqual(len(days), 14)
        self.assertEqual(poc.closed_starts("week", now), [pd.Timestamp("2026-10-19T00:00:00Z")])

    def test_nieuwe_niveaus_alleen_voor_volledige_gesloten_periodes(self):
        day1 = flat_day(100.0)
        day2 = flat_day(110.0, start=T0 + pd.Timedelta(days=1))
        today = flat_day(120.0, n=30, start=T0 + pd.Timedelta(days=2))
        df = pd.concat([day1, day2, today], ignore_index=True)
        now = T0 + pd.Timedelta(days=2, hours=2, minutes=30)
        levels = poc.new_levels(df, now, set())
        self.assertEqual([lv.key for lv in levels], ["day:2026-10-12T00:00:00+00:00", "day:2026-10-13T00:00:00+00:00"])
        self.assertAlmostEqual(levels[0].price, 100.025, places=4)
        # al bekend: niet opnieuw
        self.assertEqual(len(poc.new_levels(df, now, {levels[0].key})), 1)
        # een dag waarvan het begin ontbreekt telt niet
        self.assertEqual([lv.key for lv in poc.new_levels(df.iloc[10:], now, set())], ["day:2026-10-13T00:00:00+00:00"])

    def test_vormende_candle_telt_nooit_mee(self):
        day1 = flat_day(100.0)
        df = pd.concat([day1, m5([(101.0, 99.0, 100.0, 1.0)], start=T0 + pd.Timedelta(days=1))], ignore_index=True)
        self.assertEqual(poc.new_levels(df, T0 + pd.Timedelta(days=1, minutes=4), set())[0].touched_at, None)


class NakedTests(unittest.TestCase):
    def test_lont_door_het_niveau_telt_als_geraakt(self):
        day1 = flat_day(100.0)
        after = m5([(110.0, 109.0, 109.5, 1.0), (109.5, 100.0, 109.0, 1.0)], start=T0 + pd.Timedelta(days=1))
        df = pd.concat([day1, after], ignore_index=True)
        lv = poc.new_levels(df, T0 + pd.Timedelta(days=1, hours=1), set())[0]
        self.assertEqual(lv.touched_at, T0 + pd.Timedelta(days=1, minutes=5))
        self.assertFalse(lv.naked)

    def test_niet_geraakt_is_naakt(self):
        day1 = flat_day(100.0)
        after = m5([(110.0, 101.0, 109.5, 1.0)] * 3, start=T0 + pd.Timedelta(days=1))
        lv = poc.new_levels(pd.concat([day1, after], ignore_index=True), T0 + pd.Timedelta(days=1, hours=1), set())[0]
        self.assertTrue(lv.naked)

    def test_touches_op_latere_candles(self):
        lv = poc.PocLevel("day", T0, 100.0, None)
        later = m5([(105.0, 101.0, 104.0, 1.0), (104.0, 99.0, 103.0, 1.0)], start=T0 + pd.Timedelta(days=3))
        self.assertEqual(poc.first_touch(lv, later), T0 + pd.Timedelta(days=3, minutes=5))
        inside = m5([(100.5, 99.5, 100.0, 1.0)], start=T0 + pd.Timedelta(hours=5))      # binnen de eigen periode: telt niet
        self.assertIsNone(poc.first_touch(lv, inside))

    def test_near_alleen_naakte_niveaus_binnen_03_procent(self):
        levels = [poc.PocLevel("day", T0, 100.0, None), poc.PocLevel("week", T0, 200.0, T0 + pd.Timedelta(days=8))]
        self.assertTrue(poc.near(100.29, levels))
        self.assertFalse(poc.near(100.31, levels))
        self.assertFalse(poc.near(200.0, levels))       # geraakt: niet naakt

    def test_vanaf_wanneer_ophalen(self):
        now = pd.Timestamp("2026-10-28T10:00:00Z")
        first = poc.fetch_from(now, set(), None)
        self.assertEqual(first, pd.Timestamp("2026-10-14T00:00:00Z"))
        known = {f"day:{s.isoformat()}" for s in poc.closed_starts("day", now)} | {f"week:{s.isoformat()}" for s in poc.closed_starts("week", now)}
        checked = pd.Timestamp("2026-10-28T08:55:00Z")
        self.assertEqual(poc.fetch_from(now, known, checked), checked + poc.BAR)
        missing_yesterday = known - {"day:2026-10-27T00:00:00+00:00"}
        self.assertEqual(poc.fetch_from(now, missing_yesterday, checked), pd.Timestamp("2026-10-27T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
