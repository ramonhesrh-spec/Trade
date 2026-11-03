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
class LevelChartFullTest(unittest.TestCase):
    def test_genoeg_candles_om_de_zone_te_zien_ontstaan(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual(out["limitBase"], 120)
        self.assertEqual(out["limitOld"], 162)                             # 150 candles oud plus marge
        self.assertEqual(out["limitCap"], 500)                             # nooit meer dan de server levert (RADAR_CANDLE_FETCH)
        self.assertEqual(out["limit15"], 160)

    def test_markering_op_de_candle_waarin_de_zone_ontstond(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual(out["barSame"], 3600)
        self.assertEqual(out["barInside"], 14400)                          # 1u-zone op een 4u-grafiek
        self.assertIsNone(out["barBefore"])
        self.assertIsNone(out["barAfter"])
        self.assertIsNone(out["barNone"])

    def test_standaard_tijdframe_en_uitleg(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual((out["tfZone"], out["tfPlain"]), ("4h", "1h"))
        self.assertEqual((out["noteSame"], out["noteOther"], out["noteOutside"]), ("hier", "elders", "eerder"))
        self.assertEqual((out["noteNoOrigin"], out["noteNoZone"]), ("", ""))


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class UtabsTest(unittest.TestCase):
    def test_klik_toont_alleen_het_gekozen_paneel(self):
        out = run_node("utabs_harness.js", "utabs.js")
        self.assertEqual({k: out[k] for k in ("shown", "selected", "hash")}, {"shown": "tab-b", "selected": ["false", "true"], "hash": "#tab-b"})

    def test_zonder_hash_wint_de_actieve_tab_boven_de_eerste(self):
        self.assertEqual(run_node("utabs_harness.js", "utabs.js")["noHashActive"], "tab-b")


    def test_hash_naar_kaart_in_ander_paneel_toont_dat_paneel(self):
        deep = run_node("utabs_harness.js", "utabs.js")["deep"]
        self.assertEqual(deep["onLoad"], "tab-b+scroll")
        self.assertEqual(deep["onHashchange"], "tab-b+scroll")
        self.assertEqual(deep["stray"], "tab-b")                         # onbekende hash laat het getoonde paneel staan


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class SparkChangeTest(unittest.TestCase):
    def test_verandering_zonder_minigrafiek_wordt_gevuld(self):
        self.assertEqual(run_node("spark_harness.js", "spark.js"), {"text": "-0,9%", "down": True, "fetched": "BTC"})


if __name__ == "__main__":
    unittest.main()


class NoJokesTest(unittest.TestCase):
    """CEO 2026-11-03: "het grappen is nu over, we gaan nu echt werken". Geen CEO-pagina, geldregen, confetti of meme meer."""

    def test_geen_grappen_meer(self):
        base = (ROOT / "web/templates/base.html").read_text()
        for gone in ("ceo.js", "meme-geld.webp", "Winst-confetti", 'href="/ceo"'):
            self.assertNotIn(gone, base)
        for f in ("web/static/ceo.js", "web/static/meme-geld.webp", "web/templates/ceo.html"):
            self.assertFalse((ROOT / f).exists(), f)
        self.assertNotIn("closed_win", (ROOT / "web/static/dashboard.js").read_text())


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class NotificationNavigationTest(unittest.TestCase):
    def test_a_tap_on_a_notification_navigates_on_load_and_when_the_app_returns(self):
        out = run_node("smooth_nav_harness.js", "smooth.js")
        self.assertEqual(out["onLoad"]["href"], "https://x.test/structuur#tab-ranges")
        self.assertEqual(out["onLoad"]["left"], 0)                       # de bestemming is opgebruikt
        self.assertEqual(out["afterBackground"]["href"], "https://x.test/structuur#tab-ranges")
        self.assertEqual(out["onReturn"]["href"], "https://x.test/vandaag")  # niets te doen zonder bestemming
        self.assertEqual(out["stale"]["href"], "https://x.test/vandaag")     # een bestemming ouder dan 2 minuten telt niet
        self.assertEqual(out["coldStart"]["href"], "https://x.test/kans/7")  # de bestemming kwam na het laden, de herhaalde controle vindt hem


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class LadderMathTest(unittest.TestCase):
    """ladder.js schuift de koers live met dezelfde formules als app/ladder.py; twee versies die uit elkaar lopen zou de lijn verkeerd zetten."""
    def test_dezelfde_maths_als_de_server(self):
        from app import ladder
        out = run_node("ladder_harness.js", "ladder.js")
        for got, args in zip(out["ys"], [(107.5, 110, 100), (130, 110, 100), (90, 110, 100), (80800, 81300, 80000)]):
            self.assertAlmostEqual(got, ladder.y_pct(*args))
        for got, args in zip(out["ds"], [("short", 100, 98), ("long", 100, 102), ("short", 80774.8, 80537)]):
            self.assertAlmostEqual(got, ladder.distance_pct(*args))
        from app import price_text
        self.assertEqual(out["nls"], [price_text.nl(v) for v in (80774.8, 102, 0.1702, 2.5, 80.9234, 9.99, 0.0099, 0.00001234, 0, -3.5)])
        self.assertEqual(out["nls"][:4], [ladder.nl(v) for v in (80774.8, 102, 0.1702, 2.5)])
        for got, v in zip(out["labels"], (0, 3, 50, 99, 100)):
            self.assertAlmostEqual(got, ladder.label_y(v))
        self.assertEqual(out["plains"], [price_text.plain(v) for v in (80.9234, 0.00001234)])
        self.assertEqual([out["stale"][i] for i in range(5)], [ladder.stale_text(v) for v in (None, 30, 45, 150, 7300)])

    def test_balk_van_zonerand_naar_koers(self):
        from app import ladder
        out = run_node("ladder_harness.js", "ladder.js")
        lad = ladder.build("short", 110.0, 101.0, [(90.0, 1.0)], 99.0, 101.0, 102.0)
        hi, lo = 110, 90
        self.assertAlmostEqual(out["gap"]["top"], ladder.y_pct(101, hi, lo))
        self.assertAlmostEqual(out["gap"]["height"], ladder.y_pct(99, hi, lo) - ladder.y_pct(101, hi, lo))
        self.assertFalse(out["gap"]["inZone"])
        self.assertTrue(out["inZone"]["inZone"])
        self.assertEqual(out["inZone"]["height"], 0)
        self.assertAlmostEqual(out["noZone"]["top"], ladder.y_pct(104, hi, lo))
        self.assertTrue(lad["gap"])


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class KansenSummaryTest(unittest.TestCase):
    def test_kaarten_js_zegt_hetzelfde_als_de_server(self):
        from app import kansen
        cases = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (12, 2, 3), (0, 0, 1), (2, 0, 1)]
        out = subprocess.run(["node", str(ROOT / "tests/js/kaarten_harness.js"), str(ROOT / "web/static/kaarten.js")], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout), [kansen.summary(*c) for c in cases])

    def test_ongedaan_balk_en_verborgen_regel_zeggen_hetzelfde_als_de_server(self):
        from app import kansen
        out = run_node("kaarten_hidden_harness.js", "kaarten.js")
        self.assertEqual(out["text"], [kansen.hidden_text(t) for t in (["HYPE short"], ["HYPE short", "ETH long", "SOL long"], ["A", "B"])])
        self.assertEqual(out["label"], [kansen.hidden_label(n) for n in (0, 1, 7)])


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class LiveStreamsTest(unittest.TestCase):
    """De koers in de browser komt van dezelfde markt als de candles (app/candle_source.py)."""

    def test_perps_op_fstream_met_symboolkaart_en_terugval_op_spot(self):
        out = run_node("live_streams_harness.js", "live.js")
        self.assertEqual(out["perp"], [
            {"url": "wss://fstream.binance.com/stream?streams=btcusdt@miniTicker/1000pepeusdt@miniTicker",
             "symbols": {"BTCUSDT": ["BTC", 1], "1000PEPEUSDT": ["PEPE", 1000]}},
            {"url": "wss://stream.binance.com:9443/stream?streams=noperpusdt@miniTicker", "symbols": {"NOPERPUSDT": ["NOPERP", 1]}},
        ])

    def test_spot_als_terugval_voor_alles(self):
        out = run_node("live_streams_harness.js", "live.js")
        self.assertEqual(out["spot"], [{"url": "wss://stream.binance.com:9443/stream?streams=btcusdt@miniTicker/pepeusdt@miniTicker",
                                        "symbols": {"BTCUSDT": ["BTC", 1], "PEPEUSDT": ["PEPE", 1]}}])
        self.assertEqual(len(out["onlyPerp"]), 1)                        # geen lege spotverbinding
