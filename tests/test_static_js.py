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


if __name__ == "__main__":
    unittest.main()
