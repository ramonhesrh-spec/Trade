"""Onderdeel C: per kansmelding het slot van de candle, het moment van detectie en het moment van verzenden (tabel alert_timing), de telling per
soort voor scripts/vertraging.py, en de timer van de snelcyclus 20 s na elk 5m-slot."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import config, latency, push_notify, repo
from tests.test_samenval import DbCase

ROOT = Path(__file__).resolve().parent.parent
T = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class CandleMomentTest(unittest.TestCase):
    def test_a_closed_candle_counts_from_its_close(self):
        self.assertEqual(latency.candle_moment(T, T + timedelta(minutes=3)), T)

    def test_a_forming_candle_counts_from_the_last_five_minute_slot(self):
        # Een vulling in de candle die nog vormt: zijn slot ligt na de detectie, dus het laatste 5m-slot ervoor.
        self.assertEqual(latency.candle_moment(T + timedelta(minutes=15), T + timedelta(minutes=7, seconds=10)), T + timedelta(minutes=5))

    def test_without_a_candle_it_is_the_last_slot(self):
        self.assertEqual(latency.candle_moment(None, T + timedelta(minutes=4, seconds=59)), T)

    def test_timing_carries_iso_moments(self):
        t = latency.timing("zone_radar", "vulling", T, T + timedelta(seconds=200))
        self.assertEqual(t, {"trade_type": "zone_radar", "event": "vulling", "candle_at": T.isoformat(),
                             "detected_at": (T + timedelta(seconds=200)).isoformat()})


def row(trade_type, delay_s, detect_s=100):
    return {"trade_type": trade_type, "candle_at": T.isoformat(), "detected_at": (T + timedelta(seconds=detect_s)).isoformat(),
            "sent_at": (T + timedelta(seconds=delay_s)).isoformat(), "ok": 1}


class StatsTest(unittest.TestCase):
    def test_median_and_p90_from_candle_to_sent_per_type(self):
        rows = [row("zone_radar", s) for s in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)] + [row("structuur", 250)]
        s = latency.stats(rows)
        self.assertEqual(s["zone_radar"]["n"], 10)
        self.assertAlmostEqual(s["zone_radar"]["median_s"], 550)
        self.assertAlmostEqual(s["zone_radar"]["p90_s"], 910)
        self.assertAlmostEqual(s["zone_radar"]["detect_median_s"], 100)
        self.assertEqual(s["structuur"]["n"], 1)

    def test_a_failed_push_is_counted_apart(self):
        s = latency.stats([row("poc_radar", 200), {**row("poc_radar", 300), "ok": 0}])
        self.assertEqual((s["poc_radar"]["n"], s["poc_radar"]["failed"]), (1, 1))


class SendKansPushRecordsTimingTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.list_users()[0]["id"]

    def _send(self, result, **kw):
        async def fake(*a, **k):
            return result
        with mock.patch.object(push_notify, "send_push", fake):
            return asyncio.run(push_notify.send_kans_push(self.uid, "BTC", "long", "t", "b", "/smc#radar-zone-1",
                                                          timing=latency.timing("zone_radar", "nieuw", T, T + timedelta(seconds=190)), **kw))

    def test_a_sent_push_records_the_three_moments(self):
        self._send(None)
        rows = repo.list_alert_timings()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["trade_type"], r["event"], r["ok"], r["user_id"]), ("zone_radar", "nieuw", 1, self.uid))
        self.assertEqual(r["candle_at"], T.isoformat())
        self.assertIsNotNone(r["sent_at"])

    def test_a_failed_push_is_recorded_as_not_ok(self):
        self._send("1 van 1 apparaten mislukt")
        self.assertEqual(repo.list_alert_timings()[0]["ok"], 0)

    def test_a_refused_push_records_nothing(self):
        repo.set_push_pause(self.uid, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        self._send(None)
        self.assertEqual(repo.list_alert_timings(), [])

    def test_without_timing_nothing_is_recorded(self):
        async def fake(*a, **k):
            return None
        with mock.patch.object(push_notify, "send_push", fake):
            asyncio.run(push_notify.send_kans_push(self.uid, "BTC", "long", "t", "b", "/x"))
        self.assertEqual(repo.list_alert_timings(), [])


class EnginesPassTimingTest(DbCase):
    """Elke focus-motor geeft zijn momenten mee: een nieuwe kaart via send_new_card (stil, buiten het budget, CEO 2026-11-02), de vulling via
    send_kans_push."""

    def setUp(self):
        super().setUp()
        self.calls, self.loud = [], []

        async def fake_new(uid, coin, direction, title, body, url, **kw):
            self.calls.append(kw.get("timing"))

        async def fake_loud(uid, coin, direction, title, body, url, **kw):
            self.loud.append(kw.get("timing"))
            return True
        for p in (mock.patch.object(push_notify, "send_new_card", fake_new), mock.patch.object(push_notify, "send_kans_push", fake_loud)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.assertEqual(self.loud, [])              # een nieuwe kaart is nooit een luide push

    def test_zone_radar_new_card(self):
        from app import zone_radar_live
        card = {"id": 7, "coin": "BTC", "direction": "long", "tf": "1h", "zone_low": 99.0, "zone_high": 100.0, "stop_loss": 98.0,
                "take_profit": 104.0, "rr": 4.0, "target_tf": "1h", "created_at": T.isoformat()}
        with mock.patch.object(repo, "mark_zone_radar_alert_sent", lambda i: True):
            asyncio.run(zone_radar_live._push_new_card(card))
        self.assertEqual(self.calls[0]["trade_type"], "zone_radar")
        self.assertEqual(self.calls[0]["event"], "nieuw")

    def test_zone_sweep_new_card(self):
        from app import zone_sweep_live
        card = {"id": 3, "coin": "BTC", "direction": "long", "placed_at": T.isoformat(), "created_at": T.isoformat()}
        with mock.patch.object(repo, "mark_zone_sweep_alert_sent", lambda i: True), \
                mock.patch.object(zone_sweep_live.zsw, "new_card_body", lambda c: "x"), \
                mock.patch.object(zone_sweep_live, "viewers", lambda: [repo.list_users()[0]["id"]]):
            asyncio.run(zone_sweep_live._announce(card, T + timedelta(seconds=30)))
        self.assertEqual(self.calls[0], latency.timing("zone_sweep", "nieuw", T, T + timedelta(seconds=30)))

    def test_poc_radar_new_card(self):
        from app import poc_radar_live
        card = {"id": 4, "coin": "BTC", "direction": "short"}
        with mock.patch.object(repo, "mark_poc_radar_alert_sent", lambda i: True), \
                mock.patch.object(poc_radar_live.pr, "new_card_body", lambda c: "x"), \
                mock.patch.object(poc_radar_live, "viewers", lambda: [repo.list_users()[0]["id"]]):
            asyncio.run(poc_radar_live._announce(card, T + timedelta(minutes=2)))
        self.assertEqual(self.calls[0], latency.timing("poc_radar", "nieuw", None, T + timedelta(minutes=2)))

    def test_structure_push_all_passes_timing(self):
        from app import structure_live
        t = latency.timing("structuur", "nieuw", T, T + timedelta(seconds=40))
        asyncio.run(structure_live._push_all("t", "b", "/x", "tag", True, coin="BTC", direction="long", timing=t, new_card=True))
        self.assertEqual(self.calls[0], t)


class TimerAndReadmeTest(unittest.TestCase):
    def test_the_fast_cycle_starts_20_seconds_after_each_slot(self):
        text = (ROOT / "deploy/crypto-market-scan-smc.timer").read_text()
        self.assertIn("OnCalendar=*:0/5:20", text)
        self.assertNotIn("OnCalendar=*:3/5:00", text)

    def test_readme_says_how_to_reload_the_timer(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("sudo cp deploy/crypto-market-scan-smc.timer /etc/systemd/system/", text)
        self.assertIn("sudo systemctl restart crypto-market-scan-smc.timer", text)
        self.assertIn("scripts/vertraging.py", text)


if __name__ == "__main__":
    unittest.main()
