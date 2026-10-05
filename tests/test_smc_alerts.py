import asyncio
import os
import tempfile
import unittest
from unittest import mock

from app import config, db, market_scanner, repo, security

SETUP = {"direction": "long", "zone_low": 99.0, "zone_high": 100.0, "liquidity_target": 110.0}


class SmcBodyTests(unittest.TestCase):
    def test_limietorder_staat_voorop_met_rr_vanaf_die_prijs(self):
        body = market_scanner.format_smc_body(SETUP, 101.0, 97.0, 106.0, None, None)
        first = body.splitlines()[0]
        self.assertTrue(first.startswith("Limietorder 100.0000 op de zone-rand"))
        self.assertIn("R:R 2.0", first)               # risico 3, winst 6 vanaf 100
        self.assertIn("Entry 101.0000", body)
        self.assertIn("Zone 99.0000-100.0000", body)
        self.assertNotIn("Sniper", body)

    def test_sniper_regel_blijft_en_ongeldig_plan_geeft_geen_limietregel(self):
        body = market_scanner.format_smc_body(SETUP, 101.0, 97.0, 106.0, 98.5, "stop-hunt")
        self.assertIn("🎯 Sniper: 98.5000 — stop-hunt", body)
        bad = market_scanner.format_smc_body(SETUP, 101.0, 100.5, 106.0, None, None)   # stop boven de limiet
        self.assertNotIn("Limietorder", bad)
        self.assertIn("Entry 101.0000", bad)


class ZoneTouchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "z.db"))
        self.patch.start()
        db.init_db()
        for name in ("a", "b"):
            repo.create_user(name, security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        with db.session() as conn:
            for coin in ("XRP", "ETH"):
                conn.execute(
                    """INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                       created_at, updated_at) VALUES (?, 'long', 99.0, 100.0, 101.0, 98.0, 110.0, 1.0, ?, ?)""",
                    (coin, db.now_iso(), db.now_iso()))
        self.push = mock.patch.object(market_scanner.push_notify, "send_push", new=mock.AsyncMock())
        self.send = self.push.start()
        self.quiet = mock.patch.object(market_scanner.push_notify, "is_quiet_now", return_value=False)
        self.quiet.start()

    def tearDown(self):
        self.quiet.stop()
        self.push.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def run_touch(self, coin, price):
        with mock.patch.object(market_scanner.exchange, "fetch_last_price", return_value=price):
            asyncio.run(market_scanner._notify_zone_touches(coin))

    def flag(self, coin):
        with db.session() as conn:
            return conn.execute("SELECT zone_alert_sent FROM smc_setups WHERE coin = ?", (coin,)).fetchone()[0]

    def test_melding_zodra_de_koers_in_de_zone_staat_en_maar_een_keer(self):
        self.run_touch("XRP", 99.5)
        self.assertEqual(self.send.await_count, 2)                     # twee gebruikers
        title, body = self.send.await_args_list[0].args[1], self.send.await_args_list[0].args[2]
        self.assertIn("XRP long: koers in de zone", title)
        self.assertIn("limietorder op 100.0000", body)
        self.assertIn("R:R", body)
        self.assertEqual(self.flag("XRP"), 1)
        self.assertEqual(self.flag("ETH"), 0)                           # andere coin ongemoeid
        self.run_touch("XRP", 99.5)
        self.assertEqual(self.send.await_count, 2)                     # geen tweede melding

    def test_geen_melding_buiten_de_zone_of_voorbij_de_stop(self):
        self.run_touch("XRP", 102.0)                                    # wacht
        self.run_touch("XRP", 96.0)                                     # voorbij de stop
        self.assertEqual(self.send.await_count, 0)
        self.assertEqual(self.flag("XRP"), 0)

    def test_mislukte_koers_laat_de_setup_open(self):
        with mock.patch.object(market_scanner.exchange, "fetch_last_price", side_effect=RuntimeError("storing")):
            asyncio.run(market_scanner._notify_zone_touches("XRP"))
        self.assertEqual(self.send.await_count, 0)
        self.assertEqual(self.flag("XRP"), 0)

    def test_een_mislukte_push_blokkeert_de_andere_gebruiker_niet(self):
        self.send.side_effect = [RuntimeError("push stuk"), None]
        self.run_touch("XRP", 99.5)
        self.assertEqual(self.send.await_count, 2)
        self.assertEqual(self.flag("XRP"), 1)


if __name__ == "__main__":
    unittest.main()
