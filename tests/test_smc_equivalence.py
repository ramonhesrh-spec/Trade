"""Bewijs dat de replay-engine (app/replay/smc_engine.py) exact dezelfde beslissingen
neemt als de live SMC-pijplijn (market_scanner._run_smc_check) over dezelfde
synthetische 1m-data en dezelfde tijdstippen: dezelfde signalen (richting, entry,
stop, doel, tijdstip) en dezelfde setups (zones, niveaus, aanmaak- en
bijwerktijd, ongeldig, voltooid). Verschilt de engine, dan is de engine fout,
niet deze test. Draait enkele minuten (ongeveer 6): de live-kant gebruikt een echte database.
Overslaan kan met de omgevingsvariabele SKIP_SLOW_TESTS=1."""
import asyncio
import os
import tempfile
from collections import Counter
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, market_scanner, smc_eval
from app.replay import smc_engine
from app.replay.view import ReplayData
from tests.replay.fixtures import make_smc_prone_1m
from tests.test_smc_golden import (
    COIN, END, FIXTURE, ONE_MINUTE, START, STEP, FrozenClock, FrozenDatetime, run_live_sequence,
)

# Aanvullende perioden met andere seeds en prijs dan de golden-fixture. Seed 8 geeft vier setups
# (met een doorbraak en een tegenrichting-ongeldigverklaring, zonder signaal), seed 3 twee setups
# en een signaal; uitgezocht met de engine, de live-kant bevestigt hieronder.
SECOND_FIXTURE = dict(days=6, seed=8, start_price=1800.0, spike_prob=0.06, spike_scale=0.02, wick_scale=0.0006)
THIRD_FIXTURE = dict(SECOND_FIXTURE, seed=3)
# Vervallen-dekking: seed 8 bouwt om 04:03 een setup die met een limiet van 3 uur (ipv 24) om ~07:03 vervalt.
EXPIRY_START = pd.Timestamp("2026-01-03 02:03", tz="UTC")
EXPIRY_END = pd.Timestamp("2026-01-03 12:03", tz="UTC")
EXPIRY_MAX_AGE_HOURS = 3
SECOND_START = pd.Timestamp("2026-01-02 12:03", tz="UTC")
SECOND_END = pd.Timestamp("2026-01-05 12:03", tz="UTC")


def run_live(base, start, end) -> dict:
    """Zelfde lus als tests.test_smc_golden.run_live_sequence, voor een willekeurige basis en periode."""
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(config, "DATABASE_PATH", str(Path(tmp) / "t.db")), \
            mock.patch.object(market_scanner, "datetime", FrozenDatetime), \
            mock.patch.object(db, "now_iso", lambda: FrozenClock.now.isoformat()):
        db.init_db()
        t = start
        while t <= end:
            FrozenClock.now = t.to_pydatetime()
            with mock.patch.object(market_scanner, "exchange", ReplayData(base, t, base_delta=ONE_MINUTE)):
                asyncio.run(market_scanner._run_smc_check(COIN))
            t += STEP
        with db.session() as conn:
            setups = [dict(r) for r in conn.execute("SELECT * FROM smc_setups ORDER BY id")]
            signals = [dict(r) for r in conn.execute("SELECT * FROM signals ORDER BY id")]
    return {"setups": setups, "signals": signals}


def live_view(live):
    signals = [(s["direction"], round(s["price"], 6), round(s["stop_loss"], 6), round(s["take_profit"], 6),
                s["created_at"]) for s in live["signals"]]
    setups = [(r["direction"], round(r["zone_low"], 6), round(r["zone_high"], 6), round(r["sweep_price"], 6),
               round(r["structure_level"], 6), round(r["liquidity_target"], 6), round(r["atr"], 6), r["created_at"], r["updated_at"],
               r["invalidated_at"] is not None, r["signal_id"] is not None) for r in live["setups"]]
    return signals, setups


def engine_view(signals, book):
    s = [(x.direction, round(x.entry, 6), round(x.stop, 6), round(x.take, 6), x.at.isoformat()) for x in signals]
    r = [(x["direction"], round(x["zone_low"], 6), round(x["zone_high"], 6), round(x["sweep_price"], 6),
          round(x["structure_level"], 6), round(x["liquidity_target"], 6), round(x["atr"], 6), x["created_at"], x["updated_at"],
          x["invalidated_at"] is not None, x["signal_id"] is not None) for x in book.all_setups()]
    return s, r


@unittest.skipIf(os.environ.get("SKIP_SLOW_TESTS"), "SKIP_SLOW_TESTS gezet")
class EquivalenceTest(unittest.TestCase):
    def run_engine(self, base, start, end):
        """Engine over de periode; telt hoeveel upserts een al bestaande rij teruggaven (bijwerk-pad)."""
        book, updates = smc_engine.SmcBook(), []
        real_upsert = smc_engine.SmcBook.upsert

        def counting_upsert(self_, *a, **k):
            known = {r["id"] for r in self_.all_setups()}
            sid = real_upsert(self_, *a, **k)
            updates.append(sid in known)
            return sid

        with mock.patch.object(smc_engine.SmcBook, "upsert", counting_upsert):
            signals = smc_engine.replay_smc(COIN, base, base[COIN], start, end, step=STEP, book=book)
        return signals, book, updates

    def assert_same(self, live, base, start, end, coverage):
        signals, book, updates = self.run_engine(base, start, end)
        live_signals, live_setups = live_view(live)
        replay_signals, replay_setups = engine_view(signals, book)
        self.assertEqual(replay_setups, live_setups)
        self.assertEqual(replay_signals, live_signals)
        coverage["setups"] += len(replay_setups)
        coverage["signals"] += len(replay_signals)
        coverage["updates"] += sum(updates)
        for r in book.all_setups():
            coverage["ended"][r["ended_because"] or ("signaal" if r["signal_id"] else "bouwend")] += 1
        return len(live_setups), len(live_signals)

    def test_replay_matches_live_pipeline(self):
        coverage = {"setups": 0, "signals": 0, "updates": 0, "ended": Counter()}
        with self.subTest("golden"):
            counts = self.assert_same(run_live_sequence(), {COIN: make_smc_prone_1m(**FIXTURE)}, START, END, coverage)
            self.assertGreaterEqual(counts[0], 4)  # een lege vergelijking bewijst niets
            self.assertGreaterEqual(counts[1], 1)
        base2 = {COIN: make_smc_prone_1m(**SECOND_FIXTURE)}
        with self.subTest("seed 8"):
            counts = self.assert_same(run_live(base2, SECOND_START, SECOND_END), base2, SECOND_START, SECOND_END, coverage)
            self.assertGreaterEqual(counts[0], 4)
        base3 = {COIN: make_smc_prone_1m(**THIRD_FIXTURE)}
        with self.subTest("seed 3, met signaal"):
            counts = self.assert_same(run_live(base3, SECOND_START, SECOND_END), base3, SECOND_START, SECOND_END, coverage)
            self.assertGreaterEqual(counts, (2, 1))
        with self.subTest("vervallen, limiet 3 uur"), \
                mock.patch.object(smc_eval, "SMC_SETUP_MAX_AGE_HOURS", EXPIRY_MAX_AGE_HOURS):
            # live (market_scanner.setup_expired) en engine lezen allebei smc_eval.SMC_SETUP_MAX_AGE_HOURS
            before = coverage["ended"]["vervallen"]
            counts = self.assert_same(run_live(base2, EXPIRY_START, EXPIRY_END), base2, EXPIRY_START, EXPIRY_END, coverage)
            self.assertGreaterEqual(counts[0], 1)
            self.assertGreaterEqual(coverage["ended"]["vervallen"] - before, 1)
        # Welke paden zijn echt tegen live vergeleken
        ended = coverage["ended"]
        self.assertGreaterEqual(ended["doorbraak"] + ended["tegenrichting"], 1)
        self.assertGreaterEqual(ended["tegenrichting"], 1)
        self.assertGreaterEqual(ended["signaal"], 1)
        self.assertGreaterEqual(ended["vervallen"], 1)
        self.assertGreaterEqual(coverage["updates"], 1)


if __name__ == "__main__":
    unittest.main()
