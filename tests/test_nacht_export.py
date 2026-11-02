"""Nachtelijke export (scripts/nacht_export.py): één JSON en een korte Markdown, zonder persoonsgegevens, en --git pusht alleen naar hespulse-data."""
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app import db, repo
from tests.test_samenval import DbCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
nacht = importlib.import_module("nacht_export")

NOW = datetime(2026, 11, 1, 3, 17, tzinfo=timezone.utc)
PERSONAL_KEYS = ("username", "email", "e-mail", "password", "password_hash", "telegram_chat_id", "endpoint", "p256dh", "auth", "user_id",
                 "quiet_hours_start", "subscription")


def keys_of(value) -> set:
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_of(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(keys_of(v) for v in value)) if value else set()
    return set()


class ExportTest(DbCase):
    def setUp(self):
        super().setUp()
        repo.create_user("geheimenaam", "pw", 0, 1)
        with db.session() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
            if "email" in cols:
                conn.execute("UPDATE users SET email = 'iemand@voorbeeld.nl'")
            conn.execute("UPDATE users SET telegram_chat_id = '987654321'")
        sid = self.insert_signal(trade_type="zone_radar", coin="BTC")
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ?, auto_outcome = 'stop_loss', auto_outcome_at = ? WHERE id = ?",
                         ("2026-10-30T10:00:00+00:00", "2026-10-30T12:00:00+00:00", sid))
            conn.execute("INSERT INTO alert_timing (user_id, trade_type, event, ref, candle_at, detected_at, sent_at, ok) VALUES (1, 'zone_radar', 'nieuw', 'x', ?, ?, ?, 1)",
                         ("2026-10-30T10:00:00+00:00", "2026-10-30T10:00:30+00:00", "2026-10-30T10:01:00+00:00"))
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)

    def test_geen_persoonsgegevens(self):
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None, fetch_4h=lambda coin: None)
        text = json.dumps(data)
        self.assertNotIn("geheimenaam", text)
        self.assertNotIn("iemand@voorbeeld.nl", text)
        self.assertNotIn("987654321", text)
        self.assertFalse(keys_of(data) & set(PERSONAL_KEYS), keys_of(data) & set(PERSONAL_KEYS))
        self.assertEqual([s["trade_type"] for s in data["signalen"]], ["zone_radar"])
        self.assertIn("zone_radar", data["lekken"]["7d"])

    def test_schaduw_staat_erin(self):
        from app import shadow
        shadow.register("zr-stop-040", "zone_radar", "Stop 0,4 ATR", "reden vooraf", {"stop_atr": 0.4}, NOW)
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None, fetch_4h=lambda coin: None)
        self.assertEqual([(s["id"], s["status"], s["verdict"]["verdict"]) for s in data["schaduw"]], [("zr-stop-040", "schaduw", "wachten")])
        self.assertIn("zr-stop-040", nacht.markdown(data))

    def test_model_staat_erin(self):
        from tests.test_web_model import scenario
        scenario("ADA", entry=True)
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None, fetch_4h=lambda coin: None)
        self.assertEqual(data["model"]["funnel"]["entry"], 1)
        self.assertEqual([c["key"] for c in data["model"]["compare"]], ["V1", "V2", "V3"])
        self.assertIn("## HesPulse-model (ongetest)", nacht.markdown(data))
        self.assertFalse(keys_of(data["model"]) & set(PERSONAL_KEYS))

    def test_context_4u_per_signaal_en_onbekend_zonder_candles(self):
        # H1 (docs/onderzoek/hypotheses.md): elke rij krijgt de groep van de eigen coin en van BTC; zonder candles 'onbekend', nooit 'neutraal'.
        from tests.test_context_split import zigzag
        up = zigzag(True)
        with self.subTest("met candles"):
            with_up = nacht.with_context([{"coin": "BTC", "direction": "long", "created_at": up["timestamp"].iloc[-1].isoformat()}],
                                         fetch=lambda coin: up)
            self.assertEqual((with_up[0]["context_4u"], with_up[0]["btc_4u"]), ("mee", "mee"))
        def boom(coin):
            raise RuntimeError("geen netwerk")
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None, fetch_4h=boom)
        self.assertEqual([(s["context_4u"], s["btc_4u"]) for s in data["signalen"]], [("onbekend", "onbekend")])
        self.assertEqual(data["context_4u"]["zone_radar"]["eigen"]["onbekend"]["n"], 1)
        self.assertIn("## Context 4u (H1, alleen meting)", nacht.markdown(data))

    def test_schrijft_json_en_markdown_met_datum(self):
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None, fetch_4h=lambda coin: None)
        paths = nacht.write_files(data, Path(self.out.name), NOW)
        self.assertEqual(sorted(p.name for p in paths), ["hespulse-2026-11-01.json", "hespulse-2026-11-01.md"])
        md = (Path(self.out.name) / "hespulse-2026-11-01.md").read_text()
        self.assertIn("Zone-radar", md)
        self.assertNotIn("geheimenaam", md)


class StopThenTargetTest(unittest.TestCase):
    def test_stop_die_later_het_doel_haalde(self):
        import pandas as pd
        closed = pd.Timestamp("2026-10-30T12:00:00Z")
        candles = pd.DataFrame({"timestamp": [closed + pd.Timedelta(minutes=5 * i) for i in range(1, 300)], "open": 99.0, "high": 99.5,
                                "low": 98.8, "close": 99.0, "volume": 1.0})
        candles.loc[100, "high"] = 102.5
        sig = {"id": 7, "auto_outcome": "stop_loss", "take_profit": 102.0, "r_override": None, "auto_outcome_at": closed.isoformat(),
               "coin": "BTC", "direction": "long"}
        self.assertEqual(nacht.stop_then_target([sig], NOW, lambda coin, since: candles), {7: True})
        self.assertEqual(nacht.stop_then_target([sig], NOW, lambda coin, since: candles.assign(high=99.5)), {7: False})
        self.assertEqual(nacht.stop_then_target([{**sig, "take_profit": None}], NOW, lambda coin, since: candles), {})
        self.assertEqual(nacht.stop_then_target([sig], closed.to_pydatetime(), lambda coin, since: candles), {})     # 24 uur nog niet voorbij


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class GitTest(unittest.TestCase):
    def test_pusht_alleen_naar_hespulse_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            remote = tmp / "remote.git"
            git("init", "--bare", "-q", str(remote), cwd=tmp)
            seed = tmp / "seed"
            git("init", "-q", "-b", "main", str(seed), cwd=tmp)
            (seed / "code.py").write_text("print(1)\n")
            git("add", ".", cwd=seed)
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "code", cwd=seed)
            git("push", "-q", str(remote), "main", cwd=seed)
            main_before = git("rev-parse", "main", cwd=remote)
            files = []
            for name in ("hespulse-2026-11-01.json", "hespulse-2026-11-01.md"):
                (tmp / name).write_text("{}" if name.endswith("json") else "# x\n")
                files.append(tmp / name)
            work = tmp / "work"
            nacht.push_to_branch(files, work, str(remote), key=None, when=NOW)
            nacht.push_to_branch(files, work, str(remote), key=None, when=NOW)        # tweede keer: niets nieuws, geen fout
            self.assertEqual(git("rev-parse", "main", cwd=remote), main_before)
            listing = git("ls-tree", "-r", "--name-only", "hespulse-data", cwd=remote).split()
            self.assertEqual(sorted(listing), ["export/hespulse-2026-11-01.json", "export/hespulse-2026-11-01.md"])

    def test_weigert_andere_bestanden(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / ".env"
            bad.write_text("SECRET=1")
            with self.assertRaises(ValueError):
                nacht.push_to_branch([bad], Path(tmp) / "w", "/nergens", key=None, when=NOW)


if __name__ == "__main__":
    unittest.main()
