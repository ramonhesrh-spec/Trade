"""Licht en donker thema: tokens uit het ontwerp, de keuze in Account zonder flits (cookie, data-theme) en het contrast van beide thema's."""
import os
import re
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security
from web import main

CSS = (main.BASE_DIR / "static" / "style.css").read_text(encoding="utf-8")


def block(selector: str) -> str:
    start = CSS.index(selector + " {")
    return CSS[start + len(selector) + 2:CSS.index("}", start)]


def tokens(body: str) -> dict:
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))


def lum(hex_: str) -> float:
    h = hex_.strip().lstrip("#")
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


DARK = tokens(block(":root"))
LIGHT = {**DARK, **tokens(block(':root[data-theme="light"]'))}


def resolve(theme: dict, name: str) -> str:
    v = theme[name].strip()
    while v.startswith("var("):
        v = theme[v[4:-1].strip()].strip()
    return v


class TokenTests(unittest.TestCase):
    def test_systeem_en_gekozen_licht_zijn_dezelfde_regels(self):
        self.assertEqual(block(':root[data-theme="light"]').split(), block(':root[data-theme="system"]').split())
        self.assertIn('@media (prefers-color-scheme: light) {\n  :root[data-theme="system"] {', CSS)

    def test_donker_blijft_zoals_het_was(self):
        for name, value in (("--bg", "#0a0e0f"), ("--panel", "#131a1b"), ("--text", "#eaf1f0"), ("--accent", "#0ABAB5"), ("--glow-edge", "#0c3a42")):
            self.assertEqual(DARK[name].strip(), value, name)

    def test_ontwerptokens_bestaan_in_beide_themas(self):
        for name in ("--s1", "--s2", "--bd", "--tx", "--tx2", "--ac", "--aci", "--onac", "--win", "--loss", "--actint"):
            self.assertIn(name, DARK, name)
            self.assertIn(name, LIGHT, name)
        self.assertEqual(LIGHT["--bg"].strip(), "#f4f6f6")           # TH.light uit het ontwerp
        self.assertEqual(LIGHT["--aci"].strip(), "#067a76")

    def test_tekst_haalt_4_5_in_beide_themas(self):
        pairs = [("--text", "--bg"), ("--text-dim", "--panel"), ("--muted", "--bg"), ("--muted", "--panel"), ("--tx2", "--s1"),
                 ("--aci", "--bg"), ("--accent", "--bg"), ("--on-accent", "--accent"), ("--onac", "--ac"), ("--green", "--panel"), ("--red", "--panel")]
        for theme_name, theme in (("donker", DARK), ("licht", LIGHT)):
            for fg, bg in pairs:
                ratio = contrast(resolve(theme, fg), resolve(theme, bg))
                self.assertGreaterEqual(ratio, 4.5, f"{theme_name}: {fg} op {bg} = {ratio:.2f}")

    def test_velden_halen_3_tegen_het_paneel(self):
        for theme in (DARK, LIGHT):
            self.assertGreaterEqual(contrast(resolve(theme, "--border-interactive"), resolve(theme, "--panel")), 3.0)

    def test_grafiek_leest_rasterkleur_uit_het_thema(self):
        src = (main.BASE_DIR / "static" / "levelchart.js").read_text(encoding="utf-8")
        self.assertIn('css("--chart-grid"', src)
        self.assertNotIn('color: "rgba(255,255,255,0.04)"', src)


class ThemeChoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "t.db"))
        self.patch.start()
        db.init_db()
        main._price_cache.clear()
        self.client = TestClient(main.app)
        uid = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(uid))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_zonder_keuze_donker(self):
        html = self.client.get("/account").text
        self.assertIn('<html lang="nl" data-theme="dark"', html)
        self.assertIn('<meta name="color-scheme" content="dark">', html)
        self.assertIn('<meta name="theme-color" content="#0a0e0f" media="(prefers-color-scheme: light)">', html)

    def test_gekozen_licht_komt_van_de_server_zonder_flits(self):
        self.client.cookies.set(main.THEME_COOKIE, "light")
        html = self.client.get("/vandaag").text
        self.assertIn('<html lang="nl" data-theme="light"', html)
        self.assertIn('<meta name="color-scheme" content="light">', html)
        self.assertIn("html{background:#f4f6f6}", html)
        self.assertEqual(html.count('content="#f4f6f6"'), 2)          # beide theme-color-varianten

    def test_systeem_volgt_het_toestel(self):
        self.client.cookies.set(main.THEME_COOKIE, "system")
        html = self.client.get("/vandaag").text
        self.assertIn('data-theme="system"', html)
        self.assertIn('<meta name="color-scheme" content="dark light">', html)
        self.assertIn('<meta name="theme-color" content="#0a0e0f" media="(prefers-color-scheme: dark)">', html)
        self.assertIn('<meta name="theme-color" content="#f4f6f6" media="(prefers-color-scheme: light)">', html)
        self.assertIn("@media (prefers-color-scheme: light){html{background:#f4f6f6}}", html)

    def test_een_onbekende_cookie_is_donker(self):
        self.client.cookies.set(main.THEME_COOKIE, '"><script>')
        html = self.client.get("/vandaag").text
        self.assertIn('data-theme="dark"', html)
        self.assertNotIn("<script>\"", html)

    def test_account_toont_de_keuze_met_de_huidige_aangevinkt(self):
        self.client.cookies.set(main.THEME_COOKIE, "light")
        html = self.client.get("/account").text
        sec = html[html.index('id="weergave"'):]
        sec = sec[:sec.index("</form>")]
        for value, label in (("system", "Systeem"), ("dark", "Donker"), ("light", "Licht")):
            self.assertIn(f'value="{value}"', sec)
            self.assertIn(label, sec)
        self.assertRegex(sec, r'value="light" checked')
        self.assertNotRegex(sec, r'value="dark" checked')
        self.assertIn('action="/instellingen/thema"', sec)

    def test_zonder_js_bewaart_het_formulier_de_keuze(self):
        r = self.client.post("/instellingen/thema", data={"thema": "light"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/account#weergave")
        self.assertIn(f"{main.THEME_COOKIE}=light", r.headers["set-cookie"])
        r = self.client.post("/instellingen/thema", data={"thema": "paars"}, follow_redirects=False)
        self.assertIn(f"{main.THEME_COOKIE}=dark", r.headers["set-cookie"])

    def test_themascript_in_try_catch_en_haak_voor_de_statusbalk(self):
        src = (main.BASE_DIR / "static" / "theme.js").read_text(encoding="utf-8")
        self.assertIn("try", src)
        self.assertIn("localStorage", src)
        self.assertIn("HP.applyThemeColor", src)
        self.assertIn("hp_theme", src)
        html = self.client.get("/vandaag").text
        head = html[:html.index("</head>")]
        self.assertRegex(head, r"try \{[^}]*localStorage\.getItem\(\"hp_theme\"\)")


if __name__ == "__main__":
    unittest.main()
