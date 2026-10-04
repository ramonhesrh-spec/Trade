"""Golden-test: de factorentoetsing geeft na de refactor exact dezelfde
uitkomst als ervoor. Opnemen met: python3 -m tests.test_confirmation_golden --record
(alleen draaien op code die nog NIET is aangepast).
Faalt de golden op een andere machine alleen door float-ruis? Neem hem dan NOOIT
opnieuw op op HEAD (dat maakt de bewaking waardeloos), maar op de commit van
vóór de refactor: 018eb3d (voor cfeabb0), bijvoorbeeld in een `git worktree`
van die commit; of vergelijk HEAD met een verse opname uit die commit."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, signal_processor
from app.replay.view import ReplayData
from tests.replay.fixtures import make_base

GOLDEN = Path(__file__).parent / "golden" / "full_confirmation.json"
TIMES = ["2026-02-10 00:00", "2026-02-12 13:30", "2026-02-15 21:00"]
CASES = [(coin, direction, at) for coin in ("ETH", "BTC") for direction in ("long", "short") for at in TIMES]


def _inputs(coin, at):
    base = {"BTC": make_base(days=60, seed=1), "ETH": make_base(days=60, seed=2, start_price=50.0)}
    data = ReplayData(base, pd.Timestamp(at, tz="UTC"))
    df = data.fetch_ohlcv(coin)
    ind = signal_processor.indicators.compute_indicators(df)
    zones = signal_processor.indicators.detect_sr_zones(df)
    return data, df, ind, zones


def run_async_case(coin, direction, at):
    data, df, ind, zones = _inputs(coin, at)
    with mock.patch.object(signal_processor, "exchange", data), \
            mock.patch.object(config, "ENABLE_ADVANCED_FACTORS", True):
        confirmed, reason, pass_pct, gates = asyncio.run(
            signal_processor.compute_full_confirmation(coin, direction, df, ind, zones))
    return [confirmed, reason, round(pass_pct, 6), gates]


def run_sync_case(coin, direction, at):
    data, df, ind, zones = _inputs(coin, at)
    with mock.patch.object(config, "ENABLE_ADVANCED_FACTORS", True):
        confirmed, reason, pass_pct, gates = signal_processor.full_confirmation_sync(
            coin, direction, df, ind, zones, True, data)
    return [confirmed, reason, round(pass_pct, 6), gates]


class GoldenTest(unittest.TestCase):
    def test_async_wrapper_matches_golden(self):
        golden = json.loads(GOLDEN.read_text())
        for coin, direction, at in CASES:
            self.assertEqual(run_async_case(coin, direction, at), golden[f"{coin}|{direction}|{at}"])

    def test_sync_core_matches_golden(self):
        golden = json.loads(GOLDEN.read_text())
        for coin, direction, at in CASES:
            self.assertEqual(run_sync_case(coin, direction, at), golden[f"{coin}|{direction}|{at}"])


if __name__ == "__main__":
    if "--record" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(
            {f"{c}|{d}|{a}": run_async_case(c, d, a) for c, d, a in CASES}, indent=1, ensure_ascii=False))
        print(f"golden opgenomen in {GOLDEN}")
    else:
        unittest.main()
