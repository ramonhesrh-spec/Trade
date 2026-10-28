"""De live POC-radar (app/poc_radar_live.py) tegen een kunstmatige markt: niveaus één keer per uur bijgewerkt en bewaard, een kaart per kant,
één melding, dagcap, vullen wordt een signaal buiten de keten met journaal, een kaart zonder doel volgt de referentie-uitgang, CEO-only als
POC_RADAR_PUBLIC uit staat, en de migratie van een oude database."""
import asyncio
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, level_check, poc, push_notify, range_sweep_live as rsl, repo, rule_live
from app import poc_radar_live as live
from tests.test_samenval import DbCase

T0 = pd.Timestamp("2026-10-20T00:00:00Z")      # dinsdag: geen volledige ISO-week in de data, alleen dagen


def candles(rows, start):
    out, prev = [], None
    for i, (h, low, c) in enumerate(rows):
        out.append({"timestamp": start + i * poc.BAR, "open": c if prev is None else prev, "high": h, "low": low, "close": c, "volume": 10.0})
        prev = c
    return pd.DataFrame(out)


def day(high, low, close, start, n=288):
    return candles([(high, low, close)] * n, start)


def market():
    """Dag 1 rond 100 (POC 100,025), dag 2 rond 110 (POC 110,0275), vandaag rond 106. Beide POC's zijn naakt en liggen binnen 6%."""
    return pd.concat([day(100.01, 100.0, 100.0, T0), day(110.01, 110.0, 110.0, T0 + pd.Timedelta(days=1)),
                      day(106.5, 105.5, 106.0, T0 + pd.Timedelta(days=2), n=288)], ignore_index=True)


class EngineCase(DbCase):
    def setUp(self):
        super().setUp()
        self.student = repo.create_user("b", "x", 0, 1)
        self.ceo = repo.get_user_by_username("a")["id"]
        self.m5 = market()
        self.now = (T0 + pd.Timedelta(days=2, hours=10, minutes=2)).to_pydatetime()
        self.pushed, self.calls_5m = [], []
        for p in (mock.patch.object(config, "CEO_USERNAME", ""), mock.patch.object(config, "POC_RADAR_ENABLED", True),
                  mock.patch.object(config, "POC_RADAR_PUBLIC", True), mock.patch.object(config, "POC_RADAR_MAX_PER_DAY", 10),
                  mock.patch.object(config, "SMC_MIN_STOP_PCT", 0.2),
                  mock.patch.object(repo, "list_coins", return_value=[{"symbol": "BTC"}]),
                  mock.patch.object(rsl, "fetch_bars", self.fetch_bars), mock.patch("app.exchange.fetch_ohlcv", self.fetch_ohlcv),
                  mock.patch.object(push_notify, "is_quiet_now", return_value=False),
                  mock.patch("app.push_notify.send_push", self.fake_push)):
            p.start()
            self.addCleanup(p.stop)

    def visible(self):
        return self.m5[self.m5["timestamp"] < pd.Timestamp(self.now)].reset_index(drop=True)

    def fetch_ohlcv(self, coin, timeframe="5m", limit=200, since=None):
        assert timeframe == "5m"
        self.calls_5m.append(since)
        df = self.visible()
        if since is not None:
            df = df[df["timestamp"] >= pd.Timestamp(since, unit="ms", tz="UTC")]
        return df.head(limit).reset_index(drop=True)

    def fetch_bars(self, coin, timeframe, limit):
        df = self.visible()
        if timeframe == "5m":
            return df.tail(limit).reset_index(drop=True)
        rule = {"15m": "15min", "1h": "1h", "4h": "4h"}[timeframe]
        out = df.set_index("timestamp").resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        return out.dropna().reset_index().tail(limit).reset_index(drop=True)

    async def fake_push(self, user_id, title, body, url, silent=False, tag=None, badge=None):
        self.pushed.append({"user": user_id, "title": title, "body": body, "url": url})

    def run_(self, minutes_later=0):
        self.now = (pd.Timestamp(self.now) + pd.Timedelta(minutes=minutes_later)).to_pydatetime()
        asyncio.run(live.run(self.now))

    def cards(self, *states):
        return repo.list_poc_radar_setups(states or live.ALL_STATES)

    def signals(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM signals WHERE trade_type = 'poc_radar' ORDER BY id")]

    def titles(self, part):
        return [p for p in self.pushed if part in p["title"]]


class ScanTest(EngineCase):
    def test_kaart_per_kant_op_de_naakte_poc_met_een_melding(self):
        self.run_()
        cards = {c["direction"]: c for c in self.cards()}
        self.assertEqual(set(cards), {"long", "short"})
        self.assertAlmostEqual(cards["long"]["limit_price"], 100.025, places=3)
        self.assertAlmostEqual(cards["short"]["limit_price"], 110.0275, places=3)
        self.assertAlmostEqual(cards["long"]["take_profit"], 110.0275, places=3)     # het eerste niveau boven de koers
        self.assertEqual(cards["long"]["level_key"], "day:2026-10-20T00:00:00+00:00")
        news = self.titles("POC-radar · ongetest")
        self.assertTrue(news)
        self.assertTrue(all(p["url"].startswith("/smc#radar-poc-") for p in news))
        # niveaus zijn bewaard, met de aanraking per niveau
        self.assertEqual(len(repo.list_poc_levels("BTC", "2026-01-01")), 2)
        self.assertIsNotNone(repo.get_poc_scan("BTC"))

    def test_een_keer_per_uur_ophalen_en_nooit_een_tweede_kaart(self):
        self.run_()
        first = len(self.calls_5m)
        self.run_(minutes_later=5)
        self.assertEqual(len(self.calls_5m), first)                   # zelfde uur: geen nieuwe 5m-ophaal voor het profiel
        self.run_(minutes_later=60)
        self.assertEqual(len(self.calls_5m), first + 1)                # nieuw uur: alleen de nieuwe candles, één aanroep
        self.assertEqual(len(self.cards()), 2)
        self.assertEqual(len(self.titles("POC-radar · ongetest")), len(set(p["user"] for p in self.pushed)))

    def test_dagcap(self):
        with mock.patch.object(config, "POC_RADAR_MAX_PER_DAY", 1):
            self.run_()
        self.assertEqual(len(self.cards()), 1)

    def test_uit_doet_niets(self):
        with mock.patch.object(config, "POC_RADAR_ENABLED", False):
            self.run_()
        self.assertEqual(self.cards(), [])
        self.assertEqual(self.calls_5m, [])

    def test_geraakte_poc_geeft_geen_kaart(self):
        # vandaag zakt een lont door 100,025: dag 1 is niet meer naakt
        self.m5.loc[len(self.m5) - 200, "low"] = 99.0
        self.run_()
        self.assertEqual({c["direction"] for c in self.cards()}, {"short"})


class FillTest(EngineCase):
    def test_vulling_wordt_een_signaal_buiten_de_keten_met_journaal_en_melding(self):
        self.run_()
        long = next(c for c in self.cards() if c["direction"] == "long")
        drop = candles([(106.0, 101.0, 101.5), (101.5, 100.0, 100.5)], pd.Timestamp(self.now).floor("5min") + poc.BAR)
        self.m5 = pd.concat([self.m5[self.m5["timestamp"] < drop["timestamp"].iloc[0]], drop], ignore_index=True)
        self.run_(minutes_later=15)
        sigs = self.signals()
        self.assertEqual(len(sigs), 1)
        g = sigs[0]
        self.assertEqual((g["trade_type"], g["direction"]), ("poc_radar", "long"))
        self.assertAlmostEqual(g["price"], long["limit_price"])
        self.assertAlmostEqual(g["take_profit"], long["take_profit"])
        self.assertIsNone(repo.get_chain_link(g["id"]))
        with db.session() as conn:
            users = {r["user_id"] for r in conn.execute("SELECT user_id FROM journal_entries WHERE signal_id = ?", (g["id"],))}
        self.assertEqual(users, {self.ceo, self.student})
        # de vulling gaat via send_kans_push (dagbudget en conflictregel); een geweerde push wordt een rustige melding, dus per kijker één van beide
        with db.session() as conn:
            noted = {r["user_id"] for r in conn.execute("SELECT user_id FROM notifications WHERE title LIKE '%POC-radar gevuld%'")}
        self.assertEqual({p["user"] for p in self.titles("POC-radar gevuld")} | noted, {self.ceo, self.student})
        self.assertEqual(repo.get_poc_radar_setup(long["id"])["state"], "filled")

    def test_ceo_only_als_niet_publiek(self):
        with mock.patch.object(config, "POC_RADAR_PUBLIC", False):
            self.run_()
        self.assertEqual({p["user"] for p in self.pushed}, {self.ceo})
        self.assertIn("poc_radar", rule_live.ceo_only_types(True, True, False))
        self.assertNotIn("poc_radar", rule_live.ceo_only_types(True, True, True))

    def test_kaart_vervalt_na_ttl(self):
        self.run_()
        self.run_(minutes_later=4 * 24 * 60)
        self.assertEqual({c["state"] for c in self.cards()} - {"waiting"}, {"verlopen"})


class NoTargetTest(EngineCase):
    def test_kaart_zonder_doel_meet_de_referentie_uitgang_en_level_check_laat_hem(self):
        stamp = pd.Timestamp(self.now)
        sid = repo.insert_poc_radar_setup({"coin": "BTC", "direction": "long", "period": "day", "period_start": T0.isoformat(),
                                           "level_key": f"day:{T0.isoformat()}", "level": 100.025, "limit_price": 100.025, "stop_loss": 99.8,
                                           "take_profit": None, "rr": None, "atr": 0.5, "expires_at": (stamp + pd.Timedelta(days=3)).isoformat()},
                                          stamp.isoformat())
        start = stamp.floor("5min") + poc.BAR
        move = candles([(106.0, 100.0, 100.2), (100.2, 99.0, 99.2)] + [(99.3, 99.1, 99.2)] * 30, start)
        self.m5 = pd.concat([self.m5[self.m5["timestamp"] < start], move], ignore_index=True)
        with mock.patch.object(config, "POC_RADAR_ENABLED", False):
            self.run_(minutes_later=10)
            g = self.signals()[0]
            self.assertIsNone(g["take_profit"])
            self.assertIn("doel kies je zelf", self.titles("POC-radar gevuld")[0]["body"])
            self.assertTrue(level_check._self_measured(g))
            self.run_(minutes_later=60)
        trade = next(t for t in repo.list_open_poc_radar_trades() + [None] if t) if repo.list_open_poc_radar_trades() else None
        self.assertIsNone(trade)                                          # de stop werd geraakt: de meting is klaar
        g = repo.get_signal(g["id"])
        self.assertEqual(g["auto_outcome"], "stop_loss")
        self.assertAlmostEqual(repo.get_trade_result(g["id"])["r_value"], -1.0)
        self.assertEqual(repo.get_poc_radar_setup(sid)["signal_id"], g["id"])

    def test_met_doel_beslist_level_check(self):
        self.assertFalse(level_check._self_measured({"trade_type": "poc_radar", "take_profit": 110.0}))


class SamenvalTest(EngineCase):
    def test_niet_gemeten_tegenover_ja_en_nee(self):
        self.assertIsNone(live.samenval("BTC", 100.0, self.now))
        self.run_()
        self.assertTrue(live.samenval("BTC", 100.2, self.now))
        self.assertFalse(live.samenval("BTC", 103.0, self.now))


class MigrationTest(unittest.TestCase):
    def test_oude_database_krijgt_poc_kolommen_en_tabellen(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "oud.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE zone_radar_setups (id INTEGER PRIMARY KEY, coin TEXT, direction TEXT, zone_key TEXT, state TEXT)")
        conn.execute("CREATE TABLE zone_sweep_setups (id INTEGER PRIMARY KEY, coin TEXT, direction TEXT, zone_key TEXT, state TEXT)")
        conn.commit()
        conn.close()
        with mock.patch.object(config, "DATABASE_PATH", path):
            db.init_db()
            db.init_db()                      # idempotent
            with db.session() as c:
                for table in ("zone_radar_setups", "zone_sweep_setups"):
                    self.assertIn("poc_near", {r["name"] for r in c.execute(f"PRAGMA table_info({table})")})
                tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"poc_levels", "poc_scans", "poc_radar_setups", "poc_radar_trades"} <= tables)


if __name__ == "__main__":
    unittest.main()
