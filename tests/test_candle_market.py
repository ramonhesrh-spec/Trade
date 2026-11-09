"""De candlebron (app/candle_source.py en app/exchange.py): Binance USDⓈ-M perpetuals als standaard, spot als terugval per coin of met
CANDLE_MARKET=spot. Een 1000-contract (1000PEPE) wordt omgerekend naar de prijs per munt. Elke nieuwe kaart en elk nieuw signaal bewaart de
markt in candle_market; het detailblad toont hem. Geen netwerk: de ccxt-klassen zijn nagebootst."""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from app import candle_source, config, db, exchange, repo

PERP_MARKETS = {"BTC/USDT:USDT": {}, "1000PEPE/USDT:USDT": {}, "ETH/USDT:USDT": {}}
SPOT_MARKETS = {"BTC/USDT": {}, "PEPE/USDT": {}, "ETH/USDT": {}, "NOPERP/USDT": {}}


class FakeExchange:
    calls: list = []

    def __init__(self, markets, ident, rows=None):
        self.markets, self.id, self.rows = markets, ident, rows or {}

    def load_markets(self):
        return self.markets

    def fetch_ohlcv(self, symbol, timeframe="1h", limit=200, since=None):
        FakeExchange.calls.append((self.id, symbol, timeframe, limit, since))
        return self.rows.get(symbol, [[1_700_000_000_000, 10.0, 12.0, 9.0, 11.0, 5.0]])

    def fetch_ticker(self, symbol):
        FakeExchange.calls.append((self.id, symbol, "ticker"))
        return {"last": 0.012 if symbol.startswith("1000") else 50.0, "quoteVolume": 1234.0}


def fake_ccxt(perp_rows=None):
    return {"binanceusdm": lambda opts: FakeExchange(PERP_MARKETS, "binanceusdm", perp_rows),
            "binance": lambda opts: FakeExchange(SPOT_MARKETS, "binance")}


class Base(unittest.TestCase):
    def setUp(self):
        FakeExchange.calls = []
        exchange.reset()
        self.addCleanup(exchange.reset)
        p = mock.patch.object(config, "EXCHANGE_ID", "binance")
        p.start()
        self.addCleanup(p.stop)

    def use(self, market, perp_rows=None):
        classes = fake_ccxt(perp_rows)
        for p in (mock.patch.object(config, "CANDLE_MARKET", market),
                  mock.patch.object(exchange, "_ccxt_class", side_effect=lambda ident: classes[ident])):
            p.start()
            self.addCleanup(p.stop)


class SymbolMapTests(unittest.TestCase):
    def test_gewone_coin_is_het_perpcontract(self):
        self.assertEqual(candle_source.pick_perp("BTC", PERP_MARKETS), candle_source.Source("perp", "BTC/USDT:USDT", 1))

    def test_1000_contract_met_schaal(self):
        self.assertEqual(candle_source.pick_perp("PEPE", PERP_MARKETS), candle_source.Source("perp", "1000PEPE/USDT:USDT", 1000))

    def test_bekende_1000_contracten_staan_in_de_kaart(self):
        for coin in ("PEPE", "SHIB", "BONK", "FLOKI"):
            self.assertTrue(candle_source.PERP_ALIASES[coin].startswith("1000"), coin)

    def test_onbekend_1000_contract_wordt_herkend_aan_de_markten(self):
        self.assertEqual(candle_source.pick_perp("XYZ", {"1000XYZ/USDT:USDT": {}}), candle_source.Source("perp", "1000XYZ/USDT:USDT", 1000))

    def test_zonder_perp_geen_perpbron(self):
        self.assertIsNone(candle_source.pick_perp("NOPERP", PERP_MARKETS))

    def test_paarnaam_wordt_de_munt(self):
        self.assertEqual(candle_source.base_of("btc/usdt"), "BTC")
        self.assertEqual(candle_source.base_of("ETH/USDT:USDT"), "ETH")

    def test_label(self):
        self.assertEqual(candle_source.label("perp"), "Binance perps")
        self.assertEqual(candle_source.label("spot"), "Binance spot")
        self.assertIsNone(candle_source.label(None))

    def test_perp_alleen_bij_binance(self):
        with mock.patch.object(config, "CANDLE_MARKET", "perp"), mock.patch.object(config, "EXCHANGE_ID", "kraken"):
            self.assertEqual(candle_source.configured(), "spot")
        with mock.patch.object(config, "CANDLE_MARKET", "perp"), mock.patch.object(config, "EXCHANGE_ID", "binance"):
            self.assertEqual(candle_source.configured(), "perp")
        with mock.patch.object(config, "CANDLE_MARKET", "onzin"), mock.patch.object(config, "EXCHANGE_ID", "binance"):
            self.assertEqual(candle_source.configured(), "perp")


class FetchTests(Base):
    def test_standaard_haalt_perps(self):
        self.use("perp")
        df = exchange.fetch_ohlcv("BTC", timeframe="1h", limit=50)
        self.assertEqual(FakeExchange.calls, [("binanceusdm", "BTC/USDT:USDT", "1h", 50, None)])
        self.assertEqual(float(df["close"].iloc[0]), 11.0)
        self.assertEqual(candle_source.market_of("BTC"), "perp")

    def test_since_en_limit_gaan_mee(self):
        self.use("perp")
        exchange.fetch_ohlcv("ETH", "5m", 1000, 1_700_000_000_000)
        self.assertEqual(FakeExchange.calls, [("binanceusdm", "ETH/USDT:USDT", "5m", 1000, 1_700_000_000_000)])

    def test_1000_contract_wordt_prijs_per_munt(self):
        self.use("perp", {"1000PEPE/USDT:USDT": [[1_700_000_000_000, 0.012, 0.013, 0.011, 0.0125, 7.0]]})
        df = exchange.fetch_ohlcv("PEPE", timeframe="1h")
        self.assertEqual(FakeExchange.calls[0][1], "1000PEPE/USDT:USDT")
        self.assertAlmostEqual(float(df["open"].iloc[0]), 0.000012)
        self.assertAlmostEqual(float(df["high"].iloc[0]), 0.000013)
        self.assertAlmostEqual(float(df["low"].iloc[0]), 0.000011)
        self.assertAlmostEqual(float(df["close"].iloc[0]), 0.0000125)
        self.assertAlmostEqual(float(df["volume"].iloc[0]), 7000.0)       # contracten van 1000 munten -> munten
        self.assertAlmostEqual(exchange.fetch_last_price("PEPE"), 0.000012)
        self.assertEqual(exchange.fetch_24h_quote_volume("PEPE"), 1234.0)    # in USDT, geen schaal

    def test_coin_zonder_perp_valt_terug_op_spot(self):
        self.use("perp")
        exchange.fetch_ohlcv("NOPERP", timeframe="1h")
        self.assertEqual(FakeExchange.calls[0][:2], ("binance", "NOPERP/USDT"))
        self.assertEqual(candle_source.market_of("NOPERP"), "spot")

    def test_spot_als_terugval_voor_alles(self):
        self.use("spot")
        exchange.fetch_ohlcv("PEPE", timeframe="1h")
        self.assertEqual(FakeExchange.calls[0][:2], ("binance", "PEPE/USDT"))
        self.assertEqual(candle_source.market_of("PEPE"), "spot")
        self.assertEqual(exchange.fetch_last_price("BTC"), 50.0)

    def test_paarnaam_als_invoer(self):
        self.use("perp")
        exchange.fetch_ohlcv("BTC/USDT", "4h", 10)
        self.assertEqual(FakeExchange.calls[0][1], "BTC/USDT:USDT")

    def test_markt_bestaat(self):
        self.use("perp")
        self.assertTrue(exchange.market_exists("PEPE"))
        self.assertTrue(exchange.market_exists("NOPERP"))           # via spot
        self.assertFalse(exchange.market_exists("NERGENS"))

    def test_stroomkaart_voor_de_browser(self):
        self.use("perp")
        exchange.fetch_ohlcv("NOPERP", "1h")
        streams = candle_source.stream_map()
        self.assertEqual(streams["PEPE"], ["1000PEPEUSDT", 1000, "perp"])
        self.assertEqual(streams["NOPERP"], ["NOPERPUSDT", 1, "spot"])
        self.assertNotIn("BTC", streams)                            # gewone coins volgen de standaard


class StorageTests(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "c.db"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_migratie_op_oude_database(self):
        conn = sqlite3.connect(config.DATABASE_PATH)
        conn.execute("CREATE TABLE zone_radar_setups (id INTEGER PRIMARY KEY, coin TEXT, direction TEXT, tf TEXT, zone_key TEXT, zone_low REAL,"
                     " zone_high REAL, stop_loss REAL, take_profit REAL, rr REAL, atr REAL, target_tf TEXT, target_low REAL, target_high REAL,"
                     " state TEXT NOT NULL DEFAULT 'waiting', alert_sent INTEGER NOT NULL DEFAULT 0, signal_id INTEGER, created_at TEXT NOT NULL,"
                     " filled_at TEXT, closed_at TEXT, UNIQUE (coin, zone_key))")
        conn.execute("INSERT INTO zone_radar_setups (coin, direction, created_at) VALUES ('BTC', 'long', '2026-10-01T00:00:00+00:00')")
        conn.commit()
        conn.close()
        db.init_db()
        db.init_db()                                                 # idempotent
        tables = ("signals", "structure_setups", "range_sweep_setups", "zone_radar_setups", "zone_sweep_setups", "poc_radar_setups")
        with db.session() as c:
            for t in tables:
                self.assertIn("candle_market", {r["name"] for r in c.execute(f"PRAGMA table_info({t})")}, t)
            old = c.execute("SELECT candle_market FROM zone_radar_setups WHERE coin = 'BTC'").fetchone()
        self.assertIsNone(old["candle_market"])                     # historie blijft zoals hij was

    def test_nieuwe_rijen_krijgen_de_markt(self):
        db.init_db()
        with mock.patch.object(config, "CANDLE_MARKET", "perp"):
            sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "day_trading", "confidence": "laag", "technical_confirmed": 0, "hard_gates_ok": 1})
            candle_source.note("NOPERP", "spot")
            spot_id = repo.insert_signal({"coin": "NOPERP", "direction": "long", "category": "day_trading", "confidence": "laag", "technical_confirmed": 0, "hard_gates_ok": 1}, chain_it=False)
        with db.session() as c:
            rows = {r["id"]: r["candle_market"] for r in c.execute("SELECT id, candle_market FROM signals")}
        self.assertEqual(rows, {sid: "perp", spot_id: "spot"})


class EngineTests(unittest.TestCase):
    """De zone-radar schrijft de markt van zijn candles op de kaart en op het signaal van de vulling."""

    def setUp(self):
        from tests import test_zone_radar as tz
        self.case = tz.LiveTests("test_dagcap_op_nieuwe_kaarten")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        exchange.reset()
        self.addCleanup(exchange.reset)

    def test_kaart_en_vulling_bewaren_de_markt(self):
        import pandas as pd
        case = self.case
        original = case.fetch

        def fetch(coin, timeframe="1h", limit=200, since=None):
            candle_source.note(coin, "spot")                     # zoals exchange.fetch_ohlcv bij een coin zonder perp
            return original(coin, timeframe, limit, since)

        case.fetch = fetch
        case.run_once()
        cards = repo.list_zone_radar_setups()
        self.assertTrue(cards)
        self.assertEqual({c["candle_market"] for c in cards}, {"spot"})
        from tests.test_zone_radar import frame
        later = case.now + pd.Timedelta(hours=1)
        case.m5 = frame([(105.0, 105.0, 104.0, 104.5)], start=later, step=pd.Timedelta(minutes=5))
        case.now = later + pd.Timedelta(minutes=10)
        case.run_once()
        with db.session() as c:
            markets = [r["candle_market"] for r in c.execute("SELECT candle_market FROM signals")]
        self.assertEqual(markets, ["spot"])


class SheetTests(unittest.TestCase):
    def setUp(self):
        from tests.test_web_zone_sweep import WebZoneSweepTests
        self.case = WebZoneSweepTests("test_kaart_zonder_doel")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def sheet(self, sid):
        return self.case.client.get("/smc").text.split(f'data-kd-item="zsweep:{sid}"')[1].split("</section>")[0]

    def test_detailblad_toont_de_bron(self):
        sid = self.case.add_card(candle_market="perp")
        self.assertIn("Bron: Binance perps", self.sheet(sid))

    def test_terugval_heet_spot(self):
        sid = self.case.add_card(candle_market="spot")
        self.assertIn("Bron: Binance spot", self.sheet(sid))

    def test_oude_kaart_zonder_bron_toont_niets(self):
        sid = self.case.add_card()
        with db.session() as c:
            c.execute("UPDATE zone_sweep_setups SET candle_market = NULL WHERE id = ?", (sid,))
        self.assertNotIn("Bron:", self.sheet(sid))


if __name__ == "__main__":
    unittest.main()


class LiveMetaTests(unittest.TestCase):
    def setUp(self):
        from tests.test_web_zone_sweep import WebZoneSweepTests
        self.case = WebZoneSweepTests("test_kaart_zonder_doel")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_browserstroom_volgt_de_markt(self):
        import html
        import json
        import re
        with mock.patch.object(config, "CANDLE_MARKET", "perp"), mock.patch.object(config, "EXCHANGE_ID", "binance"):
            text = self.case.client.get("/smc").text
        self.assertIn('<meta name="live-market" content="perp">', text)
        raw = re.search(r'<meta name="live-symbols" content="([^"]*)">', text).group(1)
        self.assertEqual(json.loads(html.unescape(raw))["PEPE"], ["1000PEPEUSDT", 1000, "perp"])
        with mock.patch.object(config, "CANDLE_MARKET", "spot"):
            self.assertIn('<meta name="live-market" content="spot">', self.case.client.get("/smc").text)
