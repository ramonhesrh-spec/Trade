import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import range_sweep_gallery as gallery                                   # noqa: E402
from app.replay import rangesweep as rs                                 # noqa: E402
from tests.replay.rangesweep_fixtures import FIRST_SHORT_ZONE_SETUP_HOUR, START, frames  # noqa: E402

HEAD = "coin,richting,tijd,instap,stop,doel,uitkomst,bron,notitie,tf\n"


class GalleryTest(unittest.TestCase):
    def setUp(self):
        self.fr = rs.build_frames(*frames())

    def test_csv_page_has_a_drawn_card_for_a_seen_example_and_a_text_card_for_a_missed_one(self):
        at = (START + pd.Timedelta(hours=FIRST_SHORT_ZONE_SETUP_HOUR + 1)).tz_convert("Europe/Amsterdam").strftime("%Y-%m-%d %H:%M")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "h.csv"
            f.write_text(HEAD + f"ARB,short,{at},105.4,106.4,100,,x<b>.webp,n,1h\nARB,short,{at},50,51,40,,y.webp,n,4h\n", encoding="utf-8")
            cards = gallery.from_csv(str(f), lambda coin, when: self.fr)
        html = gallery.page(cards)
        self.assertIn("gezien", cards[0])
        self.assertIn("<svg", cards[0])
        self.assertNotIn("<b>", html)                                    # bronnaam is ontsnapt
        self.assertTrue(any("niet gezien" in c and "<svg" not in c for c in cards))
        self.assertIn(".sc-zone", html)

    def test_zones_at_lists_only_zones_active_at_that_moment(self):
        at = START + pd.Timedelta(hours=FIRST_SHORT_ZONE_SETUP_HOUR + 1)
        zs = gallery.zones_at(self.fr["1h"], at, "1h")
        self.assertTrue(zs)
        self.assertTrue(all(z["kind"] in ("bear", "bull") for z in zs))
        self.assertEqual(gallery.zones_at(self.fr["1h"], START + pd.Timedelta(hours=2), "1h"), [])


if __name__ == "__main__":
    unittest.main()
