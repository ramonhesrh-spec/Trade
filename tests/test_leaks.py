"""Lekken per soort (app/leaks.py): tellingen uit kaarten, signalen, dagcap, vertraging en auto-missers over een venster."""
import unittest
from datetime import datetime, timedelta, timezone

from app import leaks, repo
from tests.test_samenval import DbCase

NOW = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)


def ago(days: float = 0, hours: float = 0) -> str:
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


def signal(trade_type, outcome, price=100.0, stop=99.0, take=102.0, created=None, **kw):
    return {"id": kw.pop("id", 1), "trade_type": trade_type, "auto_outcome": outcome, "price": price, "stop_loss": stop, "take_profit": take,
            "created_at": created or ago(1), "auto_outcome_at": ago(0.5), "direction": "long", "coin": "BTC", "message_id": None,
            "r_override": None, "mae_r": kw.get("mae_r"), "mfe_r": 0.5 if kw.pop("mae_r", None) is not None else None, "funding_r": None, "funding_status": None, **kw}


class PerKindTest(unittest.TestCase):
    def setUp(self):
        self.inputs = {
            "cards": [
                {"kind": "zone_radar", "state": "filled", "created_at": ago(1)},
                {"kind": "zone_radar", "state": "zone_weg", "created_at": ago(2)},
                {"kind": "zone_radar", "state": "zone_weg", "created_at": ago(3)},
                {"kind": "zone_radar", "state": "waiting", "created_at": ago(1)},
                {"kind": "zone_radar", "state": "filled", "created_at": ago(20)},            # alleen in het venster van 30 dagen
                {"kind": "structuur", "state": "fired", "created_at": ago(1)},
            ],
            "signals": [
                signal("zone_radar", "take_profit", id=1, mae_r=0.4),
                signal("zone_radar", "stop_loss", id=2, mae_r=1.0),
                signal("zone_radar", None, id=3),
                signal("structuur_c", "stop_loss", id=4),
            ],
            "cap_holds": [{"engine": "zone_radar", "at": ago(1)}, {"engine": "zone_radar", "at": ago(10)}],
            "timings": [{"trade_type": "zone_radar", "ok": 1, "candle_at": ago(hours=1), "detected_at": ago(hours=1), "sent_at": (NOW - timedelta(hours=1) + timedelta(seconds=90)).isoformat()}],
            "missers": [
                {"begin_at": ago(1), "seen_by": [], "reasons": {"zone_radar": "zone_radar: geen actieve vraagzone bij het beginpunt (dichtstbij 3,1% ervandaan)"}},
                {"begin_at": ago(2), "seen_by": [], "reasons": {"zone_radar": "zone_radar: geen actieve vraagzone bij het beginpunt (dichtstbij 7,0% ervandaan)"}},
                {"begin_at": ago(2), "seen_by": ["zone_radar"], "reasons": {}},
            ],
            "stop_then_target": {2: True},
        }

    def test_tellingen_zone_radar_zeven_dagen(self):
        z = leaks.per_kind(self.inputs, NOW, 7)["zone_radar"]
        self.assertEqual(z["kaarten"], 4)
        self.assertEqual(z["gevuld"], 1)
        self.assertEqual(z["wachtend"], 1)
        self.assertEqual(z["vervallen"], {"zone_weg": {"n": 2, "tekst": "De zone is gebroken of te oud geworden."}})
        self.assertEqual(z["afgerond"], 2)
        cost = 0.06 / 1.0                                   # 0,06% kosten op een stop van 1%
        self.assertAlmostEqual(z["netto_r"], ((2.0 - cost) + (-1.0 - cost)) / 2)
        self.assertEqual(z["stop_dan_doel"], {"gecontroleerd": 1, "toch_doel": 1})
        self.assertEqual(z["mae_mediaan_winnaars"], 0.4)
        self.assertEqual(z["mae_mediaan_verliezers"], 1.0)
        self.assertEqual(z["dagcap"], 1)
        self.assertEqual(z["vertraging"]["median_s"], 90.0)
        self.assertEqual(z["missers"], {"n": 2, "redenen": {"zone_radar: geen actieve vraagzone bij het beginpunt": 2}})

    def test_dertig_dagen_telt_meer(self):
        z = leaks.per_kind(self.inputs, NOW, 30)["zone_radar"]
        self.assertEqual(z["kaarten"], 5)
        self.assertEqual(z["dagcap"], 2)

    def test_structuur_telt_ook_structuur_c(self):
        s = leaks.per_kind(self.inputs, NOW, 7)["structuur"]
        self.assertEqual((s["kaarten"], s["gevuld"], s["afgerond"]), (1, 1, 1))
        self.assertIsNone(s["vertraging"])

    def test_lege_soort(self):
        p = leaks.per_kind(self.inputs, NOW, 7)["poc_radar"]
        self.assertEqual((p["kaarten"], p["afgerond"], p["netto_r"]), (0, 0, None))


class RepoInputsTest(DbCase):
    def test_leest_alle_bronnen(self):
        self.insert_signal(trade_type="zone_radar")
        repo.record_cap_hold("zone_radar", "BTC:k", NOW.isoformat())
        got = repo.leak_inputs((NOW - timedelta(days=30)).isoformat())
        self.assertEqual(set(got), {"cards", "signals", "cap_holds", "timings", "missers"})
        self.assertEqual(len(got["cap_holds"]), 1)


if __name__ == "__main__":
    unittest.main()
