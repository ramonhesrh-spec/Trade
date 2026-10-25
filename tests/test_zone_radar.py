"""Zone-radar (app/zone_radar.py en app/zone_radar_live.py) op synthetische candles: welke zones actief zijn, het plan (limiet op de binnenrand,
stop voorbij de buitenrand met ATR en floor_stop, doel op de rand van de tegenovergestelde zone, minimaal 2R) en de motor met meldingen en vulling."""
import asyncio
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from app import config, db, radar, repo, security, smc_eval
from app import zone_radar as zr
from app import zone_radar_live as live

START = pd.Timestamp("2026-10-01T00:00:00Z")
HOUR = pd.Timedelta(hours=1)


def _flat(level: float, n: int) -> list[tuple]:
    """Kleine wisselende candles rond een niveau: te klein om zelf een zone te maken."""
    rows = []
    for i in range(n):
        o, c = (level - 0.05, level + 0.05) if i % 2 else (level + 0.05, level - 0.05)
        rows.append((o, max(o, c) + 0.1, min(o, c) - 0.1, c))
    return rows


def frame(rows: list[tuple], start: pd.Timestamp = START, step: pd.Timedelta = HOUR) -> pd.DataFrame:
    return pd.DataFrame([{"timestamp": start + i * step, "open": o, "high": h, "low": low, "close": c, "volume": 1.0}
                         for i, (o, h, low, c) in enumerate(rows)])


def tia_like() -> pd.DataFrame:
    """Aanbodzone 109,9-110,3 (groene candle vóór een val), vraagzone 103,7-104,1 (rode candle vóór een stijging), koers 106,5 ertussen."""
    rows = _flat(110.0, 60)
    rows.append((110.0, 110.3, 109.9, 110.2))          # aanbod: laatste groene candle
    rows.append((110.2, 110.2, 103.9, 104.0))          # val ruim meer dan 1 ATR onder zijn laag
    rows += _flat(104.0, 18)
    rows.append((104.0, 104.1, 103.7, 103.8))          # vraag: laatste rode candle
    rows.append((103.8, 106.6, 103.8, 106.5))          # stijging ruim meer dan 1 ATR boven zijn hoog
    rows += _flat(106.5, 18)
    return frame(rows)


def now_after(df: pd.DataFrame) -> pd.Timestamp:
    return df["timestamp"].iloc[-1] + HOUR


class ActiveZoneTests(unittest.TestCase):
    def test_vindt_de_vraag_en_aanbodzone(self):
        df = tia_like()
        zones = zr.active_zones(df, "1h", now_after(df))
        kinds = {z.kind: (z.low, z.high) for z in zones}
        self.assertEqual(kinds, {"bear": (109.9, 110.3), "bull": (103.7, 104.1)})

    def test_candle_die_nog_vormt_telt_niet(self):
        df = tia_like()
        breach = frame([(106.5, 106.5, 100.0, 100.5)], start=now_after(df))     # slot onder de vraagzone, maar nog niet gesloten
        both = pd.concat([df, breach], ignore_index=True)
        forming = zr.active_zones(both, "1h", now_after(df) + pd.Timedelta(minutes=30))
        self.assertIn("bull", {z.kind for z in forming})
        closed = zr.active_zones(both, "1h", now_after(df) + HOUR)
        self.assertNotIn("bull", {z.kind for z in closed})       # gesloten onder de buitenrand: de zone is doorbroken

    def test_te_weinig_candles_geeft_niets(self):
        df = tia_like().head(30)
        self.assertEqual(zr.active_zones(df, "1h", now_after(df)), [])


def Z(kind, low, high, tf="1h", atr=0.4):
    return zr.ZoneLevel(tf, kind, low, high, atr, f"{tf}:{kind}:{low}")


class PlanTests(unittest.TestCase):
    def test_long_en_short_op_de_synthetische_grafiek(self):
        df = tia_like()
        zones = zr.active_zones(df, "1h", now_after(df))
        by_dir = {p["direction"]: p for p in zr.plans(zones, 106.5)}
        long, short = by_dir["long"], by_dir["short"]
        self.assertEqual(long["limit"], 104.1)
        self.assertEqual(long["take_profit"], 109.9)                # onderrand van de aanbodzone
        self.assertLess(long["stop_loss"], 103.7)
        self.assertGreaterEqual(long["rr"], zr.MIN_RR)
        self.assertEqual(short["limit"], 109.9)
        self.assertEqual(short["take_profit"], 104.1)               # bovenrand van de vraagzone
        self.assertGreater(short["stop_loss"], 110.3)

    def test_stop_een_kwart_atr_voorbij_de_buitenrand(self):
        p = zr.plan_for("long", [Z("bull", 90.0, 95.0, atr=2.0), Z("bear", 120.0, 121.0)], 98.0)
        self.assertAlmostEqual(p["stop_loss"], 90.0 - 0.25 * 2.0)
        p = zr.plan_for("short", [Z("bear", 105.0, 110.0, atr=2.0), Z("bull", 80.0, 81.0)], 102.0)
        self.assertAlmostEqual(p["stop_loss"], 110.0 + 0.25 * 2.0)

    def test_te_krappe_stop_wordt_verbreed_niet_geweigerd(self):
        p = zr.plan_for("long", [Z("bull", 99.98, 100.0, atr=0.001), Z("bear", 110.0, 111.0)], 102.0)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p["stop_loss"], smc_eval.floor_stop("long", 100.0, 99.98 - 0.25 * 0.001))
        if config.SMC_MIN_STOP_PCT > 0:
            self.assertAlmostEqual(p["stop_loss"], 100.0 * (1 - config.SMC_MIN_STOP_PCT / 100))

    def test_zone_verder_dan_de_vaste_afstand_geeft_geen_kaart(self):
        far = 100.0 * (1 - (zr.MAX_DISTANCE_PCT + 0.5) / 100)
        self.assertIsNone(zr.plan_for("long", [Z("bull", far - 1, far), Z("bear", 130.0, 131.0)], 100.0))
        near = 100.0 * (1 - (zr.MAX_DISTANCE_PCT - 0.5) / 100)
        self.assertIsNotNone(zr.plan_for("long", [Z("bull", near - 1, near), Z("bear", 130.0, 131.0)], 100.0))

    def test_onder_2r_geen_kaart(self):
        # risico ~1,6 (95 -> 93,4), doel 97: 1,25R
        self.assertIsNone(zr.plan_for("long", [Z("bull", 93.5, 95.0), Z("bear", 97.0, 98.0)], 96.0))

    def test_zonder_tegenovergestelde_zone_geen_kaart(self):
        self.assertIsNone(zr.plan_for("long", [Z("bull", 93.5, 95.0)], 96.0))

    def test_alleen_de_dichtstbijzijnde_zone_telt(self):
        # De dichtste vraagzone haalt geen 2R; een verdere wel. Er wordt niet doorgezocht.
        zones = [Z("bull", 98.0, 99.0), Z("bull", 94.0, 94.5), Z("bear", 100.5, 101.0)]
        self.assertIsNone(zr.plan_for("long", zones, 99.5))

    def test_koers_in_de_zone_is_geen_wachtende_kaart(self):
        self.assertIsNone(zr.plan_for("long", [Z("bull", 95.0, 100.0), Z("bear", 120.0, 121.0)], 99.0))


class WalkTests(unittest.TestCase):
    def c(self, rows):
        return frame(rows, step=pd.Timedelta(minutes=5))

    def test_vulling_doel_en_niets(self):
        self.assertEqual(zr.walk("long", 100.0, 110.0, self.c([(101, 102, 100.5, 101), (101, 101, 99.9, 100)]))[0], "filled")
        self.assertEqual(zr.walk("long", 100.0, 110.0, self.c([(101, 110.5, 100.5, 109)]))[0], "doel_geraakt")
        self.assertEqual(zr.walk("short", 110.0, 100.0, self.c([(109, 110.0, 108, 109)]))[0], "filled")
        self.assertEqual(zr.walk("long", 100.0, 110.0, self.c([(101, 102, 100.5, 101)])), (None, None))

    def test_raakt_een_candle_beide_dan_telt_de_vulling(self):
        self.assertEqual(zr.walk("long", 100.0, 110.0, self.c([(105, 111, 99, 105)]))[0], "filled")


class RadarCardTests(unittest.TestCase):
    def test_kaart_met_eigen_sleutel_en_plan(self):
        row = {"id": 5, "coin": "TIA", "direction": "long", "tf": "1h", "zone_low": 0.6008, "zone_high": 0.6083, "stop_loss": 0.5853,
               "take_profit": 0.7547, "created_at": "2026-10-21T10:00:00+00:00"}
        card = radar.setup_card(zr.radar_setup(row), 0.63)
        self.assertEqual(card["key"], "zone:5")
        self.assertEqual(card["plan"].limit, 0.6083)
        self.assertEqual(card["state"], "wacht")
        self.assertGreater(card["plan"].rr, 2)
        self.assertIsNotNone(card["chart"]["zone"])                       # tf bekend, sleutel ontbreekt: zone zonder herkomst
        self.assertIsNone(card["chart"]["zone"]["origin"])


class ChartZoneTests(unittest.TestCase):
    ROW = {"direction": "long", "tf": "1h", "zone_key": "4h:bull:2026-10-20T08:00:00+00:00", "target_tf": "4h",
           "target_low": 0.75, "target_high": 0.77}

    def test_herkomst_uit_de_sleutel(self):
        self.assertEqual(zr.zone_origin("4h:bull:2026-10-20T08:00:00+00:00"), ("4h", "bull", 1792483200))
        self.assertEqual(zr.zone_origin("1h:bear:2026-10-20T08:00:00"), ("1h", "bear", 1792483200))     # zonder tijdzone = UTC
        for bad in ("", "1h:bear:a", "2h:bull:2026-10-20T08:00:00", "1h:x:2026-10-20T08:00:00", None):
            self.assertIsNone(zr.zone_origin(bad))

    def test_zone_voor_de_grafiek(self):
        z = zr.chart_zone(self.ROW)
        self.assertEqual((z["tf"], z["kind"], z["label"], z["origin"]), ("4h", "bull", "Vraagzone 4u", 1792483200))
        self.assertEqual((z["target_low"], z["target_high"], z["target_label"]), (0.75, 0.77, "Doelzone 4u"))
        self.assertIn("dalende 4u-candle", z["note"])
        self.assertIn("omhoog", z["note"])
        short = zr.chart_zone({**self.ROW, "direction": "short", "zone_key": "1h:bear:2026-10-20T08:00:00+00:00"})
        self.assertEqual(short["label"], "Aanbodzone 1u")
        self.assertIn("stijgende 1u-candle", short["note"])

    def test_zonder_bruikbare_sleutel_geen_marker_en_zonder_doelzone_geen_vlak(self):
        z = zr.chart_zone({"direction": "long", "tf": "1h", "zone_key": "1h:bull:a"})
        self.assertEqual(z["tf"], "1h")
        self.assertIsNone(z["origin"])
        self.assertIsNone(z["note"])
        self.assertIsNone(z["target_low"])
        self.assertIsNone(zr.chart_zone({"direction": "long", "tf": "15m"}))

    def test_open_signaal_heeft_geen_zone(self):
        card = radar.signal_card({"id": 1, "coin": "BTC", "direction": "long", "price": 100.0, "stop_loss": 97.0, "take_profit": 106.0,
                                  "created_at": "2026-10-21T10:00:00+00:00"}, 101.0)
        self.assertIsNone(card["chart"]["zone"])


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patches = [mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "z.db")),
                   mock.patch.object(config, "ZONE_RADAR_ENABLED", True),
                   mock.patch.object(repo, "list_coins", return_value=[{"symbol": "TIA"}])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        db.init_db()
        repo.create_user("a", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        from app import push_notify
        for name, kw in (("send_push", {"new": mock.AsyncMock()}), ("is_quiet_now", {"return_value": False})):
            p = mock.patch.object(push_notify, name, **kw)
            setattr(self, name, p.start())
            self.addCleanup(p.stop)
        self.h1 = tia_like()
        self.now = now_after(self.h1)
        self.m5 = frame([(106.5, 106.6, 106.4, 106.5)] * 3, start=self.now, step=pd.Timedelta(minutes=5))

    def fetch(self, coin, timeframe="1h", limit=200, since=None):
        if timeframe == "5m":
            return self.m5
        return self.h1 if timeframe == "1h" else self.h1.iloc[:0]

    def run_once(self):
        from app import exchange
        with mock.patch.object(exchange, "fetch_ohlcv", side_effect=self.fetch):
            asyncio.run(live.run(self.now.to_pydatetime()))

    def titles(self):
        return [c.args[1] for c in self.send_push.call_args_list]

    def test_nieuwe_kaart_meldt_een_keer_en_vulling_wordt_een_signaal(self):
        self.run_once()
        cards = repo.list_zone_radar_setups()
        self.assertEqual({c["direction"] for c in cards}, {"long", "short"})
        self.assertEqual(sum("Zone-radar · ongetest" in t for t in self.titles()), 1)     # long en short: de conflictregel laat er één door
        self.run_once()
        self.assertEqual(len(repo.list_zone_radar_setups(("waiting", "filled", "doel_geraakt", "zone_weg"))), 2)
        self.assertEqual(sum("Zone-radar · ongetest" in t for t in self.titles()), 1)     # geen tweede melding voor dezelfde kaart

        long = next(c for c in cards if c["direction"] == "long")
        later = self.now + pd.Timedelta(hours=1)
        self.m5 = frame([(105.0, 105.0, 104.0, 104.5)], start=later, step=pd.Timedelta(minutes=5))   # raakt de limiet 104,1
        self.now = later + pd.Timedelta(minutes=10)
        self.run_once()
        self.run_once()
        filled = repo.list_zone_radar_setups(("filled",))
        self.assertEqual([c["id"] for c in filled], [long["id"]])
        with db.session() as conn:
            signals = [dict(r) for r in conn.execute("SELECT trade_type, price, stop_loss, take_profit FROM signals")]
            journal = conn.execute("SELECT COUNT(*) AS n FROM journal_entries").fetchone()["n"]
        self.assertEqual(signals, [{"trade_type": "zone_radar", "price": 104.1, "stop_loss": long["stop_loss"], "take_profit": 109.9}])
        self.assertEqual(journal, 1)
        self.assertEqual(sum("Zone-radar gevuld" in t for t in self.titles()), 1)

    def test_dagcap_op_nieuwe_kaarten(self):
        with mock.patch.object(config, "ZONE_RADAR_MAX_PER_DAY", 1):
            self.run_once()
        self.assertEqual(len(repo.list_zone_radar_setups()), 1)

    def test_doel_eerst_geraakt_vervalt_stil(self):
        self.run_once()
        self.m5 = frame([(108.0, 110.0, 107.5, 109.95)], start=self.now + HOUR, step=pd.Timedelta(minutes=5))   # long-doel 109,9, short-limiet 109,9
        self.now += 2 * HOUR
        self.run_once()
        states = {c["direction"]: c["state"] for c in repo.list_zone_radar_setups(("waiting", "filled", "doel_geraakt", "zone_weg"))}
        self.assertEqual(states["long"], "doel_geraakt")
        self.assertEqual(states["short"], "filled")

    def test_doorbroken_zone_vervalt(self):
        self.run_once()
        self.h1 = pd.concat([self.h1, frame([(106.5, 106.5, 100.0, 100.5)], start=self.now)], ignore_index=True)
        self.m5 = frame([(106.5, 106.6, 106.4, 106.5)], start=self.now, step=pd.Timedelta(minutes=5))
        self.now += HOUR
        with mock.patch.object(zr, "walk", return_value=(None, None)):      # alleen het opruimen bekijken, niet de vulling onderweg
            self.run_once()
        states = {c["direction"]: c["state"] for c in repo.list_zone_radar_setups(("waiting", "filled", "doel_geraakt", "zone_weg"))}
        self.assertEqual(states["long"], "zone_weg")


    def test_kaart_bewaart_de_marktcontext_van_zijn_ontstaan(self):
        at = self.now.isoformat()
        repo.add_market_context([("TIA", "binance", "funding_8h", 0.06, at), ("TIA", "binance", "oi_change_24h", 3.5, at),
                                 ("TIA", "hyperliquid", "funding_8h", 0.02, at)])
        self.run_once()
        cards = repo.list_zone_radar_setups()
        self.assertEqual({c["direction"] for c in cards}, {"long", "short"})        # dezelfde kaarten als zonder context: hij beslist niets
        long = next(c for c in cards if c["direction"] == "long")
        self.assertEqual((long["ctx_funding"], long["ctx_oi_change_24h"], long["ctx_spread"]), (0.06, 3.5, 0.04))

        later = self.now + pd.Timedelta(hours=1)
        repo.add_market_context([("TIA", "binance", "funding_8h", -0.09, later.isoformat())])
        self.m5 = frame([(105.0, 105.0, 104.0, 104.5)], start=later, step=pd.Timedelta(minutes=5))
        self.now = later + pd.Timedelta(minutes=10)
        self.run_once()
        filled = repo.list_zone_radar_setups(("filled",))[0]
        self.assertEqual(filled["ctx_funding"], 0.06)                                 # de vulling overschrijft de stand bij het ontstaan niet
        rows = [r for r in repo.list_signals_for_quality_report(None) if r["trade_type"] == "zone_radar"]
        self.assertEqual([r["ctx_funding"] for r in rows], [0.06])

    def test_oude_context_wordt_niet_als_stand_bewaard(self):
        repo.add_market_context([("TIA", "binance", "funding_8h", 0.06, (self.now - pd.Timedelta(hours=3)).isoformat())])
        self.run_once()
        self.assertEqual({c["ctx_funding"] for c in repo.list_zone_radar_setups()}, {None})


if __name__ == "__main__":
    unittest.main()
