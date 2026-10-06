import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import config, db, liquidations, repo

T = 1790000000000  # ms


def msg(symbol="BTCUSDT", side="SELL", ap="100", z="2", t=T):
    return json.dumps({"e": "forceOrder", "o": {"s": symbol, "S": side, "ap": ap, "z": z, "T": t}})


class ParseTest(unittest.TestCase):
    def test_sell_is_long_liquidation_buy_is_short(self):
        coin, bucket, long_usd, short_usd = liquidations.parse_event(msg(side="SELL"), {"BTC"})
        self.assertEqual((coin, long_usd, short_usd), ("BTC", 200.0, 0.0))
        self.assertEqual(liquidations.parse_event(msg(side="BUY"), {"BTC"})[2:], (0.0, 200.0))

    def test_ignores_other_coins_bad_json_and_zero_size(self):
        self.assertIsNone(liquidations.parse_event(msg("XYZUSDT"), {"BTC"}))
        self.assertIsNone(liquidations.parse_event("{kapot", {"BTC"}))
        self.assertIsNone(liquidations.parse_event(msg(z="0"), {"BTC"}))
        self.assertIsNone(liquidations.parse_event(msg("BTCUSD_PERP"), {"BTC"}))

    def test_bucket_is_five_minute_floor(self):
        b = liquidations.bucket_of(T)
        self.assertEqual(int(b[14:16]) % 5, 0)
        self.assertEqual(liquidations.bucket_of(T + 4 * 60 * 1000 - (T % 300000)), liquidations.bucket_of(T - (T % 300000)))


class StoreTest(unittest.TestCase):
    def test_aggregates_and_accumulates_across_flushes(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "DATABASE_PATH", str(Path(tmp) / "t.db")):
            db.init_db()
            agg = liquidations.Aggregator()
            for m in (msg(side="SELL"), msg(side="SELL"), msg(side="BUY", ap="50")):
                agg.add(liquidations.parse_event(m, {"BTC"}))
            repo.add_liquidations(agg.drain())
            self.assertEqual(agg.drain(), [])
            agg.add(liquidations.parse_event(msg(side="SELL"), {"BTC"}))
            repo.add_liquidations(agg.drain())
            rows = repo.list_liquidations("BTC", "2000-01-01")
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["long_usd"], rows[0]["short_usd"], rows[0]["n"]), (600.0, 100.0, 4))


if __name__ == "__main__":
    unittest.main()
