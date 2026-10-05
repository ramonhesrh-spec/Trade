import importlib
import os
import unittest
from unittest import mock

from app import config, coinlist


class ExtraCoinsTest(unittest.TestCase):
    def reload_config(self, value):
        with mock.patch.dict(os.environ, {"EXTRA_COINS": value}):
            importlib.reload(config)
            return list(config.EXTRA_COINS), list(config.FIXED_COINS)

    def tearDown(self):
        importlib.reload(config)
        importlib.reload(coinlist)

    def test_extras_are_parsed_deduped_and_appended(self):
        extra, fixed = self.reload_config(" xrp, HBAR ,btc,")
        self.assertEqual(extra, ["XRP", "HBAR"])
        self.assertEqual(fixed[-2:], ["XRP", "HBAR"])
        self.assertEqual(fixed.count("BTC"), 1)

    def test_aliases_follow_fixed_coins_and_text_filter_sees_extra(self):
        self.reload_config("XRP,FOO")
        importlib.reload(coinlist)
        self.assertEqual(set(coinlist.COIN_NAME_ALIASES), set(config.FIXED_COINS))
        self.assertTrue(coinlist.message_mentions_tracked_coin("Ripple long entry"))
        self.assertTrue(coinlist.message_mentions_tracked_coin("foo breakout"))

    def test_default_is_unchanged(self):
        extra, fixed = self.reload_config("")
        self.assertEqual((extra, fixed), ([], config.BASE_COINS))


class ScanSkipsFourHourBlockTest(unittest.TestCase):
    def test_extra_coin_only_gets_smc_check(self):
        import asyncio
        from app import market_scanner, repo
        seen = {"smc": [], "ohlcv": []}

        async def fake_smc(coin):
            seen["smc"].append(coin)

        def fake_ohlcv(coin, *a, **k):
            seen["ohlcv"].append(coin)
            raise RuntimeError("stop hier")

        coins = [{"symbol": "BTC"}, {"symbol": "XRP"}]
        with mock.patch.object(config, "EXTRA_COINS", ["XRP"]), \
                mock.patch.object(market_scanner, "_run_smc_check", fake_smc), \
                mock.patch.object(market_scanner.exchange, "fetch_ohlcv", fake_ohlcv), \
                mock.patch.object(repo, "list_coins", lambda: coins), \
                mock.patch.object(repo, "is_market_scan_enabled", lambda: True):
            try:
                asyncio.run(market_scanner.scan_market())
            except Exception:
                pass
        self.assertIn("XRP", seen["smc"])
        self.assertNotIn("XRP", seen["ohlcv"])


if __name__ == "__main__":
    unittest.main()
