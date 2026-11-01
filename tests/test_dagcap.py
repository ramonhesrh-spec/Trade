"""Dagcaps (CEO, 2026-11-01): hogere standaarden, en elke focus-motor met een dagcap telt hoeveel kansen de cap tegenhield (hartslag en Beheer)."""
import asyncio
import importlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import config, daycap, repo, structure_live as sl, zone_radar_live
from app.replay.lab import make_bars
from tests.replay.test_breakretest import frame
from tests.test_samenval import DbCase
from tests.test_structure_live import BREAK_BAR, CUT

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class DefaultsTest(unittest.TestCase):
    def test_caps_zonder_env(self):
        names = ("ZONE_RADAR_MAX_PER_DAY", "STRUCTURE_MAX_ALERTS_PER_DAY", "ZONE_SWEEP_MAX_PER_DAY", "POC_RADAR_MAX_PER_DAY")
        try:
            with mock.patch.dict(os.environ, {}, clear=False):
                for n in names:
                    os.environ.pop(n, None)
                with mock.patch("dotenv.load_dotenv"):
                    importlib.reload(config)
                    self.assertEqual([getattr(config, n) for n in names], [40, 30, 10, 10])
        finally:
            importlib.reload(config)

    def test_env_gaat_voor(self):
        try:
            with mock.patch.dict(os.environ, {"ZONE_RADAR_MAX_PER_DAY": "7"}), mock.patch("dotenv.load_dotenv"):
                importlib.reload(config)
                self.assertEqual(config.ZONE_RADAR_MAX_PER_DAY, 7)
        finally:
            importlib.reload(config)


class TextTest(unittest.TestCase):
    def test_tekst(self):
        self.assertEqual(daycap.held_text(3, 40), "3 kansen tegengehouden door de dagcap van 40")
        self.assertEqual(daycap.held_text(1, 30), "1 kans tegengehouden door de dagcap van 30")
        self.assertEqual(daycap.held_text(0, 30), "")

    def test_hartslag_krijgt_het_aantal_erbij(self):
        self.assertEqual(daycap.with_held("20 coins gecontroleerd", 2, 40), "20 coins gecontroleerd; 2 kansen tegengehouden door de dagcap van 40")
        self.assertEqual(daycap.with_held("20 coins gecontroleerd", 0, 40), "20 coins gecontroleerd")

    def test_regels_alleen_voor_soorten_met_iets_tegengehouden(self):
        lines = daycap.lines({"zone_radar": 3, "structuur": 0, "poc_radar": 1}, {"zone_radar": 40, "structuur": 30, "poc_radar": 10})
        self.assertEqual(lines, [{"label": "Zone-radar", "text": "3 kansen tegengehouden door de dagcap van 40"},
                                 {"label": "POC-radar", "text": "1 kans tegengehouden door de dagcap van 10"}])


class RepoTest(DbCase):
    def test_een_kans_telt_een_keer_per_venster(self):
        for _ in range(3):                                # elke cyclus van 5 minuten ziet dezelfde kans opnieuw
            repo.record_cap_hold("zone_radar", "BTC:z1", NOW.isoformat())
        repo.record_cap_hold("zone_radar", "ETH:z2", NOW.isoformat())
        repo.record_cap_hold("poc_radar", "BTC:p", (NOW - timedelta(hours=30)).isoformat())
        since = (NOW - daycap.WINDOW).isoformat()
        self.assertEqual(repo.count_cap_holds("zone_radar", since), 2)
        self.assertEqual(repo.cap_hold_counts(since), {"zone_radar": 2})


def plan(coin, distance, key):
    return {"coin": coin, "direction": "long", "tf": "1h", "zone_key": key, "zone_low": 99.0, "zone_high": 100.0, "limit": 100.0,
            "stop_loss": 98.0, "take_profit": 104.0, "rr": 2.0, "atr": 1.0, "target_tf": "1h", "target_low": 104.0, "target_high": 105.0,
            "distance": distance}


class ZoneRadarCapTest(DbCase):
    def run_once(self, found):
        async def scan(coin, stamp, waiting, params=None):
            return [p for p in found if p["coin"] == coin]

        async def nothing(*a, **k):
            return None

        with mock.patch.object(config, "ZONE_RADAR_MAX_PER_DAY", 1), mock.patch.object(zone_radar_live, "_scan", scan), \
                mock.patch.object(zone_radar_live, "_track", nothing), mock.patch.object(zone_radar_live, "_push_new_card", nothing), \
                mock.patch.object(zone_radar_live, "_context", lambda c, s: {}), \
                mock.patch.object(zone_radar_live.poc_radar_live, "samenval", lambda *a: None), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}, {"symbol": "ETH"}, {"symbol": "SOL"}]):
            asyncio.run(zone_radar_live.run(NOW))

    def test_hartslag_noemt_wat_de_cap_tegenhield(self):
        found = [plan("BTC", 0.01, "1h:a"), plan("ETH", 0.02, "1h:b"), plan("SOL", 0.03, "1h:c")]
        self.run_once(found)
        self.assertEqual(len(repo.list_zone_radar_setups()), 1)
        self.assertEqual(repo.get_beat("zone_radar")["detail"], "3 coins gecontroleerd; 2 kansen tegengehouden door de dagcap van 1")
        self.run_once(found)                               # dezelfde twee kansen in de volgende cyclus tellen niet dubbel
        self.assertEqual(repo.get_beat("zone_radar")["detail"], "3 coins gecontroleerd; 2 kansen tegengehouden door de dagcap van 1")

    def test_een_zone_die_al_een_kaart_had_telt_niet_als_tegengehouden(self):
        self.run_once([plan("BTC", 0.01, "1h:a")])
        repo.end_zone_radar_setup(repo.list_zone_radar_setups()[0]["id"], "zone_weg")
        self.run_once([plan("BTC", 0.01, "1h:a")])
        self.assertEqual(repo.get_beat("zone_radar")["detail"], "3 coins gecontroleerd")


class StructureCapTest(DbCase):
    def setUp(self):
        super().setUp()
        self.f = frame(minutes=60 * 24 * 6, plant=True, cut=CUT)
        self.bars = make_bars(self.f, 30)
        patcher = mock.patch.object(sl, "MIN_RR", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_live(self, n_closed, cap):
        bars, f = self.bars, self.f

        def fake(coin, timeframe="30m", limit=300, since=None):
            if timeframe == "30m":
                return bars.iloc[:n_closed + 1][["timestamp", "open", "high", "low", "close", "volume"]]
            end = bars.at[n_closed - 1, "close_time"]
            return f[f["timestamp"] < end].set_index("timestamp").resample("5min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index().tail(limit)

        async def fake_push(*a, **k):
            return None

        now = (self.bars.at[n_closed - 1, "close_time"]).to_pydatetime()
        with mock.patch("app.exchange.fetch_ohlcv", fake), mock.patch("app.push_notify.send_push", fake_push), \
                mock.patch.object(sl, "call_claude", lambda ctx: {"grade": "A", "reason": "x"}), mock.patch.object(config, "FIXED_COINS", ["BTC"]), \
                mock.patch.object(config, "STRUCTURE_MAX_ALERTS_PER_DAY", cap), mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]):
            asyncio.run(sl.run(now))

    def test_hartslag_noemt_wat_de_cap_tegenhield(self):
        self.run_live(BREAK_BAR + 4, cap=0)
        self.assertEqual(len(repo.list_structure_setups(("niet_gemeld",))), 1)
        detail = repo.get_beat("structuur")["detail"]
        self.assertTrue(detail.endswith("; 1 kans tegengehouden door de dagcap van 0"), detail)
        self.assertEqual(sl.parse_beat(detail), {"checked": 1, "total": 1})

    def test_zonder_volle_cap_geen_regel(self):
        self.run_live(BREAK_BAR + 4, cap=5)
        self.assertNotIn("tegengehouden", repo.get_beat("structuur")["detail"])


def poc_plan(coin, distance, key):
    return {"coin": coin, "direction": "long", "period": "dag", "period_start": "2026-10-30T00:00:00+00:00", "level_key": key, "level": 100.0,
            "limit_price": 100.0, "stop_loss": 99.0, "take_profit": None, "rr": None, "atr": 1.0, "distance": distance}


class PocRadarCapTest(DbCase):
    def test_hartslag_noemt_wat_de_cap_tegenhield(self):
        from app import poc_radar_live
        found = [poc_plan("BTC", 0.01, "dag:a"), poc_plan("ETH", 0.02, "dag:b")]

        async def scan(coin, stamp, waiting, params=None):
            return [p for p in found if p["coin"] == coin]

        async def nothing(*a, **k):
            return None

        with mock.patch.object(config, "POC_RADAR_MAX_PER_DAY", 1), mock.patch.object(poc_radar_live, "_scan_coin", scan), \
                mock.patch.object(poc_radar_live, "due", lambda c, s: True), mock.patch.object(poc_radar_live, "_announce", nothing), \
                mock.patch.object(poc_radar_live.focus, "engine_on", lambda t: True), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}, {"symbol": "ETH"}]):
            asyncio.run(poc_radar_live.scan(NOW))
            asyncio.run(poc_radar_live.scan(NOW + timedelta(minutes=5)))
        self.assertEqual(repo.get_beat("poc_radar")["detail"], "2 van 2 coins bijgewerkt; 1 kans tegengehouden door de dagcap van 1")


class ZoneSweepCapTest(DbCase):
    def test_een_stille_kaart_door_de_cap_telt(self):
        from app import zone_sweep_live
        ids = iter([11, 12])
        row = {"coin": "BTC", "direction": "long", "limit_price": 100.0, "variant": "ZS_1H", "take_profit": None}
        with mock.patch.object(config, "ZONE_SWEEP_MAX_PER_DAY", 0), mock.patch.object(repo, "insert_zone_sweep_setup", lambda r, at: next(ids)), \
                mock.patch.object(zone_sweep_live.zsw, "alive", lambda r, p: True), \
                mock.patch.object(zone_sweep_live.poc_radar_live, "samenval", lambda *a: None):
            asyncio.run(zone_sweep_live._register(row, 100.0, pd.Timestamp(NOW)))
            asyncio.run(zone_sweep_live._register(row, 100.0, pd.Timestamp(NOW)))
        self.assertEqual(repo.count_cap_holds("zone_sweep", (NOW - daycap.WINDOW).isoformat()), 2)
        self.assertEqual(zone_sweep_live.beat_detail(20, NOW), "20 coins gecontroleerd; 2 kansen tegengehouden door de dagcap van 10")


if __name__ == "__main__":
    unittest.main()
