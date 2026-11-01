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
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None)
        text = json.dumps(data)
        self.assertNotIn("geheimenaam", text)
        self.assertNotIn("iemand@voorbeeld.nl", text)
        self.assertNotIn("987654321", text)
        self.assertFalse(keys_of(data) & set(PERSONAL_KEYS), keys_of(data) & set(PERSONAL_KEYS))
        self.assertEqual([s["trade_type"] for s in data["signalen"]], ["zone_radar"])
        self.assertIn("zone_radar", data["lekken"]["7d"])

    def test_schrijft_json_en_markdown_met_datum(self):
        data = nacht.build_export(NOW, stop_fetch=lambda *a, **k: None)
        paths = nacht.write_files(data, Path(self.out.name), NOW)
        self.assertEqual(sorted(p.name for p in paths), ["hespulse-2026-11-01.json", "hespulse-2026-11-01.md"])
        md = (Path(self.out.name) / "hespulse-2026-11-01.md").read_text()
        self.assertIn("Zone-radar", md)
        self.assertNotIn("geheimenaam", md)


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
