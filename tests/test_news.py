import json
import unittest

from app import news, repo
from tests.test_samenval import DbCase

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Binance lists FOO</title><link>https://x/1</link><pubDate>Tue, 06 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Opinion: BTC to the moon</title><link>https://x/2</link><pubDate>Tue, 06 Oct 2026 08:05:00 GMT</pubDate></item>
<item><title></title><link>https://x/3</link></item></channel></rss>"""
BINANCE = json.dumps({"data": {"catalogs": [{"articles": [{"code": "abc123", "title": "Binance will list SOL", "releaseDate": 1790000000000}]}]}}).encode()


def fake_http(url):
    if "binance.com" in url:
        return BINANCE
    if "coindesk" in url:
        return RSS
    raise OSError("onbereikbaar")


class ParseTest(unittest.TestCase):
    def test_rss_skips_items_without_title_and_parses_time(self):
        items = news.parse_rss(RSS)
        self.assertEqual([i["url"] for i in items], ["https://x/1", "https://x/2"])
        self.assertTrue(items[0]["at"].startswith("2026-10-06T08:00:00"))

    def test_binance_articles_get_link(self):
        items = news.parse_binance(json.loads(BINANCE))
        self.assertEqual(items[0]["url"], "https://www.binance.com/en/support/announcement/abc123")

    def test_unreachable_sources_are_skipped(self):
        got = news.fetch_all(fake_http)
        self.assertEqual({i["source"] for i in got}, {"CoinDesk", "Binance"})

    def test_clean_coins_keeps_only_tracked_and_alles(self):
        self.assertEqual(news.clean_coins("btc, FOO, eth"), "BTC,ETH")
        self.assertEqual(news.clean_coins("BTC,ALLES"), "ALLES")
        self.assertEqual(news.clean_coins(""), "")


class RunTest(DbCase):
    def verdicts(self, items):
        out = []
        for i, it in enumerate(items):
            if "SOL" in it["title"]:
                out.append({"n": i, "coins": "SOL", "direction": "long", "impact": "hoog", "summary": "Binance lijst SOL."})
            else:
                out.append({"n": i, "coins": "BTC", "direction": "neutraal", "impact": "laag", "summary": "Mening."})
        return out

    def test_keeps_relevant_only_dedupes_and_survives_classifier_failure(self):
        self.assertEqual(news.run(fake_http, self.verdicts), 1)
        events = repo.list_recent_events("SOL", "2000-01-01")
        self.assertEqual([e["impact"] for e in events], ["hoog"])
        self.assertEqual(repo.list_recent_events("BTC", "2000-01-01"), [])       # laag-impact bewaard zonder coin
        calls = []
        self.assertEqual(news.run(fake_http, lambda items: calls.append(items) or []), 0)
        self.assertEqual(calls, [])                                              # niets nieuws: classifier niet aangeroepen

    def test_classifier_error_stores_nothing_so_next_run_retries(self):
        def boom(items):
            raise RuntimeError("api weg")
        self.assertEqual(news.run(fake_http, boom), 0)
        self.assertEqual(news.run(fake_http, self.verdicts), 1)


if __name__ == "__main__":
    unittest.main()
