"""scripts/model_kaarten.py en app/model_chart.py op synthetische candles, zonder beurs: de tekening heeft alle onderdelen, de tabel elke stap
met zijn tijdstip, en de herberekening zonder latere candles vindt geen afwijking."""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import model, model_chart, poc
from tests.hespulse_model import synth as S
from tests.hespulse_model.test_model import base_rows, end_of

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
kaarten = importlib.import_module("model_kaarten")


class KaartenTest(unittest.TestCase):
    def setUp(self):
        self.fr = S.frames(base_rows())
        self.now = end_of(self.fr)
        self.pocs = [poc.PocLevel("day", pd.Timestamp("2026-10-02", tz="UTC"), 112.0, None)]

    def collect(self):
        return kaarten.collect(["BTC"], self.now, 14, 30, fetcher=lambda coin, tf, n: self.fr[tf], pocs_of=lambda coin, now: self.pocs)

    def test_svg_has_every_part(self):
        (sc,) = [s for s in self.collect() if s["direction"] == "long"]
        svg = model_chart.full_svg(sc, self.fr["15m"])
        for part in ("Evenwicht", "Pool", "Sweep", "Top", "FVG", "OB", "Limiet", "Stop", "Doel", "Dag-POC"):
            self.assertIn(part, svg, part)
        self.assertEqual(svg.count('font-weight="700"'), len(sc["steps"]))        # een letter per stap

    def test_every_step_with_its_time_and_no_difference_without_future(self):
        chosen = self.collect()
        self.assertTrue(chosen)
        self.assertTrue(all(not s["problems"] for s in chosen))
        html = kaarten.build_html(chosen, self.now, 14)
        (sc,) = [s for s in chosen if s["direction"] == "long"]
        for stap, at, _ in model_chart.step_rows(sc):
            self.assertIn(f"<td>{stap}</td><td>{at}</td>", html)
        self.assertIn("Zonder latere candles hetzelfde.", html)

    def test_main_writes_one_html_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "k.html"
            orig = kaarten.fetch
            kaarten.fetch = lambda coin, tf, n: self.fr[tf]
            try:
                kaarten.main(["--coins", "BTC", "--uit", str(out), "--dagen", "3650"])
            finally:
                kaarten.fetch = orig
            self.assertTrue(out.read_text().startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
