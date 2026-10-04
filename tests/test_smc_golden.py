"""Golden-test: de live SMC-pijplijn (market_scanner._run_smc_check) geeft na de
extractie over een hele synthetische periode exact dezelfde setups en signalen
als ervoor. Opnemen met: python3 -m tests.test_smc_golden --record (alleen op
code die nog NIET is aangepast; zie tests/golden/ voor de herstelinstructie).

Fixture-keuze (FIXTURE): met de standaard make_smc_prone_1m-parameters (seed 5,
spike_prob 0.002, spike_scale 0.006) levert de live pijplijn over deze periode 0
setups op, te weinig om iets te beschermen. Gekozen: seed=5, spike_prob=0.04,
spike_scale=0.03, wick_scale=0.0006 (start_price 2600, 12 dagen); die geven
meerdere setups, een vervallen setup en een afgewezen setup met een signaal.
De uitkomst is afhankelijk van deze waarden en van de stap (5 minuten)."""
import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, market_scanner, repo
from app.replay.view import ReplayData
from tests.replay.fixtures import make_smc_prone_1m

GOLDEN = Path(__file__).parent / "golden" / "smc_sequence.json"
ONE_MINUTE = pd.Timedelta(minutes=1)
COIN = "ETH"
START = pd.Timestamp("2026-01-03 00:03", tz="UTC")
END = pd.Timestamp("2026-01-12 00:03", tz="UTC")
STEP = pd.Timedelta(minutes=5)
FIXTURE = dict(days=12, seed=5, start_price=2600.0, spike_prob=0.04, spike_scale=0.03, wick_scale=0.0006)


class FrozenClock:
    now = datetime(2026, 1, 1)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FrozenClock.now


def run_live_sequence() -> dict:
    base = {COIN: make_smc_prone_1m(**FIXTURE)}
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(config, "DATABASE_PATH", str(Path(tmp) / "t.db")), \
            mock.patch.object(market_scanner, "datetime", FrozenDatetime), \
            mock.patch.object(db, "now_iso", lambda: FrozenClock.now.isoformat()):
        db.init_db()
        t = START
        while t <= END:
            FrozenClock.now = t.to_pydatetime()
            data = ReplayData(base, t, base_delta=ONE_MINUTE)
            with mock.patch.object(market_scanner, "exchange", data):
                asyncio.run(market_scanner._run_smc_check(COIN))
            t += STEP
        with db.session() as conn:
            setups = [dict(r) for r in conn.execute("SELECT * FROM smc_setups ORDER BY id")]
            signals = [dict(r) for r in conn.execute(
                "SELECT id, coin, direction, price, stop_loss, take_profit, created_at, sniper_entry_price "
                "FROM signals ORDER BY id")]
    def rounded(row):
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}
    return {"setups": [rounded(r) for r in setups], "signals": [rounded(r) for r in signals]}


class GoldenTest(unittest.TestCase):
    def test_live_sequence_matches_golden(self):
        self.assertEqual(run_live_sequence(), json.loads(GOLDEN.read_text()))


if __name__ == "__main__":
    if "--record" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        result = run_live_sequence()
        GOLDEN.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"golden opgenomen in {GOLDEN}: {len(result['setups'])} setups, {len(result['signals'])} signalen")
    else:
        unittest.main()
