import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, gallery_job, repo, security


class WebGalerijTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        self.out = mock.patch.object(gallery_job, "OUT_DIR", Path(self.tmp.name) / "galerij")
        self.out.start()
        db.init_db()
        from web import main
        self.main = main
        main._ceo_cache.update(at=0.0, id=None)
        self.ceo = repo.create_user("baas", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.pupil = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)

    def tearDown(self):
        self.out.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def client(self, uid):
        c = TestClient(self.main.app)
        c.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(uid))
        return c

    def test_leerling_krijgt_404_en_ceo_ziet_de_pagina(self):
        self.assertEqual(self.client(self.pupil).get("/galerij").status_code, 404)
        r = self.client(self.ceo).get("/galerij")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Maak de galerij", r.text)

    def test_klaar_bestand_wordt_geserveerd_aan_de_ceo_alleen(self):
        gallery_job.OUT_DIR.mkdir(parents=True)
        gallery_job.path_of("voorbeelden").write_text("<p>kaart</p>", encoding="utf-8")
        self.assertEqual(self.client(self.ceo).get("/galerij/voorbeelden").text, "<p>kaart</p>")
        self.assertEqual(self.client(self.pupil).get("/galerij/voorbeelden").status_code, 404)
        self.assertEqual(self.client(self.ceo).get("/galerij/onbekend").status_code, 404)

    def test_maken_start_de_draad_en_stuurt_terug(self):
        with mock.patch.object(gallery_job, "start") as start:
            r = self.client(self.ceo).get("/galerij?maak=willekeurig", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        start.assert_called_once_with("willekeurig")

    def test_mislukte_bouw_toont_de_fout_en_geeft_de_draad_vrij(self):
        with mock.patch.object(gallery_job, "_build", side_effect=RuntimeError("geen beurs")):
            gallery_job._run("voorbeelden")
        st = gallery_job.status("voorbeelden")
        self.assertFalse(st["busy"])
        self.assertIn("geen beurs", st["error"])


if __name__ == "__main__":
    unittest.main()
