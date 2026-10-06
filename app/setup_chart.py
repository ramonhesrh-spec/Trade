"""Tekent een structuur-setup als de grafiek die een handelaar zelf maakt: candles, de gebroken lijn, de limiet op het
retest-niveau, de stopzone en de doelen. Pure functie zonder netwerk: alles komt uit de momentopname die structure_live
bij de breuk bewaart. Kleuren staan in CSS (klassen .sc-*), zodat het thema bepaalt hoe het eruitziet."""
from datetime import datetime
from html import escape
from typing import Optional

W, H = 560, 320
PAD_L, PAD_R, PAD_T, PAD_B = 6, 132, 14, 14
LABEL_GAP = 16            # minimale afstand tussen twee labels, zodat dicht bij elkaar liggende doelen leesbaar blijven
SHOWN_BARS = 44           # genoeg om de structuur te zien, weinig genoeg om leesbaar te blijven op een telefoon
FUTURE_BARS = 9          # lege ruimte rechts voor stopzone en doelen
BAR_SECONDS = 30 * 60


def _fmt(x: float) -> str:
    """Vijf cijfers is genoeg om een niveau te lezen en past op een telefoon: 0.09572, 2717.1."""
    return f"{x:.5g}" if abs(x) < 1000 else f"{x:,.1f}".replace(",", "")


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def setup_svg(candles: list[list], setup: dict, plan: dict, price: Optional[float] = None, events: Optional[list[dict]] = None) -> str:
    """candles: [[iso_tijd, open, hoog, laag, slot], ...] oud naar nieuw. setup: coin, direction, kind, line_a, line_slope,
    p1_at, break_at. plan: level, stop, targets, targets_r. Geeft '' als er geen candles zijn."""
    if not candles:
        return ""
    candles = candles[-SHOWN_BARS:]
    n = len(candles)
    times = [_ts(c[0]) for c in candles]
    slots = n + FUTURE_BARS
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    step = plot_w / slots
    levels = [plan["level"], plan["stop"], *plan["targets"], *([price] if price else [])]
    lo = min([c[3] for c in candles] + levels)
    hi = max([c[2] for c in candles] + levels)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.05, hi + span * 0.05

    def y(v: float) -> float:
        return PAD_T + (hi - v) / (hi - lo) * plot_h

    def x(i: float) -> float:
        return PAD_L + (i + 0.5) * step

    def bar_index(t: float) -> float:
        return (t - times[0]) / BAR_SECONDS

    out = [f'<svg class="sc" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(setup["coin"])} {escape(setup["direction"])} structuur-setup">']
    right = PAD_L + plot_w

    has_structure = setup.get("line_a") is not None
    break_i = max(0.0, min(n - 1, bar_index(_ts(setup["break_at"])) - 1)) if has_structure else float(max(0, n - 10))
    zone_top, zone_bottom = sorted((plan["level"], plan["stop"]))
    out.append(f'<rect class="sc-stopzone" x="{x(break_i):.1f}" y="{y(zone_bottom):.1f}" width="{right - x(break_i):.1f}" '
               f'height="{max(1.0, y(zone_top) - y(zone_bottom)):.1f}"/>')

    if has_structure:
        p1 = bar_index(_ts(setup["p1_at"]))
        x0 = max(0.0, p1)
        pts = []
        for i in (x0, n - 1 + FUTURE_BARS):
            v = setup["line_a"] + setup["line_slope"] * (i - p1)
            pts.append(f"{x(i):.1f},{y(v):.1f}")
        out.append(f'<polyline class="sc-structure" points="{" ".join(pts)}"/>')

    for i, (_, o, h, low, c) in enumerate(candles):
        cls = "sc-up" if c >= o else "sc-down"
        body_top, body_h = y(max(o, c)), max(1.0, abs(y(o) - y(c)))
        out.append(f'<line class="sc-wick {cls}" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(h):.1f}" y2="{y(low):.1f}"/>'
                   f'<rect class="sc-body {cls}" x="{x(i) - step * 0.34:.1f}" y="{body_top:.1f}" width="{step * 0.68:.1f}" height="{body_h:.1f}"/>')

    if has_structure:
        bx = x(break_i)
        arrow_y = y(candles[int(break_i)][2]) - 8 if setup["direction"] == "short" else y(candles[int(break_i)][3]) + 8
        out.append(f'<text class="sc-break" x="{bx:.1f}" y="{arrow_y:.1f}" text-anchor="middle">{"▼" if setup["direction"] == "short" else "▲"}</text>')

    marks = [(plan["level"], "sc-limit", f"{plan.get('level_label', 'Limiet')} {_fmt(plan['level'])}"), (plan["stop"], "sc-stop", f"Stop {_fmt(plan['stop'])}")]
    target_name = (lambda k: "Doel") if plan.get("level_label") else (lambda k: f"T{k}")
    marks += [(t, "sc-target", f"{target_name(k)} {_fmt(t)} · {r:.1f}R") for k, (t, r) in enumerate(zip(plan["targets"], plan["targets_r"]), 1)]
    if price:
        marks.append((price, "sc-price", f"Nu {_fmt(price)}"))
    placed, last_y = [], -1e9
    for v, cls, text in sorted(marks, key=lambda m: y(m[0])):
        label_y = max(y(v), last_y + LABEL_GAP)
        placed.append((v, cls, text, label_y))
        last_y = label_y
    for v, cls, text, label_y in placed:
        out.append(f'<line class="sc-line {cls}" x1="{x(n - 1):.1f}" x2="{right:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="sc-label {cls}" x="{right + 6:.1f}" y="{label_y + 4:.1f}">{escape(text)}</text>')

    # Gebeurtenissen (limiet geraakt, doelen, stop) als stippen op het moment en het niveau waar ze gebeurden.
    for ev in events or []:
        i = min(slots - 1, max(0.0, bar_index(_ts(ev["at"]))))
        out.append(f'<circle class="sc-event" cx="{x(i):.1f}" cy="{y(ev["level"]):.1f}" r="4.5"><title>{escape(ev["text"])}</title></circle>')

    out.append("</svg>")
    return "".join(out)


def trade_svg(candles: list[list], direction: str, coin: str, entry: float, stop: float, take: float, price: Optional[float] = None) -> str:
    """Dezelfde grafiek voor elke soort kans zonder gebroken lijn (Trend, SMC, markt-script): candles, instap, stop en doel."""
    risk = abs(entry - stop)
    r = abs(take - entry) / risk if risk else 0.0
    plan = {"level": entry, "stop": stop, "targets": [take], "targets_r": [r], "level_label": "Instap"}
    return setup_svg(candles, {"coin": coin, "direction": direction}, plan, price)


def demo_svg() -> str:
    """Voorbeeld voor de openbare pagina: een verzonnen koersverloop rond 100, bewust zonder echte coin. De pagina zegt dat."""
    from datetime import timedelta
    base = datetime(2026, 1, 5, 8, 0)
    closes = [101.0, 101.8, 102.4, 101.9, 101.1, 100.4, 100.0, 100.6, 101.3, 101.9, 102.3, 101.7, 100.9, 100.2, 99.9, 100.5, 101.0, 101.5,
              101.9, 101.2, 100.5, 100.0, 99.4, 98.6, 98.9, 99.4, 99.9]
    candles = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else 100.8
        candles.append([(base + timedelta(minutes=30 * i)).isoformat() + "+00:00", o, max(o, c) + 0.25, min(o, c) - 0.25, c])
    setup = {"coin": "VOORBEELD", "direction": "short", "kind": "RANGE", "line_a": 100.0, "line_slope": 0.0,
             "p1_at": candles[6][0], "break_at": candles[22][0]}
    plan = {"level": 100.0, "stop": 100.9, "targets": [97.6, 95.9], "targets_r": [2.7, 4.6]}
    return setup_svg(candles, setup, plan, price=99.9)
