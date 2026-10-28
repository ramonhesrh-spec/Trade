"""Maakt het linkvoorbeeld van /nieuw (web/static/og/nieuw.png, 1200x630): wat Discord en WhatsApp tonen als iemand de link deelt.

    python3 scripts/make_og.py

Pillow komt mee met matplotlib (requirements.txt), net als bij scripts/make_splash.py; het lettertype is DejaVu Sans uit matplotlib zelf,
zodat het beeld op elke machine hetzelfde wordt. Bewust zonder datum of aftelstand: het plaatje wordt door chats lang bewaard, en een tijd
die verzet wordt zou er dan verkeerd op blijven staan. Opnieuw draaien na een wijziging aan de tekst, en de PNG meecommitten.
"""
import sys
from pathlib import Path

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.make_splash import ACCENT, BG, SS, _logo  # noqa: E402

OUT = ROOT / "web" / "static" / "og" / "nieuw.png"
W, H = 1200, 630
TEXT = (234, 241, 240)          # --text
DIM = (152, 164, 167)           # --tx2
LINE = (35, 45, 47)             # --border
ZONE = (12, 52, 52)             # --actint op --bg, zonder doorzichtigheid


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    path = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal"))
    return ImageFont.truetype(path, size)


def _card(d: ImageDraw.ImageDraw, x: int, top: int, bottom: int) -> None:
    """Kansen in het klein: drie tabs (de gekozen onderstreept) boven een kaart met de zone als vlak, een koerslijn en de koers als stip.
    Geen getallen: een getal op dit plaatje zou een verzonnen koers zijn."""
    for i in range(3):
        d.rounded_rectangle([x + i * 110 * SS, top, x + (i * 110 + 84) * SS, top + 12 * SS], radius=6 * SS, fill=LINE if i else DIM)
    d.rectangle([x, top + 22 * SS, x + 84 * SS, top + 26 * SS], fill=ACCENT)
    card_top = top + 50 * SS
    d.rounded_rectangle([x, card_top, x + 320 * SS, bottom], radius=18 * SS, outline=LINE, width=2 * SS)
    zone_top = card_top + 170 * SS
    d.rectangle([x + 20 * SS, zone_top, x + 300 * SS, zone_top + 40 * SS], fill=ZONE)
    d.line([(x + 20 * SS, zone_top), (x + 300 * SS, zone_top)], fill=ACCENT, width=2 * SS)
    pts = [(20, 70), (60, 100), (100, 80), (140, 140), (180, 120), (220, 175), (260, 160)]
    d.line([(x + px * SS, card_top + py * SS) for px, py in pts], fill=TEXT, width=3 * SS, joint="curve")
    lx, ly = x + 260 * SS, card_top + 160 * SS
    d.ellipse([lx - 9 * SS, ly - 9 * SS, lx + 9 * SS, ly + 9 * SS], fill=TEXT)


def render() -> Image.Image:
    img = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(img)
    pad = 80 * SS
    _logo(d, pad + 26 * SS, pad + 26 * SS, 52 * SS)
    d.text((pad + 72 * SS, pad + 26 * SS), "HesPulse", font=_font(True, 34 * SS), fill=TEXT, anchor="lm")
    d.text((pad - 6 * SS, 300 * SS), "Kansen.", font=_font(True, 120 * SS), fill=TEXT, anchor="ls")
    d.text((pad, 380 * SS), "HesPulse wordt vernieuwd.", font=_font(True, 44 * SS), fill=TEXT, anchor="ls")
    d.text((pad, 440 * SS), "Alle kansen op één plek: een tab", font=_font(False, 30 * SS), fill=DIM, anchor="ls")
    d.text((pad, 480 * SS), "per soort, met de grafiek erbij.", font=_font(False, 30 * SS), fill=DIM, anchor="ls")
    d.rectangle([pad, (H - 80) * SS, pad + 64 * SS, (H - 76) * SS], fill=ACCENT)
    _card(d, 800 * SS, 110 * SS, 520 * SS)
    return img.resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    render().save(OUT, optimize=True)
    print(f"Geschreven: {OUT.relative_to(ROOT)}")
