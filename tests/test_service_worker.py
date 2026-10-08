import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class NotificationClickTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", str(ROOT / "tests/js/sw_harness.js"), str(ROOT / "web/static/service-worker.js")], capture_output=True, text=True, check=True)
        cls.result = json.loads(out.stdout)

    def test_open_app_gets_the_destination_as_a_message_instead_of_relying_on_navigate(self):
        log = self.result["openApp"]
        self.assertTrue(log["closed"])
        self.assertEqual(log["posted"], [{"hespulseNavigate": "https://hespulse.test/kans/5"}])
        self.assertEqual(log["opened"], [])                      # geen tweede venster naast de geïnstalleerde app
        self.assertEqual(log["focused"], 1)

    def test_destination_is_cached_for_a_cold_start_that_ignores_the_url(self):
        for scenario in ("openApp", "coldStart"):
            key, value = self.result[scenario]["cached"][0]
            self.assertEqual(key, "/__pending-nav")
            self.assertEqual(value["url"], "https://hespulse.test/kans/5")

    def test_cold_start_opens_a_window_on_the_absolute_url(self):
        self.assertEqual(self.result["coldStart"]["opened"], ["https://hespulse.test/kans/5"])
        self.assertEqual(self.result["coldStart"]["posted"], [])

    def test_failing_focus_does_not_stop_the_message(self):
        self.assertEqual(len(self.result["focusFails"]["posted"]), 1)

    def test_service_worker_is_served_without_cache_so_updates_arrive(self):
        from fastapi.testclient import TestClient
        from web.main import app
        self.assertEqual(TestClient(app).get("/service-worker.js").headers["cache-control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
