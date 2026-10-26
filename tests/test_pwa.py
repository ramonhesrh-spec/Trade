"""De installeerbare app (PWA): manifest, startpagina per rol, service worker (update, offline, wat nooit gecachet wordt), installatiehulp,
themakleur, opstartbeelden en trek-om-te-verversen."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web/static"
SW = STATIC / "service-worker.js"

# Vingerafdruk van service-worker.js zonder de versieregel, per SW_VERSION. Faalt deze test na een wijziging aan de service worker, verhoog
# dan SW_VERSION (anders blijft de oude versie op telefoons hangen en ziet niemand de updatemelding) en zet hier de nieuwe afdruk.
SW_FINGERPRINTS = {
    3: "3cf7f570b78c45cdad01c3b3bf08d14548aff2eed40ca635609439cd09fdcda9",
}


def node(harness: str, target: str) -> dict:
    out = subprocess.run(["node", str(ROOT / "tests/js" / harness), str(STATIC / target)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def sw_version(src: str) -> int:
    m = re.search(r'^const SW_VERSION = (\d+);$', src, re.M)
    if not m:
        raise AssertionError("SW_VERSION ontbreekt in service-worker.js")
    return int(m.group(1))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.m = json.loads((STATIC / "manifest.json").read_text())

    def test_start_url_is_vandaag_marked_as_app_start(self):
        self.assertEqual(self.m["start_url"], "/vandaag?bron=app")

    def test_id_keeps_existing_installs_the_same_app(self):
        # Zonder id is de start_url de identiteit: de oude installaties hadden /ceo, een nieuwe start_url zou er een tweede app van maken.
        self.assertEqual(self.m["id"], "/ceo")

    def test_basis_blijft_donker_en_standalone(self):
        self.assertEqual(self.m["display"], "standalone")
        self.assertEqual(self.m["theme_color"], "#0a0e0f")
        self.assertEqual(self.m["background_color"], "#0a0e0f")

    def test_shortcuts_radar_vandaag_bewijs_with_existing_icons(self):
        from PIL import Image
        got = [(s["name"], s["url"]) for s in self.m["shortcuts"]]
        self.assertEqual(got, [("Radar", "/smc"), ("Vandaag", "/vandaag"), ("Bewijs", "/bewijs")])
        for s in self.m["shortcuts"]:
            self.assertTrue(s.get("short_name"))
            self.assertTrue(s.get("description"))
            icon = s["icons"][0]
            path = ROOT / "web" / icon["src"].lstrip("/")
            self.assertTrue(path.exists(), path)
            with Image.open(path) as im:
                self.assertEqual(f"{im.width}x{im.height}", icon["sizes"])
            self.assertEqual(icon["sizes"], "96x96")


class WebPwaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "p.db"))
        self.patch.start()
        db.init_db()
        from web import main
        self.main = main
        main._ceo_cache["at"] = 0.0
        main._price_cache.clear()
        self.ceo_id = repo.create_user("baas", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.student_id = repo.create_user("leerling", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.main._ceo_cache["at"] = 0.0
        self.tmp.cleanup()

    def client(self, user_id=None):
        c = TestClient(self.main.app)
        if user_id:
            c.cookies.set(self.main.SESSION_COOKIE, security.create_session_token(user_id))
        return c

    def test_app_start_sends_the_ceo_to_his_own_page(self):
        r = self.client(self.ceo_id).get("/vandaag?bron=app", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/ceo")

    def test_ceo_can_still_open_vandaag_from_the_tab(self):
        self.assertEqual(self.client(self.ceo_id).get("/vandaag", follow_redirects=False).status_code, 200)

    def test_app_start_shows_a_student_vandaag(self):
        r = self.client(self.student_id).get("/vandaag?bron=app", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Vandaag", r.text)

    def test_app_start_without_session_goes_to_login(self):
        r = self.client().get("/vandaag?bron=app", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/login")

    def test_every_shortcut_opens_for_a_student(self):
        c = self.client(self.student_id)
        for s in json.loads((STATIC / "manifest.json").read_text())["shortcuts"]:
            self.assertEqual(c.get(s["url"], follow_redirects=False).status_code, 200, s["url"])

    def test_offline_pages_carry_a_viewer_tag_per_user_and_api_does_not(self):
        a = self.client(self.student_id).get("/smc").headers.get("x-hp-viewer")
        b = self.client(self.ceo_id).get("/smc").headers.get("x-hp-viewer")
        self.assertTrue(a and b)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, str(self.student_id))                   # geen kaal gebruikers-id in een kop
        self.assertRegex(a, r"^[0-9a-f]{20}$")
        self.assertEqual(self.client(self.student_id).get("/vandaag").headers.get("x-hp-viewer"), a)
        self.assertIsNone(self.client(self.student_id).get("/bewijs").headers.get("x-hp-viewer"))
        self.assertIsNone(self.client(self.student_id).get("/api/vandaag").headers.get("x-hp-viewer"))

    def test_install_help_on_account_with_ios_steps_and_android_button(self):
        html = self.client(self.student_id).get("/account").text
        block = html[html.index('id="install-help"'):]
        block = block[:block.index("</section>")]
        for text in ("Zet HesPulse op je beginscherm", "Delen", "Zet op beginscherm", "Open HesPulse"):
            self.assertIn(text, block)
        self.assertIn("data-install-prompt", block)
        self.assertIn("hidden", block[:block.index(">")])              # pas zichtbaar als install.js weet dat hij niet geïnstalleerd is

    def test_install_banner_on_vandaag_is_dismissable(self):
        html = self.client(self.student_id).get("/vandaag").text
        block = html[html.index('id="install-banner"'):]
        block = block[:block.index("</aside>")]
        self.assertIn("data-install-dismiss", block)
        self.assertIn("hidden", block[:block.index(">")])
        self.assertNotIn('id="install-banner"', self.client(self.student_id).get("/smc").text)

    def test_head_has_theme_color_per_scheme_and_splash_links(self):
        from web import splash
        html = self.client().get("/login").text
        self.assertIn('<meta name="theme-color" content="#0a0e0f" media="(prefers-color-scheme: dark)">', html)
        self.assertRegex(html, r'<meta name="theme-color" content="#[0-9a-fA-F]{6}" media="\(prefers-color-scheme: light\)">')
        links = re.findall(r'<link rel="apple-touch-startup-image" href="([^"]+)" media="([^"]+)">', html)
        self.assertEqual(len(links), len(splash.SCREENS))
        self.assertGreaterEqual(len(links), 10)
        for href, media in links:
            self.assertIn("orientation: portrait", media)
            self.assertIn("-webkit-device-pixel-ratio", media)

    def test_logged_in_page_loads_pwa_and_update_notice(self):
        html = self.client(self.student_id).get("/smc").text
        self.assertIn("/static/pwa.js", html)
        self.assertIn('id="sw-update"', html)
        self.assertIn("Nieuwe versie beschikbaar, tik om te laden", html)

    def test_logged_out_page_clears_saved_pages(self):
        # Wie op een pagina zonder sessie komt (inlogscherm na uitloggen), wist de bewaarde Radar en Vandaag op dit apparaat.
        self.assertIn('data-hp-anon', self.client().get("/login").text)
        self.assertNotIn('data-hp-anon', self.client(self.student_id).get("/smc").text)


class SplashFilesTest(unittest.TestCase):
    def test_every_splash_exists_with_its_pixel_size(self):
        from PIL import Image
        from web import splash
        for s in splash.SCREENS:
            path = STATIC / "splash" / s["file"]
            self.assertTrue(path.exists(), path)
            with Image.open(path) as im:
                self.assertEqual((im.width, im.height), (s["css_w"] * s["dpr"], s["css_h"] * s["dpr"]))
                self.assertEqual(im.getpixel((5, 5))[:3], (10, 14, 15))   # effen #0a0e0f


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class ServiceWorkerFetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = SW.read_text()
        cls.r = node("sw_fetch_harness.js", "service-worker.js")

    def test_version_is_bumped_when_the_service_worker_changes(self):
        version = sw_version(self.src)
        self.assertGreaterEqual(version, 3)
        self.assertIn('const CACHE_NAME = "hespulse-shell-v" + SW_VERSION;', self.src)
        body = re.sub(r'^const SW_VERSION = \d+;$', "", self.src, flags=re.M)
        self.assertEqual(SW_FINGERPRINTS.get(version), hashlib.sha256(body.encode()).hexdigest(),
                         "service-worker.js is gewijzigd: verhoog SW_VERSION en zet de nieuwe afdruk in SW_FINGERPRINTS")

    def test_install_waits_for_the_user_and_skips_on_request(self):
        self.assertEqual(self.r["install"]["skipWaiting"], 0)
        self.assertEqual(self.r["install"]["afterMessage"], 1)

    def test_activate_drops_old_shells_and_keeps_current(self):
        v = sw_version(self.src)
        kept = set(self.r["activate"])
        self.assertIn(f"hespulse-shell-v{v}", kept)
        self.assertIn(f"hespulse-pages-v{v}", kept)
        self.assertIn("hespulse-nav", kept)
        for old in ("hespulse-shell-v1", "hespulse-shell-v2", "hespulse-pages-v0"):
            self.assertNotIn(old, kept)

    def test_api_post_and_push_are_never_handled_or_cached(self):
        u = self.r["untouched"]
        for key in ("apiGet", "apiNavigate", "post", "postNavigate", "pushPreview"):
            self.assertFalse(u[key], key)
        self.assertEqual(u["stored"], {})

    def test_only_radar_and_vandaag_are_saved_per_path(self):
        self.assertEqual(set(self.r["online"]["stored"]), {"/smc", "/vandaag"})
        for v in self.r["online"]["stored"].values():
            self.assertEqual(v["viewer"], "kijker-a")
            self.assertTrue(v["saved"])
        self.assertIn("pagina /smc", self.r["online"]["smc"])

    def test_offline_shows_the_last_known_page_with_a_marker(self):
        off = self.r["offline"]
        self.assertIn("pagina /smc", off["smc"])
        self.assertRegex(off["smc"], r'<meta name="hp-offline-at" content="\d{4}-\d\d-\d\dT[^"]+">')
        self.assertIn("pagina /vandaag?bron=app", off["vandaagFromApp"])
        self.assertIn("offline.html", off["kans"])
        self.assertNotIn("hp-offline-at", off["kans"])

    def test_another_viewer_wipes_the_previous_pages(self):
        self.assertEqual(self.r["otherViewer"], {"/vandaag": {"viewer": "kijker-b", "saved": True}})

    def test_redirect_to_login_wipes_and_redirect_to_ceo_is_not_saved(self):
        self.assertEqual(self.r["loginRedirect"], {})
        self.assertEqual(self.r["ceoRedirect"], {})
        self.assertEqual(self.r["noViewer"], {})

    def test_logout_message_wipes_pages(self):
        self.assertEqual(self.r["logout"]["before"], 1)
        self.assertEqual(self.r["logout"]["after"], {})

    def test_static_files_fall_back_to_the_last_version_offline(self):
        self.assertEqual(self.r["staticOffline"], "css /static/style.css?v=1")


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class InstallHelpModeTest(unittest.TestCase):
    def test_mode_per_device(self):
        r = node("install_harness.js", "install.js")
        self.assertEqual(r, {
            "iphone": "ios", "ipadDesktopUa": "ios", "mac": "menu", "androidPrompt": "prompt", "androidNoPrompt": "menu",
            "standalone": "installed", "iosStandalone": "installed", "dismissed": "dismissed", "dismissedInstalled": "installed",
        })

    def test_dismissal_is_remembered_in_try_catch(self):
        src = (STATIC / "install.js").read_text()
        self.assertIn("localStorage", src)
        for call in re.finditer(r"localStorage\.(getItem|setItem)", src):
            before = src[:call.start()]
            self.assertGreater(before.rfind("try {"), before.rfind("}"), "localStorage buiten try")


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class PullToRefreshTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = node("pull_harness.js", "smooth.js")

    def test_a_clear_pull_at_the_top_refreshes_live_data(self):
        self.assertEqual(self.r["pulled"]["refreshed"], 1)
        self.assertEqual(self.r["pulled"]["reloaded"], 0)
        self.assertTrue(self.r["pulledMoves"])

    def test_scrolling_short_sideways_or_in_a_chart_does_not(self):
        for k in ("short", "scrolled", "sideways", "upwards", "inChart"):
            self.assertEqual(self.r[k]["refreshed"] + self.r[k]["reloaded"], 0, k)

    def test_reduced_motion_keeps_the_function_without_movement(self):
        self.assertEqual(self.r["reduced"]["refreshed"], 1)
        self.assertFalse(self.r["reducedMoves"])

    def test_page_without_live_refresh_reloads(self):
        self.assertEqual(self.r["noRefresh"]["reloaded"], 1)


class ThemeHookTest(unittest.TestCase):
    def test_pwa_js_updates_theme_color_on_a_theme_switch(self):
        src = (STATIC / "pwa.js").read_text()
        self.assertIn("applyThemeColor", src)
        self.assertIn('meta[name="theme-color"]', src)
        self.assertIn("prefers-color-scheme", src)


if __name__ == "__main__":
    unittest.main()
