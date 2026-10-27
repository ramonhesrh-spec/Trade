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


def _ladder(d: ImageDraw.ImageDraw, x: int, top: int, bottom: int) -> None:
    """Peil in het klein: een rechtopstaande prijsschaal, de zone als vlak, de koers als lijn en de afstand als accentbalk."""
    for i, y in enumerate(range(top, bottom + 1, 26 * SS)):
        d.line([(x, y), (x + (34 if i % 4 == 0 else 18) * SS, y)], fill=LINE, width=2 * SS)
    zone_top, zone_bottom = top + 70 * SS, top + 150 * SS
    d.rectangle([x + 60 * SS, zone_top, x + 300 * SS, zone_bottom], fill=ZONE)
    d.line([(x + 60 * SS, zone_bottom), (x + 300 * SS, zone_bottom)], fill=ACCENT, width=2 * SS)
    price = bottom - 90 * SS
    d.line([(x + 40 * SS, price), (x + 320 * SS, price)], fill=TEXT, width=3 * SS)
    d.ellipse([x + 300 * SS, price - 9 * SS, x + 318 * SS, price + 9 * SS], fill=TEXT)
    d.rectangle([x + 170 * SS, zone_bottom + 6 * SS, x + 184 * SS, price - 6 * SS], fill=ACCENT)


def render() -> Image.Image:
    img = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(img)
    pad = 80 * SS
    _logo(d, pad + 26 * SS, pad + 26 * SS, 52 * SS)
    d.text((pad + 72 * SS, pad + 26 * SS), "HesPulse", font=_font(True, 34 * SS), fill=TEXT, anchor="lm")
    d.text((pad - 6 * SS, 300 * SS), "Peil.", font=_font(True, 150 * SS), fill=TEXT, anchor="ls")
    d.text((pad, 380 * SS), "HesPulse wordt vernieuwd.", font=_font(True, 44 * SS), fill=TEXT, anchor="ls")
    d.text((pad, 440 * SS), "De prijs als ladder: in één blik", font=_font(False, 30 * SS), fill=DIM, anchor="ls")
    d.text((pad, 480 * SS), "hoe ver je kans nog is.", font=_font(False, 30 * SS), fill=DIM, anchor="ls")
    d.rectangle([pad, (H - 80) * SS, pad + 64 * SS, (H - 76) * SS], fill=ACCENT)
    _ladder(d, 790 * SS, 110 * SS, 520 * SS)
    return img.resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    render().save(OUT, optimize=True)
    print(f"Geschreven: {OUT.relative_to(ROOT)}")
