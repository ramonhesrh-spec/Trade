"""scripts/aankondiging.py: zetten (Amsterdamse tijd, bewaard als UTC), tonen, wissen en een testpush alleen naar de eigenaar."""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from app import config, db, repo, security

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "aankondiging.py"


def load():
    spec = importlib.util.spec_from_file_location("aankondiging", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "s.db")),
                        mock.patch.object(config, "ANNOUNCEMENT_AT", "")]
        for p in self.patches:
            p.start()
        db.init_db()
        self.ceo = repo.create_user("ceo", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.mark = repo.create_user("mark", security.hash_password("wachtwoord-123456"), 0, 1.0)
        self.mod = load()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(list(argv))
        return code, out.getvalue()

    def test_zet_bewaart_utc_en_toon_geeft_amsterdamse_tijd(self):
        code, out = self.run_main("--zet", "2026-11-02T18:00")
        self.assertEqual(code, 0)
        self.assertEqual(repo.get_announcement_at(), datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc))
        self.assertEqual(db.get_setting("announcement_at"), "2026-11-02T17:00:00+00:00")
        code, out = self.run_main("--toon")
        self.assertIn("maandag 2 november, 18:00", out)

    def test_ongeldige_tijd_verandert_niets(self):
        code, out = self.run_main("--zet", "morgen")
        self.assertNotEqual(code, 0)
        self.assertIsNone(repo.get_announcement_at())

    def test_wis(self):
        self.run_main("--zet", "2026-11-02T18:00")
        code, out = self.run_main("--wis")
        self.assertEqual(code, 0)
        self.assertIsNone(repo.get_announcement_at())
        code, out = self.run_main("--toon")
        self.assertIn("geen", out.lower())

    def test_testpush_alleen_naar_de_eigenaar_en_zonder_vlag(self):
        sent = []

        async def fake_send(user_id, title, body, url, **kw):
            sent.append(user_id)

        with mock.patch("app.push_notify.send_push", fake_send):
            code, out = self.run_main("--test-push")
        self.assertEqual(code, 0)
        self.assertEqual(sent, [self.ceo])
        self.assertTrue(repo.claim_flag("announce_push:v3"))    # de echte push is nog niet geclaimd


if __name__ == "__main__":
    unittest.main()
