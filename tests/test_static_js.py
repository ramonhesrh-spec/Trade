import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_node(harness: str, target: str) -> dict:
    out = subprocess.run(["node", str(ROOT / "tests/js" / harness), str(ROOT / "web/static" / target)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class StaleDotTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(run_node("stale_harness.js", "stale.js"), {"unknown": "unknown", "fresh": "fresh", "stale": "stale"})


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class LevelChartAreasTest(unittest.TestCase):
    def test_risk_between_entry_and_stop_reward_between_entry_and_take(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual(out["open"], [{"key": "risk", "base": 100, "value": 97}, {"key": "reward", "base": 100, "value": 106}])
        self.assertEqual(out["setup"], out["open"])                         # zonder entry geldt de limiet
        self.assertEqual(out["short"], [{"key": "risk", "base": 100, "value": 103}, {"key": "reward", "base": 100, "value": 94}])
        self.assertEqual(out["noStop"], [{"key": "reward", "base": 100, "value": 106}])
        self.assertEqual(out["nothing"], [])

    def test_vlak_aan_de_verkeerde_kant_wordt_weggelaten(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual(out["wrongSide"], [])                              # stop en doel aan dezelfde kant van de instap
        self.assertEqual(out["longStopAbove"], [])                          # long met stop boven de instap

    def test_rgba_geeft_nooit_de_invoer_terug(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual(out["rgbaHex"], "rgba(242,104,92,0.1)")
        self.assertEqual(out["rgbaOther"], "rgba(242,104,92,0.1)")
        self.assertEqual(out["rgbaNone"], "transparent")


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class UtabsTest(unittest.TestCase):
    def test_klik_toont_alleen_het_gekozen_paneel(self):
        out = run_node("utabs_harness.js", "utabs.js")
        self.assertEqual({k: out[k] for k in ("shown", "selected", "hash")}, {"shown": "tab-b", "selected": ["false", "true"], "hash": "#tab-b"})

    def test_zonder_hash_wint_de_actieve_tab_boven_de_eerste(self):
        self.assertEqual(run_node("utabs_harness.js", "utabs.js")["noHashActive"], "tab-b")


if __name__ == "__main__":
    unittest.main()
