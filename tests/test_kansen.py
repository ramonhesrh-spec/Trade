"""De pagina Kansen (app/kansen.py): een tab per soort, in de zone eerst en dan op gemeten afstand, open trades eronder, de juiste tab open."""
import unittest

from app import kansen, radar

ZONE = {"id": 8, "coin": "BTC", "direction": "short", "zone_low": 80774.8, "zone_high": 80900.0, "source": "zone_radar",
        "preview_stop_loss": 81097.9, "preview_take_profit": 80128.6, "created_at": "2026-10-05T11:00:00+00:00"}
ZONE2 = {**ZONE, "id": 9, "coin": "ETH", "zone_low": 2455.0, "zone_high": 2470.0, "preview_stop_loss": 2484.0, "preview_take_profit": 2392.0}
SWEEP = {"id": 4, "coin": "SOL", "direction": "long", "zone_low": 140.0, "zone_high": 141.5, "source": "zone_sweep",
         "preview_stop_loss": 139.0, "preview_take_profit": 150.0, "created_at": "2026-10-05T11:00:00+00:00"}
SMC = {"id": 7, "coin": "XRP", "direction": "long", "zone_low": 99.0, "zone_high": 100.0,
       "preview_stop_loss": 97.0, "preview_take_profit": 106.0, "created_at": "2026-10-05T10:00:00+00:00"}
TRADE = {"id": 3, "coin": "BNB", "direction": "short", "price": 100.0, "stop_loss": 103.0, "take_profit": 94.0, "trade_type": "zone_radar",
         "created_at": "2026-10-05T10:00:00+00:00"}
STRUCT_CARD = {"id": 12, "coin": "HYPE", "direction": "long", "plan": {"level": 80.9234, "stop": 78.5}, "targets": [(86.0, 2.1), (90.0, 3.8)]}
STRUCT_TRADE = {**TRADE, "id": 5, "coin": "AVAX", "trade_type": "structuur_c"}
KINDS = ("structuur", "zone_radar", "zone_sweep")


def cards(*pairs):
    return [radar.setup_card(row, price) for row, price in pairs]


class TabTests(unittest.TestCase):
    def page(self, radar_cards=(), structure=(), trades=(), kinds=KINDS):
        return kansen.page(list(radar_cards), list(structure), list(trades), kinds)

    def tab(self, page, key):
        return next(t for t in page["tabs"] if t["key"] == key)

    def test_een_tab_per_live_soort_in_vaste_volgorde(self):
        p = self.page()
        self.assertEqual([t["key"] for t in p["tabs"]], ["structuur", "zone_radar", "zone_sweep"])
        self.assertEqual([t["label"] for t in p["tabs"]], ["Structuur", "Zone-radar", "Zone-sweep"])
        self.assertEqual([t["href"] for t in p["tabs"]], ["#tab-structuur", "#tab-zone_radar", "#tab-zone_sweep"])

    def test_zonder_focus_ook_smc(self):
        p = self.page(cards((SMC, 103.0)), kinds=KINDS + ("smc",))
        self.assertEqual([x["key"] for x in self.tab(p, "smc")["plans"]], ["setup:7"])

    def test_een_open_trade_van_een_uitgezette_soort_houdt_zijn_tab(self):
        smc_trade = radar.signal_card({**TRADE, "id": 6, "trade_type": "smc"}, 97.0)
        p = self.page(cards((SMC, 99.5)) + [smc_trade])
        smc = self.tab(p, "smc")
        self.assertEqual(([x["key"] for x in smc["plans"]], [x["key"] for x in smc["trades"]]), ([], ["signal:6"]))

    def test_kaarten_landen_in_de_tab_van_hun_soort(self):
        p = self.page(cards((ZONE, 80537.0), (SWEEP, 145.0)))
        self.assertEqual([x["key"] for x in self.tab(p, "zone_radar")["plans"]], ["zone:8"])
        self.assertEqual([x["key"] for x in self.tab(p, "zone_sweep")["plans"]], ["zsweep:4"])

    def test_een_soort_zonder_tab_valt_weg(self):
        p = self.page(cards((SMC, 103.0), (SWEEP, 145.0)), kinds=("structuur", "zone_radar"))
        self.assertEqual(sum(len(t["plans"]) for t in p["tabs"]), 0)

    def test_in_de_zone_eerst_dan_op_afstand(self):
        p = self.page(cards((ZONE2, 2400.0), (ZONE, 80537.0), ({**ZONE, "id": 10}, 80800.0)))
        keys = [x["key"] for x in self.tab(p, "zone_radar")["plans"]]
        self.assertEqual(keys, ["zone:10", "zone:8", "zone:9"])          # in zone, dan 0,29% en dan 2,22%

    def test_overgeslagen_blijft_staan_maar_achteraan(self):
        p = kansen.page(cards((ZONE, 80800.0), (ZONE2, 2400.0)), [], [], KINDS, skipped={"zone:8"})
        plans = self.tab(p, "zone_radar")["plans"]
        self.assertEqual([(x["key"], x["skipped"]) for x in plans], [("zone:9", False), ("zone:8", True)])

    def test_zonder_koers_achteraan(self):
        p = self.page(cards((ZONE, None), (ZONE2, 2400.0)))
        self.assertEqual([x["key"] for x in self.tab(p, "zone_radar")["plans"]], ["zone:9", "zone:8"])

    def test_vervallen_plannen_staan_er_niet(self):
        p = self.page(cards((ZONE, 81200.0)))                                # voorbij de stop
        self.assertEqual(self.tab(p, "zone_radar")["plans"], [])
        self.assertEqual(self.tab(p, "zone_radar")["moot"], [{"title": "BTC short", "label": "Plan vervallen, de stop is geraakt", "dom_id": "radar-zone-8"}])

    def test_open_trades_onder_hun_soort(self):
        p = self.page(cards((ZONE, 80537.0)) + [radar.signal_card(TRADE, 97.0)], trades=[radar.signal_card(STRUCT_TRADE, 99.0)])
        self.assertEqual([x["key"] for x in self.tab(p, "zone_radar")["trades"]], ["signal:3"])
        self.assertEqual([x["key"] for x in self.tab(p, "structuur")["trades"]], ["signal:5"])     # structuur_c heet naar buiten Structuur

    def test_telling_en_badge(self):
        p = self.page(cards((ZONE, 80800.0), (ZONE2, 2400.0)) + [radar.signal_card(TRADE, 97.0)])
        t = self.tab(p, "zone_radar")
        self.assertEqual((t["n"], t["in_zone"], t["count"]), (2, 1, 1))
        self.assertEqual(t["summary"], "2 kansen · 1 in de zone · 1 open")
        self.assertIsNone(self.tab(p, "structuur")["count"])                 # geen badge zonder kans in de zone
        self.assertEqual(self.tab(p, "structuur")["summary"], "Geen kansen")

    def test_enkelvoud(self):
        t = self.tab(self.page(cards((ZONE, 80537.0))), "zone_radar")
        self.assertEqual(t["summary"], "1 kans · 0 in de zone")

    def test_de_tab_met_de_meeste_kansen_in_de_zone_gaat_open(self):
        p = self.page(cards((ZONE, 80800.0), ({**ZONE, "id": 10}, 80800.0), (SWEEP, 141.0)))
        self.assertEqual(p["active"], "zone_radar")

    def test_anders_structuur(self):
        self.assertEqual(self.page(cards((ZONE, 80537.0)))["active"], "structuur")

    def test_structuurplan_met_grafiek_en_sleutel(self):
        p = self.page(structure=[(STRUCT_CARD, 81.5, "wacht")])
        item = self.tab(p, "structuur")["plans"][0]
        self.assertEqual(item["key"], "structuur:12")
        self.assertEqual(item["dom_id"], "structuur-12")                     # de melding linkt naar /structuur#structuur-12
        self.assertEqual(item["chart"]["limit"], 80.9234)
        self.assertEqual(item["chart"]["take"], 86.0)
        self.assertEqual(item["checklist_url"], "/nu/order/structuur:12")


class ItemTests(unittest.TestCase):
    def item(self, row, price):
        return kansen.page(cards((row, price)), [], [], KINDS)["tabs"][1]["plans"][0]

    def test_kaart_titel_en_stand(self):
        it = self.item(ZONE, 80537.0)
        self.assertEqual(it["title"], "BTC short")
        self.assertEqual((it["state"], it["state_short"]), ("wacht", "Wacht"))
        self.assertEqual(it["dom_id"], "radar-zone-8")
        self.assertTrue(it["untested"])

    def test_het_grote_getal_is_gemeten(self):
        it = self.item(ZONE, 80537.0)
        self.assertEqual((it["num_text"], it["num_hook"], it["num_label"]), ("0,29%", "distance", "tot de instap"))
        z = self.item(ZONE, 80800.0)
        self.assertEqual((z["num_text"], z["state_short"]), ("", "In zone"))         # de stand staat al in de pil, geen tweede keer groot
        self.assertEqual(self.item(ZONE, None)["num_text"], "")

    def test_de_zin_herhaalt_geen_getallen(self):
        for price in (80537.0, 80800.0, None):
            say = self.item(ZONE, price)["say"]
            self.assertTrue(say)
            self.assertFalse(any(ch.isdigit() for ch in say), say)

    def test_open_trade_zonder_zin_met_live_r(self):
        p = kansen.page([radar.signal_card(TRADE, 97.0)], [], [], KINDS)
        it = p["tabs"][1]["trades"][0]
        self.assertEqual(it["say"], "")
        self.assertEqual((it["num_text"], it["num_hook"], it["state_short"]), ("+1,00 R", "live_r", "Open"))
        self.assertEqual(it["url"], "/kans/3")

    def test_getallen_met_komma_en_passende_decimalen(self):
        p = kansen.page([], [(STRUCT_CARD, 81.5, "wacht")], [], KINDS)
        rows = p["tabs"][0]["plans"][0]["rows"]
        self.assertIn("80,92", [r["text"] for r in rows])
        self.assertIn("80.92", [r["copy"] for r in rows])


class SayTests(unittest.TestCase):
    def test_wachten_en_zone(self):
        self.assertIn("Wacht", kansen.say("wacht", "long"))
        self.assertIn("zone", kansen.say("in_zone", "short"))
        self.assertEqual(kansen.say("open", "long"), "")
