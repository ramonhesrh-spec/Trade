"""Indelingscontrole: logt in, maakt per pagina een schermafbeelding op 390px (en desktop met --desktop), en faalt bij horizontale
scroll, ontbrekende vaste knoppen of te weinig contrast onder het label boven het grote getal. Bekijk de afbeeldingen daarna zelf."""
import argparse, os, sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

REQUIRED = ["#push-pause", "#price-dot", "#system-status", "#fsearch", ".tabbar", "#more-sheet"]
# Playwright vindt in deze omgeving zijn eigen Chromium niet; elders blijft de standaard gelden.
CHROMIUM = os.environ.get("CHROMIUM_PATH") or None


def lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--user", required=True); ap.add_argument("--password", default="wachtwoord-123456")
    ap.add_argument("--pages", nargs="+", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--desktop", action="store_true"); ap.add_argument("--reduced-motion", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        size = {"width": 1280, "height": 800} if a.desktop else {"width": 390, "height": 844}
        ctx = browser.new_context(viewport=size, device_scale_factor=2, reduced_motion="reduce" if a.reduced_motion else "no-preference")
        page = ctx.new_page()
        page.goto(a.base + "/login")
        page.fill("input[name=username]", a.user); page.fill("input[name=password]", a.password)
        page.click("button[type=submit]"); page.wait_for_load_state("networkidle")
        for path in a.pages:
            page.goto(a.base + path); page.wait_for_load_state("networkidle"); page.wait_for_timeout(600)
            name = path.strip("/").replace("/", "_") or "root"
            shot = out / f"{name}-{'desktop' if a.desktop else '390'}.png"
            page.screenshot(path=str(shot), full_page=False)
            if not a.desktop and page.evaluate("document.documentElement.scrollWidth") > 390:
                failures.append(f"{path}: horizontale scroll")
            for sel in REQUIRED if not a.desktop else REQUIRED[:3]:
                if page.locator(sel).count() == 0:
                    failures.append(f"{path}: {sel} ontbreekt")
            label = page.locator(".hl-label").first
            if label.count():
                box = label.bounding_box()
                img = Image.open(shot).convert("RGB")
                bg = img.getpixel((int((box["x"] + box["width"] + 6) * 2), int((box["y"] + box["height"] / 2) * 2)))
                ratio = (0.249 + 0.05) / (lum(bg) + 0.05)        # 0,249 = luminantie van --muted, de lichtste tekst die erboven kan staan
                print(f"{path}: contrast muted op gloed {ratio:.2f}")
                if ratio < 4.5:
                    failures.append(f"{path}: contrast {ratio:.2f} onder 4,5")
            print(f"{path}: {shot}")
        browser.close()
    if failures:
        print("\n".join(failures)); sys.exit(1)


if __name__ == "__main__":
    main()
