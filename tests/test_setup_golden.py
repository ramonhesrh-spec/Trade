"""Golden-test: process_day_trading_signal schrijft na de extractie exact
dezelfde signaalrij weg als ervoor. Opnemen met:
python3 -m tests.test_setup_golden --record (alleen op ongewijzigde code).
Faalt de golden op een andere machine alleen door float-ruis? Neem hem dan NOOIT
opnieuw op op HEAD (dat maakt de bewaking waardeloos), maar op de commit van
vóór de extractie: 0ed4f0f (voor 797252d), bijvoorbeeld in een `git worktree`
van die commit; of vergelijk HEAD met een verse opname uit die commit.
TIMES wijken af van het plan: de geplande tijden gaven nul bevestigde gevallen
(de golden heeft er nu 2 bevestigd, 18 afgewezen)."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from app import coinlist, config, db, explain, repo, signal_processor
from app.anthropic_interpret import Interpretation
from app.replay.view import ReplayData
from tests.replay.fixtures import make_base

GOLDEN = Path(__file__).parent / "golden" / "live_setup.json"
TIMES = ["2026-02-14 08:15", "2026-02-12 13:30", "2026-02-15 21:00", "2026-02-20 08:15", "2026-02-20 17:45"]
CASES = [(coin, direction, at) for coin in ("ETH", "BTC") for direction in ("long", "short") for at in TIMES]
KEYS = [
    "technical_confirmed", "hard_gates_ok", "pass_pct", "reason", "price", "stop_loss", "take_profit",
    "nearest_sr_zone_price", "suggested_entry_low", "suggested_entry_high", "sniper_entry_price", "sniper_reason",
]


def run_live(coin, direction, at):
    base = {"BTC": make_base(days=60, seed=1), "ETH": make_base(days=60, seed=2, start_price=50.0)}
    data = ReplayData(base, pd.Timestamp(at, tz="UTC"))
    interp = Interpretation(coin=coin, direction=direction, category="day_trading", unclear=False)
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(config, "DATABASE_PATH", str(Path(tmp) / "t.db")), \
            mock.patch.object(config, "ENABLE_ADVANCED_FACTORS", True), \
            mock.patch.object(signal_processor, "exchange", data), \
            mock.patch.object(coinlist, "ensure_coin_tracked", return_value=(True, False)), \
            mock.patch.object(explain, "explain_signal", return_value=""):
        db.init_db()
        asyncio.run(signal_processor.process_day_trading_signal(None, interp))
        signal = repo.get_signal(1)
    return {k: (round(signal[k], 6) if isinstance(signal[k], float) else signal[k]) for k in KEYS}


class GoldenTest(unittest.TestCase):
    def test_live_pipeline_matches_golden(self):
        golden = json.loads(GOLDEN.read_text())
        for coin, direction, at in CASES:
            self.assertEqual(run_live(coin, direction, at), golden[f"{coin}|{direction}|{at}"],
                             f"{coin} {direction} {at}")


if __name__ == "__main__":
    if "--record" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(
            {f"{c}|{d}|{a}": run_live(c, d, a) for c, d, a in CASES}, indent=1, ensure_ascii=False))
        print(f"golden opgenomen in {GOLDEN}")
    else:
        unittest.main()
