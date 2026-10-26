"""Indelingscontrole: logt in, maakt per pagina een schermafbeelding op 390px (en desktop met --desktop), en faalt bij horizontale
scroll, ontbrekende vaste knoppen of te weinig contrast onder het label boven het grote getal. Met --theme light (of system) draait hetzelfde
in het lichte thema: de cookie hp_theme zet het, net als de keuze in Account. Draai hem dus twee keer. Bekijk de afbeeldingen daarna zelf."""
import argparse, os, sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

REQUIRED = ["#push-pause", "#price-dot", "#system-status", ".tabbar", "#more-sheet"]
WITH_SEARCH = {"/smc"}      # het zoekveld hoort alleen op de Radar te staan; Nu volgt het ontwerp zonder zoekveld
# Playwright vindt in deze omgeving zijn eigen Chromium niet; elders blijft de standaard gelden.
CHROMIUM = os.environ.get("CHROMIUM_PATH") or None
DEFAULT_PAGES = ["/vandaag", "/structuur", "/smc", "/bewijs", "/signalen", "/meldingen", "/account", "/week", "/ceo", "/uitleg", "/keten", "/coins/BTC"]
PUBLIC = {"/keten"}          # openbare pagina zonder dok en vaste knoppen


def lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--user", required=True); ap.add_argument("--password", default="wachtwoord-123456")
    ap.add_argument("--pages", nargs="+", default=None, help="standaard alle ingelogde pagina's"); ap.add_argument("--out", required=True)
    ap.add_argument("--desktop", action="store_true"); ap.add_argument("--reduced-motion", action="store_true")
    ap.add_argument("--theme", choices=("dark", "light", "system"), default="dark", help="thema via de cookie hp_theme")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        size = {"width": 1280, "height": 800} if a.desktop else {"width": 390, "height": 844}
        ctx = browser.new_context(viewport=size, device_scale_factor=2, reduced_motion="reduce" if a.reduced_motion else "no-preference")
        ctx.add_cookies([{"name": "hp_theme", "value": a.theme, "url": a.base}])
        page = ctx.new_page()
        page.goto(a.base + "/login")
        page.fill("input[name=username]", a.user); page.fill("input[name=password]", a.password)
        page.click("button[type=submit]"); page.wait_for_timeout(2500)
        pages = a.pages
        if pages is None:
            pages = list(DEFAULT_PAGES)
            page.goto(a.base + "/week", wait_until="domcontentloaded")   # de deal van de week linkt naar een kans
            kans = page.locator('a[href^="/kans/"]').first
            if kans.count():
                pages.append(kans.get_attribute("href"))
        for path in pages:
            page.goto(a.base + path, wait_until="domcontentloaded"); page.wait_for_timeout(1500)   # geen networkidle: de koerssocket staat nooit stil
            name = path.strip("/").replace("/", "_") or "root"
            shot = out / f"{name}-{'desktop' if a.desktop else '390'}-{a.theme}.png"
            page.screenshot(path=str(shot), full_page=False)
            if not a.desktop and page.evaluate("document.documentElement.scrollWidth") > 390:
                failures.append(f"{path}: horizontale scroll")
            for sel in [] if path in PUBLIC else REQUIRED if not a.desktop else REQUIRED[:3]:   # op desktop bestaan dok en blad niet
                if page.locator(sel).count() == 0:
                    failures.append(f"{path}: {sel} ontbreekt")
            if (page.locator("#fsearch").count() > 0) != (path in WITH_SEARCH) and path not in PUBLIC:
                failures.append(f"{path}: zoekveld {'ontbreekt' if path in WITH_SEARCH else 'hoort hier niet'}")
            label = page.locator(".hl-label").first
            if label.count():
                box = label.bounding_box()
                img = Image.open(shot).convert("RGB")
                if box["y"] + box["height"] > size["height"]:      # op Nu staat het grote getal onder Markt, lager op de pagina
                    label.scroll_into_view_if_needed(); page.wait_for_timeout(300)
                    box = label.bounding_box()
                    page.screenshot(path=str(out / f"{name}-label.png"))
                    img = Image.open(out / f"{name}-label.png").convert("RGB")
                bg = img.getpixel((int((box["x"] + box["width"] + 6) * 2), int((box["y"] + box["height"] / 2) * 2)))
                # --muted is de zwakste tekst die erboven kan staan; zijn kleur komt uit het thema van de pagina zelf.
                muted = page.evaluate("""() => { const v = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim();
                                                 return [1, 3, 5].map(i => parseInt(v.slice(i, i + 2), 16)); }""")
                hi, lo = sorted((lum(muted), lum(bg)), reverse=True)
                ratio = (hi + 0.05) / (lo + 0.05)
                print(f"{path}: contrast muted op de achtergrond {ratio:.2f} ({a.theme})")
                if ratio < 4.5:
                    failures.append(f"{path}: contrast {ratio:.2f} onder 4,5")
            print(f"{path}: {shot}")
        browser.close()
    if failures:
        print("\n".join(failures)); sys.exit(1)


if __name__ == "__main__":
    main()
