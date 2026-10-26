"""Het scherm Nu (app/nu.py): rust of precies één kaart, het eerstvolgende plan, de tweede kans en de order-checklist."""
import unittest

from app import nu, radar

LONG = {"id": 7, "coin": "XRP", "direction": "long", "zone_low": 99.0, "zone_high": 100.0,
        "preview_stop_loss": 97.0, "preview_take_profit": 106.0, "created_at": "2026-10-05T10:00:00+00:00"}
SHORT = {"id": 8, "coin": "BTC", "direction": "short", "zone_low": 80774.8, "zone_high": 80900.0, "source": "zone_radar",
         "preview_stop_loss": 81097.9, "preview_take_profit": 80128.6, "created_at": "2026-10-05T11:00:00+00:00"}
TRADE = {"id": 3, "coin": "ETH", "direction": "short", "price": 100.0, "stop_loss": 103.0, "take_profit": 94.0, "trade_type": "smc",
         "created_at": "2026-10-05T10:00:00+00:00"}


def setup(row, price):
    return radar.setup_card(row, price)


class ScreenTests(unittest.TestCase):
    def test_zonder_kaarten_is_het_rust_zonder_eerstvolgende(self):
        s = nu.screen([])
        self.assertEqual(s["mode"], "rust")
        self.assertIsNone(s["nearest"])
        self.assertEqual((s["plans"], s["open_trades"]), (0, 0))

    def test_rust_noemt_het_dichtstbijzijnde_wachtende_plan(self):
        far, near = setup(LONG, 103.0), setup(SHORT, 80537.0)        # 3,00% en 0,29% tot de limiet
        s = nu.screen([far, near])
        self.assertEqual(s["mode"], "rust")
        self.assertEqual(s["nearest"]["key"], "zone:8")
        self.assertEqual(s["nearest"]["distance_text"], "0,29%")
        self.assertEqual(s["nearest"]["limit_text"], "80774,80")
        self.assertEqual(s["nearest"]["price_text"], "80537,00")
        self.assertAlmostEqual(s["nearest"]["approach_pct"], near["approach_pct"])
        self.assertEqual(s["plans"], 2)

    def test_een_plan_zonder_koers_telt_mee_maar_is_nooit_eerstvolgende(self):
        s = nu.screen([setup(LONG, None)])
        self.assertEqual(s["plans"], 1)
        self.assertIsNone(s["nearest"])

    def test_een_moot_of_vervallen_plan_telt_niet_mee(self):
        s = nu.screen([setup(LONG, 107.0), setup(LONG, 96.0)])        # doel gehaald zonder vulling, stop geraakt
        self.assertEqual(s["plans"], 0)
        self.assertEqual(s["mode"], "rust")

    def test_een_plan_in_de_zone_vult_het_scherm(self):
        s = nu.screen([setup(LONG, 103.0), setup(SHORT, 80800.0)])
        self.assertEqual(s["mode"], "zone")
        f = s["focus"]
        self.assertEqual((f["key"], f["coin"], f["dir_word"]), ("zone:8", "BTC", "Short"))
        self.assertIn("in de zone", f["action"])
        self.assertEqual(f["checklist_url"], "/nu/order/zone:8")
        self.assertTrue(f["untested"])
        self.assertEqual(f["trade_type"], "zone_radar")
        self.assertEqual(s["also"], [])

    def test_een_tweede_plan_in_de_zone_staat_eronder_en_niet_ernaast(self):
        a, b = setup(SHORT, 80800.0), setup(LONG, 99.5)
        s = nu.screen([a, b])
        self.assertEqual(s["focus"]["key"], "zone:8")                 # het dichtst bij de limiet (0,03% voorbij) gaat voor
        self.assertEqual([x["key"] for x in s["also"]], ["setup:7"])
        self.assertEqual(nu.screen([a, b], prefer="setup:7")["focus"]["key"], "setup:7")

    def test_een_overgeslagen_plan_valt_terug_op_rust_en_zegt_dat(self):
        s = nu.screen([setup(SHORT, 80800.0)], skipped={"zone:8"})
        self.assertEqual(s["mode"], "rust")
        self.assertEqual([x["key"] for x in s["skipped"]], ["zone:8"])
        self.assertIsNone(s["nearest"])                               # in de zone is geen afstand meer; het staat er als overgeslagen

    def test_alleen_een_open_trade_toont_die_met_live_r(self):
        s = nu.screen([radar.signal_card(TRADE, 97.0), setup(LONG, 103.0)])
        self.assertEqual(s["mode"], "trade")
        f = s["focus"]
        self.assertEqual(f["key"], "signal:3")
        self.assertEqual(f["live_r_text"], "+1,00 R")
        self.assertEqual(f["url"], "/kans/3")
        self.assertEqual(s["open_trades"], 1)

    def test_een_plan_in_de_zone_gaat_voor_een_open_trade_die_eronder_staat(self):
        s = nu.screen([radar.signal_card(TRADE, 97.0), setup(LONG, 99.5)])
        self.assertEqual(s["mode"], "zone")
        self.assertEqual([t["key"] for t in s["trades"]], ["signal:3"])

    def test_skip_cookie_houdt_alleen_geldige_sleutels(self):
        self.assertEqual(nu.parse_skip("zone:8,setup:7,<script>,signal:x"), frozenset({"zone:8", "setup:7"}))
        self.assertEqual(nu.parse_skip(None), frozenset())
        raw = nu.add_skip("zone:8", "setup:7")
        self.assertEqual(nu.parse_skip(raw), frozenset({"zone:8", "setup:7"}))
        self.assertEqual(nu.add_skip(",".join(f"setup:{i}" for i in range(40)), "zone:1").split(",")[-1], "zone:1")
        self.assertLessEqual(len(nu.add_skip(",".join(f"setup:{i}" for i in range(40)), "zone:1").split(",")), nu.MAX_SKIP)


class LookupTests(unittest.TestCase):
    def test_datumregel_in_het_nederlands(self):
        from datetime import datetime
        self.assertEqual(nu.date_line(datetime(2026, 10, 25, 23, 46)), "Zondag 25 oktober · 23:46")
        self.assertEqual(nu.date_line(datetime(2026, 3, 2, 9, 5)), "Maandag 2 maart · 09:05")

    def test_item_voor_de_checklist_alleen_als_het_plan_nog_kan_vullen(self):
        cards = [setup(SHORT, 80800.0), setup(LONG, 96.0), radar.signal_card(TRADE, 97.0)]
        self.assertEqual(nu.item_for(cards, "zone:8")["key"], "zone:8")
        self.assertIsNone(nu.item_for(cards, "setup:7"))                # stop geraakt
        self.assertIsNone(nu.item_for(cards, "signal:3"))               # een open trade heeft geen order meer te zetten
        self.assertIsNone(nu.item_for(cards, "zone:99"))

    def test_setupkaart_wordt_een_plan_met_meerdere_doelen(self):
        card = {"id": 4, "coin": "SOL", "direction": "long", "plan": {"level": 100.0, "stop": 99.0}, "targets": [(102.0, 2.0), (103.0, 3.0)]}
        item = nu.structure_item(card, 100.5, "wacht")
        self.assertEqual(item["key"], "structuur:4")
        self.assertEqual(item["distance_text"], "0,50%")
        self.assertEqual(len(item["targets"]), 2)
        self.assertEqual(item["trade_type"], "structuur")


class PlanRowTests(unittest.TestCase):
    def test_rijen_staan_op_prijs_zoals_de_grafiek(self):
        short = nu.plan_rows("short", 80774.8, 81097.9, [(80128.6, 2.0)])
        self.assertEqual([r["tone"] for r in short], ["loss", "entry", "win"])
        self.assertEqual(short[2]["label"], "Doel · 2,0 R")
        long = nu.plan_rows("long", 100.0, 97.0, [(103.0, 1.0), (106.0, 2.0)])
        self.assertEqual([r["label"] for r in long], ["Doel 2 · 2,0 R", "Doel 1 · 1,0 R", "Instap", "Stop"])
        self.assertEqual(long[2]["copy"], "100.00")
        self.assertEqual(long[2]["text"], "100,00")


class ChecklistTests(unittest.TestCase):
    def test_vier_stappen_in_de_volgorde_van_de_beurs_zonder_grootte(self):
        item = nu.screen([setup(SHORT, 80800.0)])["focus"]
        steps = nu.checklist(item)
        self.assertEqual([s["title"] for s in steps], ["Open BTC bij je beurs", "Limietprijs", "Stop", "Doel"])
        self.assertIn("Short en Limit", steps[0]["sub"])
        self.assertIsNone(steps[0]["value"])
        self.assertEqual(steps[1]["copy"], "80774.80")
        self.assertEqual(steps[2]["tone"], "loss")
        self.assertEqual(steps[3]["choices"], [])
        self.assertEqual(steps[3]["copy"], "80128.60")
        self.assertNotIn("Grootte", " ".join(s["title"] for s in steps))
        self.assertFalse(any("€" in (s["sub"] or "") for s in steps))

    def test_meerdere_doelen_geven_een_keuze(self):
        item = nu.plan_item("structuur:4", "SOL", "long", 100.0, 99.0, [(102.0, 2.0), (103.0, 3.0)], price=100.4, state=None,
                            trade_type="structuur", untested=False)
        doel = nu.checklist(item)[3]
        self.assertEqual([c["label"] for c in doel["choices"]], ["Doel 1 · 2,0 R", "Doel 2 · 3,0 R"])
        self.assertEqual(doel["copy"], "102.00")
        self.assertIn("Kies", doel["sub"])

    def test_koersregel_onderaan(self):
        self.assertEqual(nu.price_note(nu.screen([setup(SHORT, 80800.0)])["focus"]), "nog in zone")
        self.assertEqual(nu.price_note(nu.screen([setup(SHORT, 80537.0)])["nearest"]), "nog 0,29% tot instap")
        self.assertEqual(nu.price_note(nu.plan_item("structuur:4", "SOL", "long", 100.0, 99.0, [(102.0, 2.0)], price=None, state=None)), "")


if __name__ == "__main__":
    unittest.main()
