"""Opstartbeelden voor een geïnstalleerde HesPulse op iPhone (apple-touch-startup-image). iOS toont er alleen één als breedte, hoogte en
pixelverhouding precies kloppen; anders een wit scherm. Eén lijst voor base.html en scripts/make_splash.py, zodat tag en bestand niet uit
elkaar lopen. Alleen staand: de app wordt op een telefoon niet liggend gebruikt."""

# (css-breedte, css-hoogte, pixelverhouding): de schermformaten van iPhone SE (1e generatie) tot en met iPhone 16 Pro Max.
_SIZES = [
    (440, 956, 3),   # 16 Pro Max
    (402, 874, 3),   # 16 Pro
    (430, 932, 3),   # 14 Pro Max, 15 Plus, 15 Pro Max, 16 Plus
    (393, 852, 3),   # 14 Pro, 15, 15 Pro, 16
    (428, 926, 3),   # 12 Pro Max, 13 Pro Max, 14 Plus
    (390, 844, 3),   # 12, 12 Pro, 13, 13 Pro, 14
    (375, 812, 3),   # X, XS, 11 Pro, 12 mini, 13 mini
    (414, 896, 3),   # XS Max, 11 Pro Max
    (414, 896, 2),   # XR, 11
    (414, 736, 3),   # 6 Plus t/m 8 Plus
    (375, 667, 2),   # 6 t/m 8, SE 2e en 3e generatie
    (320, 568, 2),   # SE 1e generatie
]

SCREENS = [
    {
        "css_w": w, "css_h": h, "dpr": dpr, "file": f"splash-{w * dpr}x{h * dpr}.png",
        "media": f"(device-width: {w}px) and (device-height: {h}px) and (-webkit-device-pixel-ratio: {dpr}) and (orientation: portrait)",
    }
    for w, h, dpr in _SIZES
]
