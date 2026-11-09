import json
import unittest

from app import chain, trust


class TrustTest(unittest.TestCase):
    def test_status_needs_fifty_trades_and_a_positive_average_to_be_proven(self):
        self.assertEqual(trust.status(None)["state"], "proef")
        self.assertIn("Te weinig", trust.status({"resolved": 4, "wins": 3, "avg_net": 0.5})["text"])        # 3 van 4 zegt niets
        self.assertEqual(trust.status({"resolved": 49, "wins": 40, "avg_net": 1.0})["state"], "proef")
        self.assertEqual(trust.status({"resolved": 50, "wins": 30, "avg_net": 0.1})["state"], "bewezen")
        self.assertEqual(trust.status({"resolved": 80, "wins": 20, "avg_net": -0.2})["state"], "negatief")
        self.assertEqual(trust.status({"resolved": 50, "wins": 25, "avg_net": 0.0})["state"], "negatief")   # nul netto is niet bewezen

    def test_text_shows_counts_and_net_r(self):
        text = trust.status({"resolved": 12, "wins": 7, "avg_net": 0.25})["text"]
        self.assertIn("12 trades", text)
        self.assertIn("netto +3.0R", text)
        self.assertIn("Nog 38 trades", text)


class ChainTest(unittest.TestCase):
    def rows(self, n=3):
        out, prev = [], None
        for i in range(1, n + 1):
            body = chain.payload({"id": i, "created_at": f"2026-10-0{i}T10:00:00+00:00", "coin": "BTC", "direction": "short", "trade_type": "rejectie",
                                  "price": 100.0, "stop_loss": 101.0, "take_profit": 98.0})
            h = chain.link(prev, body)
            out.append({"signal_id": i, "prev": prev, "payload": body, "hash": h})
            prev = h
        return out

    def test_untouched_chain_verifies(self):
        self.assertEqual(chain.verify(self.rows()), (True, None))
        self.assertEqual(chain.verify([]), (True, None))

    def test_changed_plan_missing_or_inserted_signal_breaks_it(self):
        rows = self.rows()
        rows[1] = {**rows[1], "payload": rows[1]["payload"].replace("98.0", "90.0")}
        self.assertEqual(chain.verify(rows), (False, 2))
        self.assertEqual(chain.verify([self.rows()[0], self.rows()[2]]), (False, 3))     # signaal 2 weggelaten

    def test_payload_is_stable_text(self):
        body = chain.payload({"id": 1, "created_at": "x", "coin": "BTC", "direction": "long", "trade_type": "smc", "price": 1.5, "stop_loss": 1.0, "take_profit": 2.0, "extra": 9})
        self.assertNotIn("extra", body)                                      # alleen de vaste velden
        self.assertEqual(list(json.loads(body)), sorted(json.loads(body)))


if __name__ == "__main__":
    unittest.main()
