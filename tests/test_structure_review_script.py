import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app import repo, structure_live
from tests.test_samenval import DbCase

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "structure_review.py"


def load_script():
    spec = importlib.util.spec_from_file_location("structure_review_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptLoadTest(DbCase):
    def test_rows_carry_everything_the_missed_break_analysis_needs(self):
        t = datetime.now(timezone.utc) - timedelta(hours=5)
        plan = {"level": 100.0, "stop": 100.8, "risk_pct": 0.8, "targets": [99.2, 98.4], "targets_r": [1.0, 2.0]}
        repo.insert_structure_setup({"coin": "BTC", "direction": "short", "kind": "LINE", "break_at": t.isoformat(), "p1_at": (t - timedelta(hours=6)).isoformat(),
                                     "line_a": 100.5, "line_slope": -0.01, "atr": 0.5, "grade": "C", "reason": "x", "features": "{}", "state": "expired",
                                     "expires_at": (t + timedelta(hours=4)).isoformat(), "plan": json.dumps(plan)})
        rows = load_script().load(30)
        self.assertEqual(len(rows), 1)
        # structure_live.line_value (gebruikt door --gemist) leest precies deze velden; zonder ze crasht het script op de VPS
        self.assertAlmostEqual(structure_live.line_value(rows[0], pd.Timestamp(t)), 100.5 - 0.01 * 12)
        self.assertEqual(rows[0]["risk_pct"], 0.8)


if __name__ == "__main__":
    unittest.main()
