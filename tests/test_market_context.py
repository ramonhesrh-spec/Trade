"""Marktcontext (app/market_context.py): funding gelijk gemaakt naar procent per 8 uur, het verschil tussen beurzen, OI over 24 uur, de parsers op
echte API-antwoorden en de rustige teksten. Niets hiervan beslist iets; de tests bewaken dat de getallen kloppen en de woorden beschrijven."""
import unittest
from datetime import datetime, timedelta, timezone

from app import market_context as mc
from tests import market_context_fixtures as fx

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


class FundingMathTests(unittest.TestCase):
    def test_rate_per_interval_becomes_percent_per_8_hours(self):
        self.assertAlmostEqual(mc.per_8h_pct(0.0001, 8), 0.01)
        self.assertAlmostEqual(mc.per_8h_pct(0.0000125, 1), 0.01)       # Hyperliquid: per uur
        self.assertAlmostEqual(mc.per_8h_pct(0.0001, 4), 0.02)          # 4-uurs interval betaalt twee keer zo vaak
        self.assertIsNone(mc.per_8h_pct(0.0001, 0))

    def test_labels_use_fixed_thresholds(self):
        self.assertEqual(mc.funding_label(0.05), "hoog")
        self.assertEqual(mc.funding_label(0.049), None)
        self.assertEqual(mc.funding_label(0.01), None)                  # de gewone basis van 0,01% is niet hoog
        self.assertEqual(mc.funding_label(-0.03), "laag")
        self.assertEqual(mc.funding_label(None), None)
        self.assertTrue(mc.is_extreme(0.08))
        self.assertTrue(mc.is_extreme(-0.04))
        self.assertFalse(mc.is_extreme(0.0))
        self.assertFalse(mc.is_extreme(None))

    def test_funding_text_says_who_pays_and_nothing_more(self):
        self.assertEqual(mc.funding_text(0.03), "Funding +0,030% per 8u: longs betalen")
        self.assertEqual(mc.funding_text(-0.012), "Funding -0,012% per 8u: shorts betalen")
        self.assertEqual(mc.funding_text(0.0), "Funding 0,000% per 8u: niemand betaalt")
        for word in ("koop", "verkoop", "zal", "gaat"):
            self.assertNotIn(word, mc.funding_text(0.2).lower())

    def test_spread_against_binance(self):
        funding = {"binance": 0.01, "hyperliquid": 0.03, "bybit": 0.012, "okx": 0.008}
        self.assertEqual(mc.widest_spread(funding), ("hyperliquid", 0.02))
        self.assertIsNone(mc.widest_spread({"binance": 0.01}))
        self.assertIsNone(mc.widest_spread({"hyperliquid": 0.01, "okx": 0.02}))      # zonder Binance geen vergelijking
        self.assertEqual(mc.spread_text("hyperliquid", 0.02), "Binance en Hyperliquid wijken 0,020% af")

    def test_oi_change(self):
        self.assertAlmostEqual(mc.oi_change_pct(105.0, 100.0), 5.0)
        self.assertIsNone(mc.oi_change_pct(105.0, 0.0))
        self.assertIsNone(mc.oi_change_pct(None, 100.0))

    def test_value_24h_back_only_within_tolerance(self):
        series = [(ago(hours=25), 90.0), (ago(hours=24, minutes=10), 100.0), (ago(hours=1), 110.0)]
        self.assertEqual(mc.value_near(series, NOW - timedelta(hours=24)), 100.0)
        self.assertIsNone(mc.value_near([(ago(hours=3), 1.0)], NOW - timedelta(hours=24)))


class ParserTests(unittest.TestCase):
    def test_hyperliquid(self):
        out = mc.parse_hyperliquid(fx.HYPERLIQUID, ["BTC", "SOL", "PEPE", "XRP"])
        self.assertEqual(set(out), {"BTC", "SOL"})                     # kPEPE is een andere eenheid, XRP ontbreekt: geen gok
        self.assertAlmostEqual(out["BTC"]["funding_8h"], 0.01)
        self.assertAlmostEqual(out["BTC"]["oi_usd"], 28012.34 * 67410.0)
        self.assertEqual(out["BTC"]["mark"], 67410.0)
        self.assertEqual(out["BTC"]["oracle"], 67402.0)
        self.assertAlmostEqual(out["SOL"]["funding_8h"], -0.00248)

    def test_bybit_uses_its_interval(self):
        out = mc.parse_bybit(fx.BYBIT, ["BTC", "ETH", "SOL"])
        self.assertAlmostEqual(out["BTC"]["funding_8h"], 0.01)
        self.assertAlmostEqual(out["SOL"]["funding_8h"], -0.02)
        self.assertAlmostEqual(out["ETH"]["oi_usd"], 2460000000.0)

    def test_okx_interval_from_its_timestamps(self):
        self.assertAlmostEqual(mc.parse_okx(fx.OKX_BTC)["funding_8h"], 0.008)
        self.assertEqual(mc.parse_okx(fx.OKX_ERROR), {})

    def test_binance_premium_with_adjusted_interval(self):
        out = mc.parse_binance_premium(fx.BINANCE_PREMIUM, fx.BINANCE_FUNDING_INFO, ["BTC", "ETH", "SOL"])
        self.assertAlmostEqual(out["BTC"]["funding_8h"], 0.01)
        self.assertAlmostEqual(out["SOL"]["funding_8h"], 0.005)       # 4-uurs interval volgens fundingInfo
        self.assertAlmostEqual(out["ETH"]["mark"], 2430.5)
        self.assertAlmostEqual(mc.parse_binance_premium(fx.BINANCE_PREMIUM, None, ["SOL"])["SOL"]["funding_8h"], 0.0025)

    def test_binance_oi_history(self):
        out = mc.parse_binance_oi(fx.BINANCE_OI_HIST)
        self.assertEqual(out["oi_usd"], 5210000000.0)
        self.assertAlmostEqual(out["oi_change_24h"], 4.2)
        self.assertEqual(mc.parse_binance_oi([]), {})

    def test_fear_greed_and_stablecoins(self):
        self.assertEqual(mc.parse_fear_greed(fx.FEAR_GREED), {"fear_greed": 38.0, "fear_greed_class": 1.0})     # het eigen label van de bron
        self.assertEqual(mc.parse_fear_greed({"data": []}), {})
        out = mc.parse_stablecoins(fx.STABLECOINS)
        self.assertAlmostEqual(out["stablecoin_usd"], 307.58e9)
        self.assertAlmostEqual(out["stablecoin_change_7d"], 7e9 / 300.58e9 * 100)

    def test_rubbish_never_raises(self):
        for parse in (lambda r: mc.parse_hyperliquid(r, ["BTC"]), lambda r: mc.parse_bybit(r, ["BTC"]), mc.parse_okx,
                      lambda r: mc.parse_binance_premium(r, None, ["BTC"]), mc.parse_binance_oi, mc.parse_fear_greed, mc.parse_stablecoins):
            for raw in (None, {}, [], "html", [{"x": 1}], {"result": {"list": [{"symbol": "BTCUSDT", "fundingRate": "nan?"}]}}):
                self.assertIn(parse(raw), ({}, None))


def rows_for(coin: str, at: str) -> list[dict]:
    return [
        {"coin": coin, "bron": "binance", "metric": "funding_8h", "waarde": 0.06, "gemeten_op": at},
        {"coin": coin, "bron": "binance", "metric": "oi_change_24h", "waarde": 4.2, "gemeten_op": at},
        {"coin": coin, "bron": "hyperliquid", "metric": "funding_8h", "waarde": 0.02, "gemeten_op": at},
        {"coin": coin, "bron": "okx", "metric": "funding_8h", "waarde": 0.05, "gemeten_op": ago(hours=3)},
    ]


class DisplayTests(unittest.TestCase):
    def test_latest_keeps_the_newest_value_per_metric(self):
        rows = rows_for("BTC", ago(minutes=4)) + [{"coin": "BTC", "bron": "binance", "metric": "funding_8h", "waarde": 0.01, "gemeten_op": ago(hours=1)}]
        latest = mc.latest(rows)
        self.assertEqual(latest["BTC"]["binance"]["funding_8h"], (0.06, ago(minutes=4)))

    def test_coin_lines_are_measured_with_source_and_age(self):
        lines = mc.coin_lines(mc.latest(rows_for("BTC", ago(minutes=4)))["BTC"], NOW)
        by_label = {line["label"]: line for line in lines}
        self.assertEqual(by_label["Funding"]["value"], "+0,060% per 8u")
        self.assertEqual(by_label["Funding"]["note"], "longs betalen")
        self.assertEqual(by_label["Funding"]["flag"], "hoog")
        self.assertEqual(by_label["Funding"]["source"], "Binance")
        self.assertEqual(by_label["Funding"]["age"], "4 min")
        self.assertEqual(by_label["Verschil tussen beurzen"]["value"], "0,040%")
        self.assertEqual(by_label["Verschil tussen beurzen"]["note"], "Binance en Hyperliquid wijken 0,040% af")
        self.assertEqual(by_label["Open interest 24u"]["value"], "+4,2%")

    def test_missing_source_means_missing_line(self):
        self.assertEqual(mc.coin_lines({}, NOW), [])
        only_hl = {"hyperliquid": {"funding_8h": (0.01, ago(minutes=2))}}
        labels = [line["label"] for line in mc.coin_lines(only_hl, NOW)]
        self.assertEqual(labels, ["Funding"])

    def test_spread_ignores_an_old_venue(self):
        # OKX is drie uur oud: vergelijken met een verse Binance-waarde zou een verschil meten dat er nooit tegelijk was.
        latest = mc.latest([r for r in rows_for("BTC", ago(minutes=4)) if r["bron"] != "hyperliquid"])["BTC"]
        self.assertNotIn("Verschil tussen beurzen", [line["label"] for line in mc.coin_lines(latest, NOW)])

    def test_market_lines_for_today(self):
        rows = rows_for("BTC", ago(minutes=4)) + rows_for("ETH", ago(minutes=4)) + [
            {"coin": "markt", "bron": "alternative", "metric": "fear_greed", "waarde": 38.0, "gemeten_op": ago(hours=2)},
            {"coin": "markt", "bron": "alternative", "metric": "fear_greed_class", "waarde": 1.0, "gemeten_op": ago(hours=2)},
            {"coin": "markt", "bron": "defillama", "metric": "stablecoin_usd", "waarde": 307.58e9, "gemeten_op": ago(hours=2)},
            {"coin": "markt", "bron": "defillama", "metric": "stablecoin_change_7d", "waarde": 2.33, "gemeten_op": ago(hours=2)},
        ]
        view = mc.market_view(mc.latest(rows), NOW)
        lines = {line["label"]: line for line in view["lines"]}
        self.assertEqual(lines["Fear and Greed"]["value"], "38")
        self.assertEqual(lines["Fear and Greed"]["note"], "angst")
        self.assertEqual(lines["Stablecoin-voorraad"]["value"], "$307,6 mld")
        self.assertEqual(lines["Stablecoin-voorraad"]["note"], "+2,33% in 7 dagen")
        btc = next(f for f in view["funding"] if f["coin"] == "BTC")
        self.assertEqual([v["source"] for v in btc["venues"]], ["Binance", "Hyperliquid", "OKX"])
        self.assertEqual(btc["venues"][0]["value"], "+0,060%")
        table = view["table"]
        self.assertEqual(table["coins"], ["BTC", "ETH"])
        self.assertEqual([r["source"] for r in table["rows"]], ["Binance", "Hyperliquid", "OKX"])       # Bybit ontbreekt: geen rij
        self.assertEqual([c["value"] if c else None for c in table["rows"][0]["cells"]], ["+0,060%", "+0,060%"])
        self.assertEqual(table["rows"][0]["cells"][0]["flag"], "hoog")
        self.assertEqual(mc.market_view({}, NOW), {"lines": [], "funding": [], "table": None})

    def test_snapshot_only_fresh_values(self):
        latest = mc.latest(rows_for("BTC", ago(minutes=4)))["BTC"]
        self.assertEqual(mc.snapshot(latest, NOW), {"ctx_funding": 0.06, "ctx_oi_change_24h": 4.2, "ctx_spread": 0.04})
        stale = mc.latest(rows_for("BTC", ago(hours=2)))["BTC"]
        self.assertEqual(mc.snapshot(stale, NOW), {"ctx_funding": None, "ctx_oi_change_24h": None, "ctx_spread": None})

    def test_snapshot_lines_for_the_chance_page(self):
        lines = mc.snapshot_lines({"ctx_funding": 0.06, "ctx_oi_change_24h": None, "ctx_spread": -0.01})
        self.assertEqual([(line["label"], line["value"]) for line in lines], [("Funding", "+0,060% per 8u"), ("Verschil tussen beurzen", "0,010%")])
        self.assertEqual(mc.snapshot_lines({}), [])


if __name__ == "__main__":
    unittest.main()
