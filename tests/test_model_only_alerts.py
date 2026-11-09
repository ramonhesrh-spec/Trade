"""MODEL_ONLY_ALERTS (besluit CEO 2026-11-02): met het HesPulse-model aan sturen Structuur, Zone-radar, Zone-sweep en POC-radar geen enkele
melding meer (geen luide, geen stille push en geen rij op /meldingen); ze blijven kaarten en signalen maken. Zonder model, of met
MODEL_ONLY_ALERTS=false, blijft alles zoals het was. De standaard in productie: model aan, dus alleen het model meldt."""
import asyncio
import re
from pathlib import Path
from unittest import mock

from app import config, db, focus, poc_radar_live, push_notify, repo, structure_live, zone_radar_live, zone_sweep_live
from tests.test_samenval import DbCase

ROOT = Path(__file__).resolve().parent.parent
CARD = {"id": 1, "coin": "BTC", "direction": "long", "tf": "1h", "zone_low": 99.0, "zone_high": 100.0, "target_tf": "4h", "limit_price": 100.0,
        "stop_loss": 98.0, "take_profit": 104.0, "rr": 2.0, "target_text": "aanbodzone 4u", "period": "day", "period_start": "2026-10-30T00:00:00+00:00",
        "level": 100.0, "placed_at": None, "variant": "ZS_1H", "extreme": 98.5}


class Case(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        self.sent = []

        async def fake_push(user_id, title, body, url, silent=False, tag=None, badge=None):
            self.sent.append((user_id, title, silent))
        for p in (mock.patch.object(push_notify, "send_push", fake_push), mock.patch.object(push_notify, "is_quiet_now", return_value=False),
                  mock.patch.object(repo, "mark_zone_radar_alert_sent", return_value=True),
                  mock.patch.object(repo, "mark_zone_sweep_alert_sent", return_value=True),
                  mock.patch.object(repo, "mark_poc_radar_alert_sent", return_value=True),
                  mock.patch.object(zone_radar_live, "new_card_body", return_value="plan"),
                  mock.patch("app.zone_sweep.new_card_body", return_value="plan"), mock.patch("app.poc_radar.new_card_body", return_value="plan"),
                  mock.patch.object(config, "HESPULSE_MODEL_ENABLED", True)):
            p.start()
            self.addCleanup(p.stop)

    def notes(self):
        with db.session() as conn:
            return conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ?", (self.uid,)).fetchone()[0]

    def announce_all(self):
        asyncio.run(zone_radar_live._push_new_card(dict(CARD)))
        asyncio.run(zone_sweep_live._announce(dict(CARD)))
        asyncio.run(poc_radar_live._announce(dict(CARD)))
        asyncio.run(structure_live._push_all("BTC long", "plan", "/smc#structuur-1", "structuur-1", loud=False, coin="BTC", direction="long",
                                             new_card=True))
        asyncio.run(structure_live._push_all("Doel 1 geraakt", "stop naar de instap", "/kans/1", "trade-1", loud=True))


class GateTest(Case):
    def test_old_kinds_send_nothing_when_only_the_model_alerts(self):
        with mock.patch.object(config, "MODEL_ONLY_ALERTS", True):
            self.announce_all()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.notes(), 0)

    def test_without_model_only_everything_stays_as_it_was(self):
        with mock.patch.object(config, "MODEL_ONLY_ALERTS", False):
            self.announce_all()
        self.assertEqual(len(self.sent), 5)
        self.assertEqual(self.notes(), 4)          # vier nieuwe kaarten op /meldingen; de trade-update is alleen een push

    def test_the_model_itself_always_alerts(self):
        with mock.patch.object(config, "MODEL_ONLY_ALERTS", True):
            self.assertTrue(focus.alerts_on("hespulse_model"))
            self.assertFalse(focus.alerts_on("zone_radar"))
        with mock.patch.object(config, "HESPULSE_MODEL_ENABLED", False), mock.patch.object(config, "MODEL_ONLY_ALERTS", True):
            self.assertTrue(focus.alerts_on("zone_radar"))       # zonder model is er niets om op over te stappen

    def test_fills_of_old_kinds_skip_the_push(self):
        """Elke vulling van een oude soort heeft de poort: fanout met skip_push of geen kijkers voor de push."""
        for name in ("structure_live.py", "zone_radar_live.py"):
            self.assertIn("skip_push=not focus.alerts_on(", (ROOT / "app" / name).read_text())
        for name in ("zone_sweep_live.py", "poc_radar_live.py"):
            self.assertIn("for uid in uids if focus.alerts_on(TRADE_TYPE) else ()", (ROOT / "app" / name).read_text())


class DefaultTest(DbCase):
    def test_production_default_is_model_on_and_only_model_alerts(self):
        src = (ROOT / "app" / "config.py").read_text()
        self.assertRegex(src, r'HESPULSE_MODEL_ENABLED = _get\("HESPULSE_MODEL_ENABLED", "true"\)')
        self.assertRegex(src, r'MODEL_ONLY_ALERTS = _get\("MODEL_ONLY_ALERTS", "true" if HESPULSE_MODEL_ENABLED else "false"\)')
        env = (ROOT / ".env.example").read_text()
        self.assertTrue(re.search(r"^HESPULSE_MODEL_ENABLED=true$", env, re.M))

    def test_model_is_a_focus_kind(self):
        self.assertIn("hespulse_model", focus.FOCUS_TYPES)


class OnlyTheModelRuns(DbCase):
    """Besluit CEO 2026-11-02: "ik wil alle modellen weg, alleen het HesPulse-model". Met het model aan zoeken de vier oude motoren niets en
    vullen hun wachtende kaarten niet; de POC-niveaus blijven bijgewerkt omdat het model een naakte POC als doel neemt."""

    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(config, "HESPULSE_MODEL_ENABLED", True), mock.patch.object(config, "MODEL_ONLY_ALERTS", True),
                  mock.patch.object(repo, "list_coins", return_value=[{"symbol": "BTC"}])):
            p.start()
            self.addCleanup(p.stop)

    def test_de_vier_oude_motoren_zoeken_niet(self):
        for t in ("structuur", "structuur_c", "zone_radar", "zone_sweep", "poc_radar"):
            self.assertFalse(focus.engine_on(t), t)
        self.assertTrue(focus.engine_on("hespulse_model"))
        with mock.patch.object(zone_radar_live, "_scan") as zr_scan, mock.patch.object(zone_radar_live, "_track") as zr_track, \
                mock.patch.object(structure_live, "_discover") as discover, mock.patch.object(structure_live, "_track") as st_track, \
                mock.patch.object(structure_live, "_follow") as st_follow, mock.patch("app.digest.run") as brief, \
                mock.patch.object(zone_sweep_live, "_track_one") as zs_track, mock.patch.object(poc_radar_live, "_scan_coin") as poc_scan, \
                mock.patch.object(poc_radar_live, "refresh") as refresh, mock.patch.object(repo, "list_zone_sweep_setups", return_value=[{"coin": "BTC", "id": 1}]), \
                mock.patch.object(repo, "list_poc_radar_setups", return_value=[]):
            async def go():
                await zone_radar_live.run()
                await structure_live.run()
                await zone_sweep_live.scan()
                await zone_sweep_live.track()
                await poc_radar_live.scan()
                await poc_radar_live.track()
            asyncio.run(go())
        for m in (zr_scan, zr_track, discover, st_track, zs_track, poc_scan):
            m.assert_not_called()
        st_follow.assert_called_once()           # lopende Structuur-trades lopen af
        brief.assert_called_once()               # de dagbrief blijft
        refresh.assert_called_once()             # POC-niveaus voor het doel van het model
        self.assertEqual(repo.get_beat("zone_radar")["detail"], focus.OFF_DETAIL)

    def test_tegenvoorbeeld_zonder_model_zoeken_ze_zoals_eerst(self):
        with mock.patch.object(config, "HESPULSE_MODEL_ENABLED", False):
            for t in ("structuur", "zone_radar", "zone_sweep", "poc_radar"):
                self.assertTrue(focus.engine_on(t), t)
