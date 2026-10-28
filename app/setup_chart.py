"""Tekent een structuur-setup als de grafiek die een handelaar zelf maakt: candles, de gebroken lijn, de limiet op het
retest-niveau, de stopzone en de doelen. Pure functie zonder netwerk: alles komt uit de momentopname die structure_live
bij de breuk bewaart. Kleuren staan in CSS (klassen .sc-*), zodat het thema bepaalt hoe het eruitziet."""
from datetime import datetime
from html import escape
from typing import Optional

import pandas as pd

from app import price_text

W, H = 560, 320
PAD_L, PAD_R, PAD_T, PAD_B = 6, 132, 14, 14
LABEL_CHAR_W = 8.0        # breedte van een teken in .sc-label (13px monospace is 7,8); de rechtermarge groeit mee met het langste label
LABEL_GAP = 16            # minimale afstand tussen twee labels, zodat dicht bij elkaar liggende doelen leesbaar blijven
SHOWN_BARS = 44           # genoeg om de structuur te zien, weinig genoeg om leesbaar te blijven op een telefoon
FUTURE_BARS = 9          # lege ruimte rechts voor stopzone en doelen
BAR_SECONDS = 30 * 60
MAX_RS_BARS = 240         # een range beslaat tot 120 candles plus de aanloop en de afloop; meer maakt een candle dunner dan een pixel


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
    marks = [(plan["level"], "sc-limit", f"{plan.get('level_label', 'Limiet')} {_fmt(plan['level'])}"), (plan["stop"], "sc-stop", f"Stop {_fmt(plan['stop'])}")]
    target_name = (lambda k: "Doel") if plan.get("level_label") else (lambda k: f"T{k}")
    marks += [(t, "sc-target", f"{target_name(k)} {_fmt(t)} · {r:.1f}R") for k, (t, r) in enumerate(zip(plan["targets"], plan["targets_r"]), 1)]
    if price:
        marks.append((price, "sc-price", f"Nu {_fmt(price)}"))
    # Een vaste marge sneed "T3 2453.4 · 10.2R" rechts af: vier cijfers voor de punt plus een R van twee cijfers past niet in 132.
    pad_r = max(PAD_R, int(max(len(m[2]) for m in marks) * LABEL_CHAR_W + 10))
    plot_w, plot_h = W - PAD_L - pad_r, H - PAD_T - PAD_B
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

    diffs = sorted(b - a for a, b in zip(times, times[1:]))
    bar_seconds = diffs[len(diffs) // 2] if diffs else BAR_SECONDS        # 5m, 15m, 30m of 4u, zoals de candles zelf

    def bar_index(t: float) -> float:
        return (t - times[0]) / bar_seconds

    # De data-attributen laten live.js de prijslijn verplaatsen zonder de pagina te herladen: y = pad_t + (hi - prijs) / (hi - lo) * plot_h.
    out = [f'<svg class="sc" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(setup["coin"])} {escape(setup["direction"])} structuur-setup" '
           f'data-chart-coin="{escape(setup["coin"])}" data-hi="{hi:.8g}" data-lo="{lo:.8g}" data-pad-t="{PAD_T}" data-plot-h="{plot_h}" '
           f'data-level="{plan["level"]:.8g}" data-stop="{plan["stop"]:.8g}">']
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


def _epoch(value) -> float:
    """Candles zijn iso-tekst, de setups van rangesweep zijn Timestamps; zonder tijdzone geldt UTC, voor allebei op dezelfde manier."""
    t = pd.Timestamp(value)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).timestamp()


def range_sweep_svg(candles: list[list], setup: dict, stop: float, price: Optional[float] = None, zones: Optional[list[dict]] = None) -> str:
    """Een range sweep-setup zoals de trader hem tekent: de range als vak, de zone van de setup, eventuele andere zones gedempt, de wick van de sweep,
    de limiet(en), de stop en het midden en de overkant van de range als referentie (er is geen doel). candles: [[iso, o, h, l, c], ...] oud naar nieuw,
    de aanroeper kiest het venster; setup: een element uit rangesweep.find_setups. Geeft '' zonder candles."""
    if not candles:
        return ""
    candles = candles[-MAX_RS_BARS:]
    n = len(candles)
    times = [_epoch(c[0]) for c in candles]
    diffs = sorted(b - a for a, b in zip(times, times[1:]))
    bar_seconds = diffs[len(diffs) // 2] if diffs else BAR_SECONDS
    short = setup["direction"] == "short"
    legs = setup["legs"]
    rng_hi, rng_lo = setup["range_high"], setup["range_low"]
    # Een zone-sweep heeft geen range: zijn range_high en range_low zijn alleen het referentiekader van de uitkomstmeting, dus niet tekenen.
    ref = [] if setup["family"] == "zonesweep" else [((rng_hi + rng_lo) / 2, "Midden (ref.)"), (rng_lo if short else rng_hi, "Overkant (ref.)")]
    marks = [(p, "sc-limit", (f"Limiet {round(w * 100):d}%" if len(legs) > 1 else "Limiet") + f" {_fmt(p)}") for w, p in legs]
    marks += [(stop, "sc-stop", f"Stop {_fmt(stop)}")] + [(v, "sc-target", f"{name} {_fmt(v)}") for v, name in ref]
    if price:
        marks.append((price, "sc-price", f"Nu {_fmt(price)}"))
    pad_r = max(PAD_R, int(max(len(m[2]) for m in marks) * LABEL_CHAR_W + 10))
    plot_w, plot_h = W - PAD_L - pad_r, H - PAD_T - PAD_B
    step = plot_w / (n + FUTURE_BARS)
    shown = candles
    values = [c[3] for c in shown] + [c[2] for c in shown] + [m[0] for m in marks] + [setup["zone_low"], setup["zone_high"]]
    if setup.get("extreme") is not None:
        values.append(setup["extreme"])
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.05, hi + span * 0.05

    def y(v: float) -> float:
        return PAD_T + (hi - v) / (hi - lo) * plot_h

    def x(i: float) -> float:
        return PAD_L + (i + 0.5) * step

    def idx(value) -> float:
        return (_epoch(value) - times[0]) / bar_seconds

    right = PAD_L + plot_w
    left = float(PAD_L)

    def clamp_x(i: float) -> float:
        return min(right, max(left, x(i)))

    def box(x0: float, x1: float, v_hi: float, v_lo: float, cls: str, label: str = "", label_below: bool = False) -> str:
        top, bottom = max(PAD_T, y(v_hi)), min(PAD_T + plot_h, y(v_lo))
        out = f'<rect class="{cls}" x="{x0:.1f}" y="{top:.1f}" width="{max(1.0, x1 - x0):.1f}" height="{max(1.0, bottom - top):.1f}"/>'
        return out + (f'<text class="sc-box-label" x="{x0 + 3:.1f}" y="{(bottom - 4 if label_below else top + 11):.1f}">{label}</text>' if label else "")

    out = [f'<svg class="sc" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(setup["family"])} setup {escape(setup["direction"])}">']
    for z in zones or []:
        out.append(box(clamp_x(idx(z["from"])), right, z["high"], z["low"], "sc-zone is-other"))
    if setup["family"] != "zonesweep":
        out.append(box(clamp_x(idx(setup["range_first_at"])), clamp_x(idx(setup["placed_at"])), rng_hi, rng_lo, "sc-range", "Range", label_below=True))
    own = "Order block" if setup["family"] == "sweep" else ("Aanbod" if short else "Vraag")
    out.append(box(clamp_x(idx(setup["zone_at"])), right, setup["zone_high"], setup["zone_low"], "sc-zone", own))

    for i, (_, o, h, low, c) in enumerate(shown):
        cls = "sc-up" if c >= o else "sc-down"
        out.append(f'<line class="sc-wick {cls}" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(h):.1f}" y2="{y(low):.1f}"/>'
                   f'<rect class="sc-body {cls}" x="{x(i) - step * 0.34:.1f}" y="{min(y(o), y(c)):.1f}" width="{step * 0.68:.1f}" height="{max(1.0, abs(y(o) - y(c))):.1f}"/>')
    if setup.get("sweep_at") is not None and setup.get("extreme") is not None:
        sx, sy = clamp_x(idx(setup["sweep_at"])), y(setup["extreme"])
        out.append(f'<line class="sc-sweep" x1="{sx - 5:.1f}" x2="{sx + 5:.1f}" y1="{sy:.1f}" y2="{sy:.1f}"/>'
                   f'<text class="sc-box-label" x="{sx + 7:.1f}" y="{sy + 4:.1f}">Sweep</text>')

    placed, last_y = [], -1e9
    for v, cls, text in sorted(marks, key=lambda m: y(m[0])):
        label_y = max(y(v), last_y + LABEL_GAP)
        placed.append((v, cls, text, label_y))
        last_y = label_y
    for v, cls, text, label_y in placed:
        out.append(f'<line class="sc-line {cls}" x1="{x(n - 1):.1f}" x2="{right:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="sc-label {cls}" x="{right + 6:.1f}" y="{label_y + 4:.1f}">{escape(text)}</text>')
    out.append("</svg>")
    return "".join(out)


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


# De kaartgrafiek van Zone-radar en Zone-sweep op Kansen: dezelfde tekenstijl als de galerij (range_sweep_svg), maar met een viewBox die op een
# telefoonkaart 1:1 schaalt (de kaart is op 375px 317 pixels breed). 560 breed maakte van 13px labels 8px; zo blijven ze 12px (CSS .sc.is-card).
CARD_W, CARD_H = 316, 180
CARD_PAD_L, CARD_PAD_T, CARD_PAD_B = 4, 10, 10
CARD_CHAR_W = 7.4           # 12px monospace
CARD_FUTURE = 5
CARD_LABEL_GAP = 15
CARD_MARK_CHAR_W = 6.6     # 11px tekst van markeringen en vlakken


def zone_svg(candles: list[list], coin: str, direction: str, zone: Optional[dict], lines: list[tuple], points: list[tuple] = (),
             target_zone: Optional[dict] = None, price: Optional[float] = None, limit: Optional[float] = None) -> str:
    """candles: [[unix_s, open, high, low, close], ...] oud naar nieuw, het venster kiest de aanroeper (card_chart.window). zone: {"low", "high",
    "from" (unix_s of None = vanaf links), "label"}; target_zone idem zonder from. lines: [(prijs, klasse, tekst)] zoals sc-limit, sc-stop,
    sc-target. points: [(unix_s, prijs, tekst)], een markering op de candle die ertoe doet (ontstaan, prik, herstel). zone None: geen vlak, alleen
    lijnen (de POC-radar: een POC is één prijs). Geeft '' zonder candles."""
    if not candles:
        return ""
    n = len(candles)
    times = [float(c[0]) for c in candles]
    diffs = sorted(b - a for a, b in zip(times, times[1:]))
    bar_seconds = diffs[len(diffs) // 2] if diffs else 3600.0
    marks = list(lines) + ([(price, "sc-price", f"Nu {price_text.nl(price)}")] if price else [])
    pad_r = int(max([len(m[2]) for m in marks] + [8]) * CARD_CHAR_W + 10)
    plot_w, plot_h = CARD_W - CARD_PAD_L - pad_r, CARD_H - CARD_PAD_T - CARD_PAD_B
    step = plot_w / (n + CARD_FUTURE)
    values = [c[3] for c in candles] + [c[2] for c in candles] + [m[0] for m in marks] + [p[1] for p in points]
    if zone:
        values += [zone["low"], zone["high"]]
    if target_zone:
        values += [target_zone["low"], target_zone["high"]]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.06, hi + span * 0.06
    right, left = CARD_PAD_L + plot_w, float(CARD_PAD_L)

    def y(v: float) -> float:
        return CARD_PAD_T + (hi - v) / (hi - lo) * plot_h

    def x(i: float) -> float:
        return CARD_PAD_L + (i + 0.5) * step

    def at(ts: Optional[float]) -> float:
        return left if ts is None else min(right, max(left, x((ts - times[0]) / bar_seconds)))

    taken: list[tuple[float, float, float, float]] = []      # tekstvlakken die er al staan: een markering zoekt een plek ernaast

    def box(x0: float, v_hi: float, v_lo: float, cls: str, label: str, below: bool, at_end: bool = False) -> str:
        top, bottom = max(CARD_PAD_T, y(v_hi)), min(CARD_PAD_T + plot_h, y(v_lo))
        ly = bottom + 13 if below else top - 4
        ly = min(CARD_H - 2, max(11.0, ly))
        # De eigen zone draagt zijn naam aan het rechteinde: links begint hij bij de ontstaanscandle, waar de markering al een naam heeft.
        lx, anchor = (right - 3, "end") if at_end else (x0 + 3, "start")
        w = len(label) * CARD_MARK_CHAR_W
        taken.append((lx - w if at_end else lx, ly - 11, lx if at_end else lx + w, ly + 2))
        return (f'<rect class="{cls}" x="{x0:.1f}" y="{top:.1f}" width="{max(1.0, right - x0):.1f}" height="{max(1.0, bottom - top):.1f}"/>'
                f'<text class="sc-box-label" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{escape(label)}</text>')

    short = direction == "short"
    what = zone["label"] if zone else (lines[0][2] if lines else "")
    out = [f'<svg class="sc is-card" viewBox="0 0 {CARD_W} {CARD_H}" role="img" aria-label="{escape(coin)} {escape(direction)}: {escape(what)}" '
           f'data-chart-coin="{escape(coin)}" data-hi="{hi:.8g}" data-lo="{lo:.8g}" data-pad-t="{CARD_PAD_T}" data-plot-h="{plot_h}"'
           + (f' data-level="{limit:.8g}"' if limit is not None else "") + ">"]
    if target_zone:
        # De doelzone ligt aan de overkant: label aan de kant weg van de eigen zone, zodat de twee namen nooit op elkaar staan.
        out.append(box(left, target_zone["high"], target_zone["low"], "sc-zone is-target", target_zone["label"], below=short))
    if zone:
        out.append(box(at(zone.get("from")), zone["high"], zone["low"], "sc-zone", zone["label"], below=not short, at_end=True))
    for i, (_, o, h, low, c) in enumerate(candles):
        cls = "sc-up" if c >= o else "sc-down"
        out.append(f'<line class="sc-wick {cls}" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(h):.1f}" y2="{y(low):.1f}"/>'
                   f'<rect class="sc-body {cls}" x="{x(i) - step * 0.34:.1f}" y="{min(y(o), y(c)):.1f}" width="{step * 0.68:.1f}" height="{max(1.0, abs(y(o) - y(c))):.1f}"/>')

    def free(r: tuple) -> bool:
        return (r[0] >= left and r[2] <= right and r[1] >= 0 and r[3] <= CARD_H
                and not any(r[0] < t[2] and t[0] < r[2] and r[1] < t[3] and t[1] < r[3] for t in taken))

    for ts, v, text in points:
        px, py = at(ts), y(v)
        w = len(text) * CARD_MARK_CHAR_W
        # Rechts, links, onder of boven de stip: de eerste plek zonder andere tekst. Twee markeringen dicht bij elkaar (ontstaan en herstel)
        # stonden anders op elkaar.
        options = [(px + 8, py + 4, "start"), (px - 8, py + 4, "end"), (px, py + 18, "middle"), (px, py - 9, "middle")]
        rects = [((tx if a == "start" else tx - w if a == "end" else tx - w / 2), ty - 11, (tx + w if a == "start" else tx if a == "end" else tx + w / 2), ty + 2)
                 for tx, ty, a in options]
        k = next((i for i, r in enumerate(rects) if free(r)), 0)
        taken.append(rects[k])
        tx, ty, anchor = options[k]
        out.append(f'<circle class="sc-mark" cx="{px:.1f}" cy="{py:.1f}" r="4.5"/>'
                   f'<text class="sc-mark-label" x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{escape(text)}</text>')
    placed, last_y = [], -1e9
    for v, cls, text in sorted(marks, key=lambda m: y(m[0])):
        label_y = max(y(v), last_y + CARD_LABEL_GAP)
        placed.append((v, cls, text, label_y))
        last_y = label_y
    for v, cls, text, label_y in placed:
        out.append(f'<line class="sc-line {cls}" x1="{x(n - 1):.1f}" x2="{right:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="sc-label {cls}" x="{right + 6:.1f}" y="{min(CARD_H - 2, label_y + 4):.1f}">{escape(text)}</text>')
    out.append("</svg>")
    return "".join(out)
