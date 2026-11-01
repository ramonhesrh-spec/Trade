"""Onderdeel D: een kaart die eindigt zonder vulling zegt waarom (app/end_reason.py, overal waar hij nog staat), 'volgorde onbekend' is zichtbaar
op Bewijs en in Logboek en replay, en de melding 'terug bij niveau' (level_check.check_pending_signals) volgt het patroon van check_open_trades."""
import asyncio
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from app import db, end_reason, level_check, logbook, repo, trade_replay, track_record
from tests.test_samenval import DbCase
from tests.test_web_focus import Base, signal
from tests.test_web_nu import zone

ROOT = Path(__file__).resolve().parent.parent
LIVE = ("waiting", "filled", "fired", "oordeel")       # nog open of gevuld: geen einde zonder vulling


def _source_states() -> dict[str, set]:
    """Elke stand die de code op een kaart zet, gelezen uit de bron, zodat een nieuwe stand zonder tekst deze test laat falen."""
    text = {p.name: p.read_text() for p in (ROOT / "app").glob("*.py")}
    found = {"zone_radar": set(), "zone_sweep": set(), "poc_radar": set(), "structuur": set()}
    for src in text.values():
        for kind in ("zone_radar", "zone_sweep", "poc_radar"):
            found[kind] |= set(re.findall(rf'end_{kind}_setup\([^,]+,\s*"(\w+)"', src))
        found["structuur"] |= set(re.findall(r'set_structure_state\([^,]+,\s*"(\w+)"', src))
        found["structuur"] |= set(re.findall(r'update_structure_judgement\([^,]+,[^,]+,[^,]+,\s*"(\w+)"', src))
        found["structuur"] |= set(re.findall(r'"state":\s*"(\w+)"', src)) & {"geen_plan", "oordeel", "schaduw"}
    found["structuur"] |= set(re.findall(r"UPDATE structure_setups SET state = '(\w+)'", (ROOT / "app/repo.py").read_text()))
    from app import range_sweep_live, trade_plan, today
    found["zone_sweep"] |= set(range_sweep_live.CANCEL_STATE.values())
    shown = set(trade_plan.STATE_LABELS) - {"wacht", "in_zone"}       # standen op een kaart die de motor nog niet omzette
    for kind in found:
        found[kind] |= shown
    found["structuur"].add("verlopen")                                  # today.structure_state
    return {k: v - set(LIVE) for k, v in found.items()}


class ReasonTextTest(unittest.TestCase):
    def test_every_existing_state_has_a_plain_reason(self):
        states = _source_states()
        self.assertIn("zone_weg", states["zone_radar"])                 # de scan vond echt iets
        self.assertIn("stop_voor_vulling", states["zone_sweep"])
        self.assertIn("expired", states["structuur"])
        for kind, found in states.items():
            for state in sorted(found):
                text = end_reason.text(kind, state)
                self.assertTrue(text and text != state, f"{kind}/{state} heeft geen tekst")
                self.assertTrue(text.endswith("."), f"{kind}/{state}: {text}")

    def test_examples_in_plain_dutch(self):
        self.assertEqual(end_reason.text("zone_radar", "zone_weg"), "De zone is gebroken of te oud geworden.")
        self.assertEqual(end_reason.text("poc_radar", "verlopen"), "Na 3 dagen niet gevuld.")
        self.assertEqual(end_reason.text("zone_sweep", "verlopen"), "Na 24 uur niet gevuld.")
        self.assertEqual(end_reason.text("structuur", "expired"), "Na 4 uur niet gevuld: de koers kwam niet terug naar het niveau.")

    def test_unknown_state_is_still_a_sentence(self):
        self.assertEqual(end_reason.text("zone_radar", "iets_nieuws"), "Niet meer actief.")


class EndedCardsOnKansenTest(Base):
    def test_an_ended_zone_card_shows_its_reason_under_its_own_tab(self):
        sid = zone("SOL", "long", 90.0, 91.0, 89.0, 96.0, "1h:bull:x")
        repo.end_zone_radar_setup(sid, "zone_weg")
        html = self.client.get("/smc").text
        self.assertIn(f'id="radar-zone-{sid}"', html)                   # het anker van de melding wijst nog ergens heen
        self.assertIn("De zone is gebroken of te oud geworden.", html)

    def test_an_expired_structure_plan_shows_its_reason(self):
        sid = repo.insert_structure_setup({"coin": "ADA", "direction": "long", "kind": "LINE", "break_at": db.now_iso(), "p1_at": db.now_iso(),
                                           "line_a": 1.0, "line_slope": 0.0, "atr": 0.1, "grade": None, "reason": None, "features": "{}",
                                           "state": "waiting", "expires_at": db.now_iso(), "plan": None})
        repo.set_structure_state(sid, "expired")
        html = self.client.get("/smc").text
        self.assertIn("Na 4 uur niet gevuld: de koers kwam niet terug naar het niveau.", html)


class EndedCardsInLogbookTest(Base):
    def test_the_logbook_names_the_reason_on_the_day_it_ended(self):
        sid = zone("SOL", "long", 90.0, 91.0, 89.0, 96.0, "1h:bull:x")
        repo.end_zone_radar_setup(sid, "zone_weg")
        html = self.client.get("/signalen").text
        self.assertIn("SOL long, geen trade", html)
        self.assertIn("De zone is gebroken of te oud geworden.", html)

    def test_timeline_turns_an_ended_card_into_a_quiet_event(self):
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        ended = [{"kind": "poc_radar", "coin": "ETH", "direction": "short", "state": "verlopen", "ended_at": "2026-11-01T10:00:00+00:00"}]
        days = logbook.timeline(skips=[], runs=[], plans={}, signals={}, taken=[], seen=[], ended=ended, now=now, tz=timezone.utc)
        ev = days[0]["events"][0]
        self.assertEqual((ev["kind"], ev["title"], ev["sub"]), ("ended", "ETH short, geen trade", "POC-radar. Na 3 dagen niet gevuld."))


AMB = level_check.AMBIGUOUS_NOTE


class AmbiguousOutcomeVisibleTest(unittest.TestCase):
    def _row(self, note):
        return {"price": 100.0, "stop_loss": 99.0, "take_profit": 102.0, "auto_outcome": "stop_loss", "trade_type": "zone_radar", "message_id": None,
                "created_at": "2026-10-30T10:00:00+00:00", "auto_outcome_at": "2026-10-30T12:00:00+00:00", "auto_outcome_note": note}

    def test_summary_counts_order_unknown_per_type(self):
        entry = next(e for e in track_record.summarize([self._row(AMB), self._row(None)], 0.06) if e["trade_type"] == "zone_radar")
        self.assertEqual(entry["ambiguous"], 1)

    def test_logbook_close_event_says_order_unknown(self):
        s = {"id": 5, "coin": "BTC", "direction": "long", **self._row(AMB), "r_override": None}
        ev = logbook._close_events(s, datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc), timezone.utc)[0]
        self.assertIn("Volgorde onbekend", ev["sub"])

    def test_replay_stop_sentence_says_order_unknown(self):
        s = {"id": 5, "coin": "BTC", "direction": "long", **self._row(AMB), "r_override": None}
        self.assertIn("Volgorde onbekend", trade_replay._sentence({"key": "stop"}, s, -1.0))
        self.assertNotIn("Volgorde onbekend", trade_replay._sentence({"key": "stop"}, {**s, "auto_outcome_note": None}, -1.0))


class AmbiguousOnBewijsTest(Base):
    def test_bewijs_counts_order_unknown(self):
        sid = signal("SOL", "zone_radar", "stop_loss")
        with db.session() as conn:
            # Op perps-candles: de hoofdcijfers van een focus-soort (tests/test_bewijs_v2.py)
            conn.execute("UPDATE signals SET auto_outcome_note = ?, candle_market = 'perp' WHERE id = ?", (AMB, sid))
        html = self.client.get("/bewijs").text
        self.assertIn("1 keer stop en doel in dezelfde candle: volgorde onbekend, als stop geteld.", html)

    def test_signals_by_ids_carries_the_note(self):
        sid = signal("SOL", "zone_radar", "stop_loss")
        with db.session() as conn:
            conn.execute("UPDATE signals SET auto_outcome_note = ? WHERE id = ?", (AMB, sid))
        self.assertEqual(repo.signals_by_ids([sid])[sid]["auto_outcome_note"], AMB)


class PendingLevelAlertRetryTest(DbCase):
    """check_pending_signals: pas verzonden na een geslaagde push of na MAX_LEVEL_ALERT_ATTEMPTS, elke poging in push_attempts."""

    def setUp(self):
        super().setUp()
        self.uid = repo.list_users()[0]["id"]
        sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "swing", "price": 100.0,
                                  "stop_loss": 95.0, "take_profit": 110.0, "atr": 2.0, "technical_confirmed": 1, "hard_gates_ok": 1,
                                  "confidence": "x"}, chain_it=False)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?", ((datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(), sid))
        self.entry = repo.create_journal_entry(sid, self.uid, None)

    def _run(self, push):
        with mock.patch.object(level_check.exchange, "fetch_last_price", lambda coin: 100.2), \
                mock.patch.object(level_check.push_notify, "send_push", push):
            asyncio.run(level_check.check_pending_signals())

    def _sent(self) -> int:
        with db.session() as conn:
            return conn.execute("SELECT level_alert_sent FROM journal_entries WHERE id = ?", (self.entry,)).fetchone()[0]

    async def _boom(self, *a, **k):
        raise RuntimeError("netwerk weg")

    async def _ok(self, *a, **k):
        return None

    async def _no_device(self, *a, **k):
        return "1 van 1 apparaten mislukt"

    def _attempts(self):
        return repo.list_push_attempts("terug_bij_niveau", f"journal:{self.entry}")

    def test_a_failed_send_keeps_the_flag_and_logs_the_attempt(self):
        self._run(self._boom)
        self.assertEqual(self._sent(), 0)
        self.assertEqual([a["ok"] for a in self._attempts()], [0])
        self.assertIn("netwerk weg", self._attempts()[0]["error"])

    def test_a_send_that_reached_no_device_is_retried_then_succeeds(self):
        self._run(self._no_device)
        self.assertEqual(self._sent(), 0)
        self._run(self._ok)
        self.assertEqual(self._sent(), 1)
        self.assertEqual([a["ok"] for a in self._attempts()], [0, 1])

    def test_after_the_maximum_attempts_the_flag_is_set(self):
        for _ in range(level_check.MAX_LEVEL_ALERT_ATTEMPTS):
            self._run(self._boom)
        self.assertEqual(self._sent(), 1)
        self.assertEqual(len(self._attempts()), level_check.MAX_LEVEL_ALERT_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
