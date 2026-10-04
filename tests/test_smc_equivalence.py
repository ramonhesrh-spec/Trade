"""Bewijs dat de replay-engine (app/replay/smc_engine.py) exact dezelfde beslissingen
neemt als de live SMC-pijplijn (market_scanner._run_smc_check) over dezelfde
synthetische 1m-data en dezelfde tijdstippen: dezelfde signalen (richting, entry,
stop, doel, tijdstip) en dezelfde setups (zones, niveaus, aanmaak- en
bijwerktijd, ongeldig, voltooid). Verschilt de engine, dan is de engine fout,
niet deze test. Draait enkele minuten: de live-kant gebruikt een echte database."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, market_scanner
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
               round(r["structure_level"], 6), round(r["liquidity_target"], 6), r["created_at"], r["updated_at"],
               r["invalidated_at"] is not None, r["signal_id"] is not None) for r in live["setups"]]
    return signals, setups


def engine_view(signals, book):
    s = [(x.direction, round(x.entry, 6), round(x.stop, 6), round(x.take, 6), x.at.isoformat()) for x in signals]
    r = [(x["direction"], round(x["zone_low"], 6), round(x["zone_high"], 6), round(x["sweep_price"], 6),
          round(x["structure_level"], 6), round(x["liquidity_target"], 6), x["created_at"], x["updated_at"],
          x["invalidated_at"] is not None, x["signal_id"] is not None) for x in book.all_setups()]
    return s, r


class EquivalenceTest(unittest.TestCase):
    def assert_same(self, live, base, start, end):
        book = smc_engine.SmcBook()
        signals = smc_engine.replay_smc(COIN, base, base[COIN], start, end, step=STEP, book=book)
        live_signals, live_setups = live_view(live)
        replay_signals, replay_setups = engine_view(signals, book)
        self.assertEqual(replay_setups, live_setups)
        self.assertEqual(replay_signals, live_signals)
        return len(live_setups), len(live_signals)

    def test_replay_matches_live_pipeline_golden_period(self):
        counts = self.assert_same(run_live_sequence(), {COIN: make_smc_prone_1m(**FIXTURE)}, START, END)
        self.assertGreaterEqual(counts[0], 4)  # een lege vergelijking bewijst niets
        self.assertGreaterEqual(counts[1], 1)

    def test_replay_matches_live_pipeline_second_period(self):
        base = {COIN: make_smc_prone_1m(**SECOND_FIXTURE)}
        counts = self.assert_same(run_live(base, SECOND_START, SECOND_END), base, SECOND_START, SECOND_END)
        self.assertGreaterEqual(counts[0], 4)

    def test_replay_matches_live_pipeline_third_period_with_signal(self):
        base = {COIN: make_smc_prone_1m(**THIRD_FIXTURE)}
        counts = self.assert_same(run_live(base, SECOND_START, SECOND_END), base, SECOND_START, SECOND_END)
        self.assertGreaterEqual(counts, (2, 1))


if __name__ == "__main__":
    unittest.main()
