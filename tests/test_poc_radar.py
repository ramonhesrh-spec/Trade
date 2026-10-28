"""De kaart van de POC-radar (app/poc_radar.py): de dichtstbijzijnde naakte POC aan elke kant binnen 6%, limiet op de POC, stop een kwart ATR
erachter, doel de eerstvolgende POC of zonerand met minstens 2R, anders geen doel. Nooit doorzoeken naar een verder niveau."""
import unittest

import pandas as pd

from app import config, poc, poc_radar as pr
from app.zone_radar import ZoneLevel
from unittest import mock

T0 = pd.Timestamp("2026-10-20T00:00:00Z")


def lv(price, period="day", days=0, touched=None):
    return poc.PocLevel(period, T0 + pd.Timedelta(days=days), price, touched)


class PlanTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(config, "SMC_MIN_STOP_PCT", 0.2)
        p.start()
        self.addCleanup(p.stop)

    def test_long_onder_de_koers_short_erboven(self):
        levels = [lv(97.0), lv(103.0, days=1)]
        plans = pr.plans(levels, [], 100.0, 4.0)
        self.assertEqual({p["direction"] for p in plans}, {"long", "short"})
        long = next(p for p in plans if p["direction"] == "long")
        self.assertEqual(long["limit_price"], 97.0)
        self.assertAlmostEqual(long["stop_loss"], 96.0)          # 97 - 0,25 x 4, ruimer dan de vloer van 0,2%
        self.assertEqual(long["level_key"], "day:2026-10-20T00:00:00+00:00")

    def test_stop_krijgt_de_vloer(self):
        long = pr.plan_for("long", [lv(97.0)], [], 100.0, 0.01)
        self.assertAlmostEqual(long["stop_loss"], 97.0 * (1 - 0.002))

    def test_alleen_naakt_en_binnen_zes_procent(self):
        self.assertIsNone(pr.plan_for("long", [lv(93.9)], [], 100.0, 4.0))
        self.assertIsNone(pr.plan_for("long", [lv(97.0, touched=T0 + pd.Timedelta(days=2))], [], 100.0, 4.0))
        self.assertEqual(pr.plan_for("long", [lv(94.1, "week")], [], 100.0, 4.0)["period"], "week")

    def test_doel_eerstvolgende_poc_met_2r(self):
        # risico 97 - 96 = 1; doel 103 (ook een geraakte POC telt als doel)
        levels = [lv(97.0), lv(103.0, days=1, touched=T0 + pd.Timedelta(days=3)), lv(105.0, days=2)]
        long = pr.plan_for("long", levels, [], 100.0, 4.0)
        self.assertEqual(long["take_profit"], 103.0)
        self.assertEqual(long["target_kind"], "poc")
        self.assertAlmostEqual(long["rr"], 6.0)

    def test_doel_zonerand_als_die_eerder_komt(self):
        zone = ZoneLevel("4h", "bear", 101.0, 102.0, 1.0, "4h:bear:2026-10-19T00:00:00+00:00")
        long = pr.plan_for("long", [lv(97.0), lv(103.0, days=1)], [zone], 100.0, 4.0)
        self.assertEqual(long["take_profit"], 101.0)
        self.assertEqual((long["target_kind"], long["target_tf"], long["target_low"], long["target_high"]), ("zone", "4h", 101.0, 102.0))

    def test_eerste_doel_onder_2r_geeft_geen_doel_en_zoekt_niet_verder(self):
        # risico 1 (stop 96); het eerste niveau boven de koers is 97,15 en haalt geen 2R. 103 wel, maar telt niet.
        levels = [lv(97.0), lv(97.15, days=1, touched=T0 + pd.Timedelta(days=3)), lv(103.0, days=2)]
        long = pr.plan_for("long", levels, [], 97.1, 4.0)
        self.assertIsNone(long["take_profit"])
        self.assertIsNone(long["rr"])
        self.assertIsNone(long["target_kind"])

    def test_dichtstbijzijnde_telt_ook_als_hij_geen_doel_heeft(self):
        long = pr.plan_for("long", [lv(98.0), lv(96.0, days=1)], [], 100.0, 4.0)
        self.assertEqual(long["limit_price"], 98.0)

    def test_short_spiegel(self):
        short = pr.plan_for("short", [lv(103.0), lv(97.0, days=1)], [], 100.0, 4.0)
        self.assertEqual((short["limit_price"], short["take_profit"]), (103.0, 97.0))
        self.assertAlmostEqual(short["stop_loss"], 104.0)


class WalkTests(unittest.TestCase):
    def candles(self, rows, start=T0):
        return pd.DataFrame([{"timestamp": start + i * poc.BAR, "open": o, "high": h, "low": low, "close": c} for i, (o, h, low, c) in enumerate(rows)])

    def test_vulling_bij_aanraking(self):
        what, at = pr.walk("long", 97.0, 103.0, self.candles([(99, 99.5, 98, 98.5), (98.5, 98.6, 96.9, 97.2)]))
        self.assertEqual((what, at), ("filled", T0 + poc.BAR))

    def test_doel_eerst(self):
        self.assertEqual(pr.walk("long", 97.0, 103.0, self.candles([(100, 103.5, 99, 103)]))[0], "doel_geraakt")

    def test_zonder_doel_alleen_vulling(self):
        self.assertEqual(pr.walk("short", 103.0, None, self.candles([(100, 102, 90, 91)]))[0], None)
        self.assertEqual(pr.walk("short", 103.0, None, self.candles([(100, 103.0, 99, 101)]))[0], "filled")


class TextTests(unittest.TestCase):
    ROW = {"id": 4, "coin": "BTC", "direction": "long", "period": "day", "period_start": "2026-10-20T00:00:00+00:00",
           "level_key": "day:2026-10-20T00:00:00+00:00", "level": 97.0, "limit_price": 97.0, "stop_loss": 96.9, "take_profit": 103.0, "rr": 60.0,
           "target_kind": "poc", "target_text": "dag-POC 21 okt", "target_tf": None, "target_low": None, "target_high": None,
           "created_at": "2026-10-22T10:00:00+00:00", "expires_at": "2026-10-25T10:00:00+00:00"}

    def test_periode_tekst(self):
        self.assertEqual(poc.period_text("day", T0), "dag-POC 20 okt")
        self.assertEqual(poc.period_text("week", pd.Timestamp("2026-10-19T00:00:00Z")), "week-POC week 43")

    def test_radar_setup_is_een_kaart_met_eigen_sleutel(self):
        from app import radar
        card = radar.setup_card(pr.radar_setup(self.ROW), 100.0)
        self.assertEqual(card["key"], "poc:4")
        self.assertEqual(card["plan"].limit, 97.0)
        self.assertEqual(card["state"], "wacht")

    def test_teksten_zonder_advies(self):
        body = pr.new_card_body(self.ROW)
        self.assertIn("Ongetest", body)
        self.assertIn("dag-POC 20 okt", body)
        row = pr.signal_row(self.ROW, 97.0)
        self.assertEqual((row["trade_type"], row["price"], row["take_profit"]), ("poc_radar", 97.0, 103.0))
        no_target = pr.new_card_body({**self.ROW, "take_profit": None, "rr": None, "target_kind": None})
        self.assertIn("geen doel", no_target)
        for text in (body, no_target, pr.fill_body(self.ROW, 97.0), row["plain_explanation"]):
            for word in ("koop", "verkoop", "zal stijgen", "zal dalen"):
                self.assertNotIn(word, text.lower())


if __name__ == "__main__":
    unittest.main()
