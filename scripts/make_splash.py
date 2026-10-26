"""Maakt de opstartbeelden voor iPhone (web/static/splash/) en de iconen van de snelkoppelingen in het manifest (web/static/shortcut-*.png).

    python3 scripts/make_splash.py

Pillow komt mee met matplotlib (requirements.txt); er is geen SVG-renderer nodig, het logo (cirkel met hartslaglijn uit hespulse-logo.svg)
wordt hier met dezelfde maten nagetekend. Eerst op vier keer de grootte, dan verkleind: zo zijn de randen glad. Opnieuw draaien na een
wijziging aan het logo of aan web/splash.py, en de PNG's meecommitten.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from web.splash import SCREENS  # noqa: E402

BG = (10, 14, 15)              # #0a0e0f, de achtergrond van de app en van background_color in het manifest
ACCENT = (10, 186, 181)        # #0ABAB5
PANEL = (19, 26, 27)           # #131a1b, --panel
SS = 4                         # supersampling
PULSE = [(5, 16), (9, 16), (11.5, 9), (15.5, 23), (18, 16), (27, 16)]   # het pad uit hespulse-logo.svg, viewBox 32


def _logo(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float) -> None:
    """Het logo in een vierkant van `size` pixels rond (cx, cy), lijndikte 2 op 32 zoals de SVG."""
    unit = size / 32
    left, top = cx - size / 2, cy - size / 2
    width = max(1, round(2 * unit))
    r = 15 * unit
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT, width=width)
    pts = [(left + x * unit, top + y * unit) for x, y in PULSE]
    draw.line(pts, fill=ACCENT, width=width, joint="curve")
    for x, y in (pts[0], pts[-1]):
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=ACCENT)


def splash(w: int, h: int) -> Image.Image:
    big = Image.new("RGB", (w * SS, h * SS), BG)
    _logo(ImageDraw.Draw(big), w * SS / 2, h * SS / 2, min(w, h) * SS * 0.22)
    return big.resize((w, h), Image.LANCZOS)


def _glyph(draw: ImageDraw.ImageDraw, kind: str, s: float) -> None:
    """Een eenvoudig teken per snelkoppeling, op een vierkant van s pixels."""
    lw = round(s * 0.06)
    if kind == "radar":                   # twee ringen en de stip van de koers
        for r in (0.30, 0.17):
            draw.ellipse([s * (0.5 - r), s * (0.5 - r), s * (0.5 + r), s * (0.5 + r)], outline=ACCENT, width=lw)
        draw.ellipse([s * 0.44, s * 0.44, s * 0.56, s * 0.56], fill=ACCENT)
    elif kind == "vandaag":               # kalenderblad met een gevulde dag
        draw.rounded_rectangle([s * 0.24, s * 0.28, s * 0.76, s * 0.76], radius=s * 0.06, outline=ACCENT, width=lw)
        draw.line([s * 0.24, s * 0.42, s * 0.76, s * 0.42], fill=ACCENT, width=lw)
        for x in (0.38, 0.62):
            draw.line([s * x, s * 0.20, s * x, s * 0.33], fill=ACCENT, width=lw)
        draw.rectangle([s * 0.36, s * 0.52, s * 0.48, s * 0.64], fill=ACCENT)
    elif kind == "bewijs":                # drie balken: gemeten resultaat
        for i, hgt in enumerate((0.22, 0.36, 0.50)):
            x = s * (0.28 + i * 0.17)
            draw.rectangle([x, s * (0.74 - hgt), x + s * 0.11, s * 0.74], fill=ACCENT)


def shortcut_icon(kind: str, size: int = 96) -> Image.Image:
    s = size * SS
    big = Image.new("RGB", (s, s), BG)
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle([s * 0.06, s * 0.06, s * 0.94, s * 0.94], radius=s * 0.2, fill=PANEL)
    _glyph(draw, kind, s)
    return big.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = ROOT / "web" / "static" / "splash"
    out.mkdir(exist_ok=True)
    for screen in SCREENS:
        splash(screen["css_w"] * screen["dpr"], screen["css_h"] * screen["dpr"]).save(out / screen["file"], optimize=True)
        print(out / screen["file"])
    for kind in ("radar", "vandaag", "bewijs"):
        path = ROOT / "web" / "static" / f"shortcut-{kind}.png"
        shortcut_icon(kind).save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
