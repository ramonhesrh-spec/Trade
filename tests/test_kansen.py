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
        p = self.page(cards((ZONE2, 2400.0), (ZONE, 80537.0), ({**ZONE, "id": 10, "coin": "LTC"}, 80800.0)))
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
        self.assertEqual((t["n"], t["in_zone"], t["num"], t["badge"]), (2, 1, 2, 1))     # n telt de plannen in de zone mee, open trades niet
        self.assertIsNone(t["count"])                                        # de oude accentteller van utabs is de badge geworden
        self.assertEqual(t["summary"], "2 kansen klaar · 1 in de zone · 1 open")
        s = self.tab(p, "structuur")
        self.assertEqual((s["num"], s["badge"]), (0, None))                  # 0 staat er als getal, een badge pas bij 1 in de zone
        self.assertEqual(s["summary"], "Geen kansen")

    def test_enkelvoud_en_geen_nul_in_de_zone(self):
        t = self.tab(self.page(cards((ZONE, 80537.0))), "zone_radar")
        self.assertEqual(t["summary"], "1 kans klaar")

    def test_totaal_boven_de_tabs(self):
        p = self.page(cards((ZONE, 80800.0), (ZONE2, 2400.0), (SWEEP, 145.0)) + [radar.signal_card(TRADE, 97.0)],
                      structure=[(STRUCT_CARD, 81.5, "wacht")], trades=[radar.signal_card(STRUCT_TRADE, 99.0)])
        self.assertEqual(p["total"], {"n": 4, "in_zone": 1, "open": 2, "text": "4 kansen klaar · 1 in de zone · 2 open"})

    def test_totaal_leeg_en_enkelvoud(self):
        self.assertEqual(self.page()["total"]["text"], "Geen kansen")
        self.assertEqual(self.page(cards((ZONE, 80800.0)))["total"]["text"], "1 kans klaar · 1 in de zone")
        self.assertEqual(self.page(trades=[radar.signal_card(STRUCT_TRADE, 99.0)])["total"]["text"], "1 open")
        self.assertEqual(self.page(cards((ZONE, 80537.0)))["total"]["text"], "1 kans klaar")

    def test_totaal_is_de_som_van_de_tabs(self):
        p = self.page(cards((ZONE, 80800.0), (ZONE2, 2400.0), (SWEEP, 141.0)))
        self.assertEqual(p["total"]["n"], sum(t["n"] for t in p["tabs"]))
        self.assertEqual(p["total"]["in_zone"], p["in_zone"])

    def test_de_tab_met_de_meeste_kansen_in_de_zone_gaat_open(self):
        p = self.page(cards((ZONE, 80800.0), ({**ZONE, "id": 10, "coin": "LTC"}, 80800.0), (SWEEP, 141.0)))
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

    def test_structuurplan_tekent_zijn_eigen_momentopname(self):
        p = self.page(structure=[({**STRUCT_CARD, "chart": "<svg class=\"sc\"></svg>"}, 81.5, "wacht")])
        self.assertEqual(self.tab(p, "structuur")["plans"][0]["svg"], '<svg class="sc"></svg>')

    def test_structuurplan_zonder_momentopname_valt_terug_op_de_kaartgrafiek(self):
        item = self.tab(self.page(structure=[({**STRUCT_CARD, "chart": ""}, 81.5, "wacht")]), "structuur")["plans"][0]
        self.assertFalse(item["svg"])
        self.assertEqual(item["chart"]["limit"], 80.9234)

    def test_open_structuurtrade_draagt_zijn_tekening(self):
        trade = {**radar.signal_card(STRUCT_TRADE, 99.0), "svg": '<svg class="sc"></svg>'}
        it = self.tab(self.page(trades=[trade]), "structuur")["trades"][0]
        self.assertEqual(it["svg"], '<svg class="sc"></svg>')

    def test_zone_soorten_laden_hun_eigen_tekening(self):
        p = self.page(cards((ZONE, 80537.0), (SWEEP, 145.0)) + [radar.signal_card(TRADE, 97.0)])
        self.assertEqual(self.tab(p, "zone_radar")["plans"][0]["svg_src"], "/api/kaart_svg/zone:8")
        self.assertEqual(self.tab(p, "zone_sweep")["plans"][0]["svg_src"], "/api/kaart_svg/zsweep:4")
        self.assertEqual(self.tab(p, "zone_radar")["trades"][0]["svg_src"], "/api/kaart_svg/signal:3")

    def test_smc_en_structuur_laden_geen_zonetekening(self):
        p = self.page(cards((SMC, 103.0)), structure=[(STRUCT_CARD, 81.5, "wacht")], kinds=KINDS + ("smc",))
        self.assertIsNone(self.tab(p, "smc")["plans"][0]["svg_src"])
        self.assertIsNone(self.tab(p, "structuur")["plans"][0]["svg_src"])

    def test_andere_soorten_houden_de_kaartgrafiek(self):
        p = self.page(cards((ZONE, 80537.0)) + [radar.signal_card(TRADE, 97.0)])
        z = self.tab(p, "zone_radar")
        self.assertFalse(z["plans"][0].get("svg"))
        self.assertTrue(z["plans"][0]["chart"])
        self.assertFalse(z["trades"][0].get("svg"))


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
        self.assertIn("de instap bereikt", kansen.say("wacht", "long", zone=False))       # Structuur heeft een niveau, geen zone


class DuplicateTests(unittest.TestCase):
    """Per tab één kaart per coin, richting en instap (binnen kansen.DUP_PCT): de oudste blijft, de rest telt als 'vergelijkbaar'. Alleen de
    weergave van Kansen; Bewijs, Logboek en de database houden elk signaal."""

    def trade(self, ident, coin="ETH", direction="short", price=2357.50, stop=2380.0, take=2300.0, created="2026-10-05T10:00:00+00:00", tt="zone_radar"):
        return radar.signal_card({**TRADE, "id": ident, "coin": coin, "direction": direction, "price": price, "stop_loss": stop, "take_profit": take,
                                  "trade_type": tt, "created_at": created}, 2350.0)

    def tab(self, p, key):
        return next(t for t in p["tabs"] if t["key"] == key)

    def test_twee_eth_short_met_dezelfde_instap_worden_een_kaart(self):
        p = kansen.page([self.trade(1, stop=2380.0, created="2026-10-05T11:00:00+00:00"), self.trade(2, stop=2390.0, created="2026-10-05T09:00:00+00:00")],
                        [], [], KINDS)
        t = self.tab(p, "zone_radar")
        self.assertEqual([x["key"] for x in t["trades"]], ["signal:2"])               # de oudste trade blijft
        self.assertEqual(t["trades"][0]["similar"], 1)
        self.assertEqual(p["total"]["open"], 1)

    def test_grens_net_onder_en_net_boven(self):
        base = 2000.0
        under = kansen.page([self.trade(1, price=base), self.trade(2, price=base * 1.00199, created="2026-10-05T11:00:00+00:00")], [], [], KINDS)
        over = kansen.page([self.trade(1, price=base), self.trade(2, price=base * 1.00201, created="2026-10-05T11:00:00+00:00")], [], [], KINDS)
        self.assertEqual(len(self.tab(under, "zone_radar")["trades"]), 1)
        self.assertEqual(len(self.tab(over, "zone_radar")["trades"]), 2)

    def test_ondo_long_en_short_blijven_allebei(self):
        p = kansen.page([self.trade(1, coin="ONDO", direction="long", price=0.9, stop=0.88, take=0.95),
                         self.trade(2, coin="ONDO", direction="short", price=0.9, stop=0.92, take=0.85)], [], [], KINDS)
        self.assertEqual(len(self.tab(p, "zone_radar")["trades"]), 2)

    def test_zelfde_coin_in_twee_tabs_blijft_in_beide(self):
        p = kansen.page([self.trade(1, tt="zone_radar"), self.trade(2, tt="zone_sweep")], [], [], KINDS)
        self.assertEqual(len(self.tab(p, "zone_radar")["trades"]), 1)
        self.assertEqual(len(self.tab(p, "zone_sweep")["trades"]), 1)

    def test_wachtende_plannen_apart_van_open_trades(self):
        plan_a = {**ZONE, "id": 20, "created_at": "2026-10-05T12:00:00+00:00"}
        plan_b = {**ZONE, "id": 21, "preview_stop_loss": 81200.0, "created_at": "2026-10-05T08:00:00+00:00"}
        trade = radar.signal_card({**TRADE, "id": 30, "coin": "BTC", "direction": "short", "price": 80774.8, "stop_loss": 81097.9,
                                   "take_profit": 80128.6}, 80537.0)
        p = kansen.page(cards((plan_a, 80537.0), (plan_b, 80537.0)) + [trade], [], [], KINDS)
        t = self.tab(p, "zone_radar")
        self.assertEqual(([x["key"] for x in t["plans"]], t["plans"][0]["similar"]), (["zone:21"], 1))
        self.assertEqual([x["key"] for x in t["trades"]], ["signal:30"])               # een open trade telt niet tegen een plan
        self.assertEqual((t["n"], p["total"]["n"]), (1, 1))

    def test_geen_dubbele_dan_nul(self):
        p = kansen.page(cards((ZONE, 80537.0)), [], [], KINDS)
        self.assertEqual(self.tab(p, "zone_radar")["plans"][0]["similar"], 0)

    def test_similar_text(self):
        self.assertEqual(kansen.similar_text(0), "")
        self.assertEqual(kansen.similar_text(1), "Nog 1 vergelijkbaar signaal")
        self.assertEqual(kansen.similar_text(3), "Nog 3 vergelijkbare signalen")


class HiddenTests(unittest.TestCase):
    """Verbergen (kans_hidden): alleen een weergavekeuze per gebruiker. Een verborgen kaart staat niet in de lijst en telt nergens mee, maar staat
    onderaan zijn tab onder 'Verborgen (N)' met 'Toon weer'."""

    def tab(self, p, key):
        return next(t for t in p["tabs"] if t["key"] == key)

    def trade(self, ident, coin="ETH", price=2357.5, created="2026-10-05T10:00:00+00:00"):
        return radar.signal_card({**TRADE, "id": ident, "coin": coin, "price": price, "stop_loss": price * 1.01, "take_profit": price * 0.97,
                                  "created_at": created}, price)

    def test_verborgen_plan_staat_niet_in_de_lijst_maar_onder_verborgen(self):
        p = kansen.page(cards((ZONE, 80800.0), (ZONE2, 2400.0)), [], [], KINDS, hidden={"zone:8"})
        t = self.tab(p, "zone_radar")
        self.assertEqual([x["key"] for x in t["plans"]], ["zone:9"])
        self.assertEqual([(h["key"], h["title"], h["state_short"], h["group"]) for h in t["hidden"]], [("zone:8", "BTC short", "In zone", "plans")])
        self.assertEqual(t["hidden_label"], "Verborgen (1)")
        self.assertEqual([x["key"] for x in t["hidden_cards"]], ["zone:8"])

    def test_ongedaan_is_gewoon_niet_meer_verborgen(self):
        before = kansen.page(cards((ZONE, 80800.0)), [], [], KINDS)
        after = kansen.page(cards((ZONE, 80800.0)), [], [], KINDS, hidden=set())
        self.assertEqual(self.tab(before, "zone_radar")["plans"][0]["key"], self.tab(after, "zone_radar")["plans"][0]["key"])
        self.assertEqual(self.tab(after, "zone_radar")["hidden"], [])
        self.assertEqual(self.tab(after, "zone_radar")["hidden_label"], "")

    def test_open_trade_verbergen(self):
        p = kansen.page([self.trade(1), self.trade(2, coin="SOL", price=150.0)], [], [], KINDS, hidden={"signal:1"})
        t = self.tab(p, "zone_radar")
        self.assertEqual([x["key"] for x in t["trades"]], ["signal:2"])
        self.assertEqual([(h["key"], h["state_short"], h["group"]) for h in t["hidden"]], [("signal:1", "Open", "trades")])
        self.assertEqual(p["total"]["open"], 1)

    def test_alles_verbergen(self):
        trades = [self.trade(i, coin=c, price=pr) for i, (c, pr) in enumerate((("ETH", 2357.5), ("SOL", 150.0), ("ADA", 0.6)), 1)]
        p = kansen.page(cards((ZONE, 80800.0)) + trades, [], [], KINDS, hidden={"signal:1", "signal:2", "signal:3", "zone:8"})
        t = self.tab(p, "zone_radar")
        self.assertEqual((t["plans"], t["trades"]), ([], []))
        self.assertEqual(t["hidden_label"], "Verborgen (4)")
        self.assertEqual(p["total"]["text"], "Geen kansen")

    def test_tellers_zonder_verborgen(self):
        p = kansen.page(cards((ZONE, 80800.0), (ZONE2, 2400.0)) + [self.trade(1)], [], [], KINDS, hidden={"zone:8", "signal:1"})
        t = self.tab(p, "zone_radar")
        self.assertEqual((t["n"], t["num"], t["in_zone"], t["badge"]), (1, 1, 0, None))       # de verborgen kans in de zone telt niet
        self.assertEqual(t["summary"], "1 kans klaar")
        self.assertEqual(p["total"], {"n": 1, "in_zone": 0, "open": 0, "text": "1 kans klaar"})
        self.assertEqual(p["in_zone"], 0)

    def test_verborgen_kans_in_de_zone_kiest_de_tab_niet(self):
        p = kansen.page(cards((ZONE, 80800.0)), [], [], KINDS, hidden={"zone:8"})
        self.assertEqual(p["active"], "structuur")

    def test_per_gebruiker_apart(self):
        rows = cards((ZONE, 80800.0), (ZONE2, 2400.0))
        mine = kansen.page(rows, [], [], KINDS, hidden={"zone:8"})
        other = kansen.page(rows, [], [], KINDS, hidden=set())
        self.assertEqual(len(self.tab(mine, "zone_radar")["plans"]), 1)
        self.assertEqual(len(self.tab(other, "zone_radar")["plans"]), 2)

    def test_verborgen_tellen_niet_mee_als_vergelijkbaar(self):
        a = self.trade(1, created="2026-10-05T09:00:00+00:00")
        b = self.trade(2, created="2026-10-05T10:00:00+00:00")
        c = self.trade(3, created="2026-10-05T11:00:00+00:00")
        shown = self.tab(kansen.page([a, b, c], [], [], KINDS), "zone_radar")["trades"][0]
        self.assertEqual((shown["key"], shown["similar"], shown["keys"]), ("signal:1", 2, ["signal:1", "signal:2", "signal:3"]))
        t = self.tab(kansen.page([a, b, c], [], [], KINDS, hidden={"signal:3"}), "zone_radar")
        self.assertEqual((t["trades"][0]["similar"], t["trades"][0]["similar_text"]), (1, "Nog 1 vergelijkbaar signaal"))
        self.assertEqual(t["trades"][0]["keys"], ["signal:1", "signal:2"])

    def test_verbergen_van_een_dubbele_kaart_neemt_zijn_tweelingen_mee(self):
        # De knop verbergt card["keys"]: dan komt de jongere tweeling niet ineens als nieuwe kaart tevoorschijn.
        a, b = self.trade(1, created="2026-10-05T09:00:00+00:00"), self.trade(2, created="2026-10-05T10:00:00+00:00")
        t = self.tab(kansen.page([a, b], [], [], KINDS, hidden={"signal:1", "signal:2"}), "zone_radar")
        self.assertEqual(t["trades"], [])
        self.assertEqual([(h["key"], h["keys"]) for h in t["hidden"]], [("signal:1", ["signal:1", "signal:2"])])
        self.assertEqual(t["hidden_label"], "Verborgen (1)")

    def test_verborgen_valt_ook_uit_niet_meer_actief(self):
        p = kansen.page(cards((ZONE, 81200.0)), [], [], KINDS, hidden={"zone:8"})
        self.assertEqual(self.tab(p, "zone_radar")["moot"], [])

    def test_structuurplan_verbergen(self):
        p = kansen.page([], [(STRUCT_CARD, 81.5, "wacht")], [], KINDS, hidden={"structuur:12"})
        t = self.tab(p, "structuur")
        self.assertEqual((t["plans"], [h["key"] for h in t["hidden"]]), ([], ["structuur:12"]))


class HideKeyTests(unittest.TestCase):
    def test_alleen_geldige_sleutels_uniek(self):
        self.assertEqual(kansen.parse_keys(["zone:8", "zone:8", "signal:3", "bla", "structuur:x", 5, "zsweep:2", "setup:1", "structuur:12"]),
                         ["zone:8", "signal:3", "zsweep:2", "setup:1", "structuur:12"])
        self.assertEqual(kansen.parse_keys("zone:8"), ["zone:8"])
        self.assertEqual(kansen.parse_keys(None), [])
        self.assertEqual(len(kansen.parse_keys([f"signal:{i}" for i in range(500)])), kansen.MAX_HIDE)

    def test_tekst_van_de_ongedaan_balk(self):
        self.assertEqual(kansen.hidden_text(["HYPE short"]), "HYPE short verborgen")
        self.assertEqual(kansen.hidden_text(["HYPE short", "ETH long", "SOL long"]), "3 kaarten verborgen")
        self.assertEqual(kansen.hidden_label(0), "")
        self.assertEqual(kansen.hidden_label(2), "Verborgen (2)")


class StructureOriginTests(unittest.TestCase):
    def card(self, kind, direction="long"):
        return {"id": 4, "coin": "SOL", "direction": direction, "kind": kind, "plan": {"level": 100.0, "stop": 99.0},
                "targets": [(102.0, 2.0), (103.0, 3.0)], "chart": ""}

    def test_origin_says_which_shape_broke_in_plain_words(self):
        self.assertEqual(kansen.structure_item(self.card("CHOCH"), 100.5, "wacht")["origin"], "Structuur · hogere bodem, breuk van de laatste top, 30m")
        self.assertEqual(kansen.structure_item(self.card("CHOCH", "short"), 99.5, "wacht")["origin"], "Structuur · lagere top, breuk van de laatste bodem, 30m")
        self.assertEqual(kansen.structure_item(self.card("RANGE"), 100.5, "wacht")["origin"], "Structuur · breuk van een range, 30m")
        self.assertEqual(kansen.structure_item(self.card("LINE"), 100.5, "wacht")["origin"], "Structuur · breuk van een lijn, 30m")


class SharedTimeTests(unittest.TestCase):
    """Het moment waarop een kaart gedeeld werd staat op de kaart, in Nederlandse tijd (de CEO miste het, 29 oktober 2026)."""
    NOW = __import__("datetime").datetime(2026, 10, 29, 12, 0, tzinfo=__import__("datetime").timezone.utc)

    def test_vandaag_alleen_de_tijd(self):
        self.assertEqual(kansen.when_text("2026-10-29T07:58:00+00:00", self.NOW), "08:58")       # CET: UTC + 1

    def test_gisteren_en_eerder(self):
        self.assertEqual(kansen.when_text("2026-10-28T08:15:00+00:00", self.NOW), "gisteren 09:15")
        self.assertEqual(kansen.when_text("2026-10-25T09:04:00+00:00", self.NOW), "25 okt 10:04")      # CET
        self.assertEqual(kansen.when_text("2026-09-24T08:00:00+00:00", self.NOW), "24 sep 10:00")      # CEST: UTC + 2

    def test_zonder_zone_telt_als_utc_en_zonder_tijd_is_leeg(self):
        self.assertEqual(kansen.when_text("2026-10-29T07:58:00", self.NOW), "08:58")
        self.assertEqual(kansen.when_text(None, self.NOW), "")
        self.assertEqual(kansen.when_text("geen tijd", self.NOW), "")

    def test_poc_kaart_kan_verborgen_worden(self):
        self.assertEqual(kansen.parse_keys(["poc:7", "zone:3", "poc:x"]), ["poc:7", "zone:3"])
