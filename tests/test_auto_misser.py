"""Automatische missers (app/auto_misser.py): grote omkeringen op gesloten 1u-candles en of een live motor er rond het begin een kaart had."""
import json
import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from app import auto_misser as am, repo
from tests.test_samenval import DbCase

T0 = pd.Timestamp("2026-10-30T00:00:00Z")


def bars_with_move(rise: float, n_flat: int = 40, direction: str = "long") -> pd.DataFrame:
    """Vlakke candles met een bereik van 1 (ATR ongeveer 1), dan een bodem (long) of top (short) en een beweging van `rise` vanaf dat punt."""
    rows = []
    sign = 1 if direction == "long" else -1
    for i in range(n_flat):
        rows.append((100.0, 100.5, 99.5, 100.0))
    # het swing-punt: een halve eenheid voorbij de vlakke candles
    rows.append((100.0, 100.5, 99.0, 99.5) if direction == "long" else (100.0, 101.0, 99.5, 100.5))
    pivot = 99.0 if direction == "long" else 101.0
    steps = 8
    for k in range(1, steps + 1):
        top = pivot + sign * rise * k / steps
        lo, hi = (max(top - 0.6, pivot + 0.01), top) if direction == "long" else (top, min(top + 0.6, pivot - 0.01))
        rows.append((lo + 0.3, hi, lo, lo + 0.3))
    for _ in range(6):                                  # rustig uitlopen, zodat het swing-punt bevestigd is
        last = pivot + sign * rise
        lo, hi = (last - 0.9, last - 0.3) if direction == "long" else (last + 0.3, last + 0.9)
        rows.append((lo + 0.3, hi, lo, lo + 0.3))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["volume"] = 1.0
    df.insert(0, "timestamp", [T0 + pd.Timedelta(hours=i) for i in range(len(df))])
    return df


def now_after(df: pd.DataFrame) -> pd.Timestamp:
    return df["timestamp"].iloc[-1] + pd.Timedelta(hours=1)


class FindMovesTest(unittest.TestCase):
    def test_omkeer_van_drie_atr_telt(self):
        df = bars_with_move(4.0)
        moves = am.find_moves(df, now_after(df))
        self.assertEqual(len(moves), 1)
        m = moves[0]
        self.assertEqual(m["direction"], "long")
        self.assertEqual(m["begin_at"], (T0 + pd.Timedelta(hours=40)).isoformat())
        self.assertGreaterEqual(m["size_atr"], am.MIN_MOVE_ATR)
        self.assertAlmostEqual(m["size_pct"], (m["end_price"] - m["begin_price"]) / m["begin_price"] * 100)

    def test_omkeer_van_twee_atr_telt_niet(self):
        df = bars_with_move(2.0)
        self.assertEqual(am.find_moves(df, now_after(df)), [])

    def test_short_gespiegeld(self):
        df = bars_with_move(4.0, direction="short")
        moves = am.find_moves(df, now_after(df))
        self.assertEqual([m["direction"] for m in moves], ["short"])

    def test_alleen_gesloten_candles(self):
        """De candle die nog vormt telt niet: met `now` vóór het slot van de bevestigende candles is het swing-punt nog niet bevestigd."""
        df = bars_with_move(4.0)
        early = T0 + pd.Timedelta(hours=40 + am.PIVOT_BARS)       # de derde candle na het swing-punt is nog niet gesloten
        self.assertEqual(am.find_moves(df, early), [])

    def test_buiten_het_venster_valt_af(self):
        df = bars_with_move(4.0)
        self.assertEqual(am.find_moves(df, now_after(df) + pd.Timedelta(hours=48), lookback_hours=24), [])


class SeenTest(unittest.TestCase):
    def test_kaart_binnen_twaalf_uur_is_gezien(self):
        move = {"direction": "long", "begin_at": "2026-10-30T10:00:00+00:00"}
        rows = [{"source": "zone_radar", "direction": "long", "at": "2026-10-30T00:30:00+00:00"},
                {"source": "poc_radar", "direction": "short", "at": "2026-10-30T10:00:00+00:00"},
                {"source": "structuur", "direction": "long", "at": "2026-10-29T20:00:00+00:00"}]
        self.assertEqual(am.seen_by(move, rows), ["zone_radar"])


class RepoTest(DbCase):
    def test_gemelde_kaart_wordt_herkend(self):
        from app import db
        with db.session() as conn:
            conn.execute("""INSERT INTO zone_radar_setups (coin, direction, tf, zone_key, zone_low, zone_high, stop_loss, take_profit, rr, atr,
                            target_tf, target_low, target_high, state, created_at)
                            VALUES ('BTC', 'long', '1h', 'k', 1, 2, 0.9, 3, 1, 0.1, '1h', 3, 3.1, 'waiting', '2026-10-30T05:00:00+00:00')""")
        rows = repo.auto_misser_seen_rows("BTC", "2026-10-29T22:00:00+00:00", "2026-10-30T22:00:00+00:00")
        move = {"direction": "long", "begin_at": "2026-10-30T10:00:00+00:00"}
        self.assertEqual(am.seen_by(move, rows), ["zone_radar"])

    def test_signaal_telt_als_gezien_en_geen_plan_niet(self):
        self.insert_signal(coin="ETH", direction="short", trade_type="zone_sweep")
        rows = repo.auto_misser_seen_rows("ETH", "2000-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00")
        self.assertEqual({r["source"] for r in rows}, {"signaal:zone_sweep"})

    def test_opslaan_is_idempotent(self):
        row = {"coin": "BTC", "direction": "long", "begin_at": "2026-10-30T10:00:00+00:00", "end_at": "2026-10-30T18:00:00+00:00",
               "begin_price": 99.0, "end_price": 103.0, "size_atr": 4.0, "size_pct": 4.04, "seen_by": [], "reasons": {"structuur": "geen breuk"}}
        repo.save_auto_misser(row, "2026-10-31T03:17:00+00:00")
        repo.save_auto_misser({**row, "reasons": {"structuur": "anders"}}, "2026-11-01T03:17:00+00:00")
        found = repo.list_auto_missers("2026-10-01T00:00:00+00:00")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["reasons"], {"structuur": "anders"})
        self.assertEqual(found[0]["seen_by"], [])


class ScriptTest(DbCase):
    def test_misser_krijgt_redenen_en_gezien_niet(self):
        import importlib
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        script = importlib.import_module("auto_misser")
        df = bars_with_move(4.0)
        fetch = lambda coin, timeframe, limit: df
        reasons = {"structuur": lambda coin, move: "structuur: geen breuk", "zone_radar": lambda coin, move: 1 / 0}
        rows = script.run(["BTC"], now_after(df).to_pydatetime(), 24, fetch=fetch, reasons=reasons)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reasons"]["structuur"], "structuur: geen breuk")
        self.assertIn("niet te bepalen", rows[0]["reasons"]["zone_radar"])
        self.assertEqual(len(repo.list_auto_missers("2000-01-01")), 1)
        self.insert_signal(coin="ETH", direction="long", trade_type="zone_radar")
        from app import db
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ?", (rows[0]["begin_at"],))
        seen = script.run(["ETH"], now_after(df).to_pydatetime(), 24, fetch=fetch, reasons=reasons)
        self.assertEqual(seen[0]["seen_by"], ["signaal:zone_radar"])
        self.assertEqual(seen[0]["reasons"], {})


class ReasonTest(unittest.TestCase):
    def test_zone_reden(self):
        from app import zone_radar as zr
        z = zr.ZoneLevel("1h", "bull", 98.0, 99.5, 1.0, "k")
        self.assertIn("actieve vraagzone bij het beginpunt", am.zone_reason("long", [z], 99.0))
        self.assertIn("geen actieve vraagzone", am.zone_reason("long", [], 99.0))

    def test_poc_reden(self):
        from app import poc
        lv = poc.PocLevel("day", pd.Timestamp("2026-10-28T00:00:00Z"), 99.1, None)
        self.assertIn("naakte POC bij het beginpunt", am.poc_reason("long", [lv], 99.0, pd.Timestamp("2026-10-30T10:00:00Z")))
        late = poc.PocLevel("day", pd.Timestamp("2026-10-30T00:00:00Z"), 99.1, None)     # nog niet bekend bij het begin
        self.assertIn("geen naakte POC", am.poc_reason("long", [late], 99.0, pd.Timestamp("2026-10-30T10:00:00Z")))


if __name__ == "__main__":
    unittest.main()
