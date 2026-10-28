"""De marktcontext op de pagina's: het blok Context op Radar-kaart en kanspagina, Marktcontext op Vandaag en de funding-tabel op Bewijs.
Alleen gemeten waarden, met bron en leeftijd; zonder meting geen regel."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from app import zone_radar_live


def card(**kw):
    row = {"coin": "SOL", "direction": "long", "tf": "1h", "zone_key": "1h:bull:x", "zone_low": 95.0, "zone_high": 97.0, "stop_loss": 94.0,
           "take_profit": 105.0, "rr": 2.7, "atr": 1.0, "target_tf": "4h", "target_low": 105.0, "target_high": 106.0}
    row.update(kw)
    return row


class WebMarketContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        db.init_db()
        from web import main
        main._price_cache.clear()
        self.client = TestClient(main.app)
        user_id = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(user_id))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()
        self.ohlcv = mock.patch.object(main.exchange, "fetch_ohlcv", side_effect=RuntimeError("geen netwerk"))
        self.ohlcv.start()
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.ohlcv.stop()
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def seed_context(self, coin="SOL"):
        at = (self.now - timedelta(minutes=4)).isoformat()
        repo.add_market_context([(coin, "binance", "funding_8h", 0.06, at), (coin, "binance", "oi_change_24h", 4.2, at),
                                 (coin, "hyperliquid", "funding_8h", 0.02, at)])

    def test_radar_card_shows_measured_context_with_source_and_age(self):
        repo.insert_zone_radar_setup(card(), self.now.isoformat())
        self.seed_context()
        text = self.client.get("/smc").text
        self.assertIn('class="kd-ctx"', text)                               # in het detailblad van de kaart
        self.assertIn("gemeten", text)
        self.assertIn("+0,060% per 8u", text)
        self.assertIn("longs betalen", text)
        self.assertIn("Binance en Hyperliquid wijken 0,040% af", text)
        self.assertIn("Binance · 4 min", text)
        self.assertIn(">hoog<", text)

    def test_no_measurement_no_block(self):
        repo.insert_zone_radar_setup(card(), self.now.isoformat())
        self.assertNotIn('class="kd-ctx"', self.client.get("/smc").text)
        self.assertNotIn("Marktcontext", self.client.get("/vandaag").text)

    def test_vandaag_shows_market_context(self):
        at = (self.now - timedelta(hours=2)).isoformat()
        repo.add_market_context([("markt", "alternative", "fear_greed", 38.0, at), ("markt", "alternative", "fear_greed_class", 1.0, at),
                                 ("markt", "defillama", "stablecoin_usd", 307.58e9, at), ("markt", "defillama", "stablecoin_change_7d", 2.33, at),
                                 ("BTC", "binance", "funding_8h", 0.01, at), ("BTC", "okx", "funding_8h", 0.008, at)])
        text = self.client.get("/vandaag").text
        self.assertIn("Marktcontext", text)
        self.assertIn("Fear and Greed", text)
        self.assertIn("angst", text)
        self.assertIn("$307,6 mld", text)
        self.assertIn("+2,33% in 7 dagen", text)
        self.assertIn("+0,010%", text)
        self.assertIn("+0,008%", text)
        self.assertNotIn("Bybit", text)                 # geen meting, geen rij

    def test_chance_page_shows_context_now_and_at_creation(self):
        self.seed_context()
        setup_id = repo.insert_zone_radar_setup(card(ctx_funding=-0.05, ctx_oi_change_24h=1.5, ctx_spread=0.01), self.now.isoformat())
        signal_id = repo.fill_zone_radar_setup(setup_id, zone_radar_live.signal_row({**card(), "id": setup_id}))
        text = self.client.get(f"/kans/{signal_id}").text
        self.assertIn('class="ctx"', text)
        self.assertIn("+0,060% per 8u", text)            # nu
        self.assertIn("Bij het ontstaan van de kaart", text)
        self.assertIn("-0,050% per 8u", text)            # de bewaarde stand
        self.assertIn("+1,5%", text)

    def test_bewijs_shows_funding_split(self):
        for i, (funding, outcome) in enumerate(((0.08, "take_profit"), (0.01, "stop_loss"))):
            setup_id = repo.insert_zone_radar_setup(card(zone_key=f"1h:bull:{i}", ctx_funding=funding), self.now.isoformat())
            signal_id = repo.fill_zone_radar_setup(setup_id, zone_radar_live.signal_row({**card(), "id": setup_id}))
            with db.session() as conn:
                conn.execute("UPDATE signals SET auto_outcome = ?, auto_outcome_at = ? WHERE id = ?", (outcome, self.now.isoformat(), signal_id))
        text = self.client.get("/bewijs").text
        self.assertIn("Funding bij het ontstaan", text)
        self.assertIn("Extreme funding", text)
        self.assertIn("Dit beschrijft wat er gebeurde en voorspelt niets", text)
        self.assertIn("0,05%", text)


if __name__ == "__main__":
    unittest.main()
