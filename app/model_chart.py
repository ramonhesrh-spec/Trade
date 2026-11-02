"""De getekende kaart van één HesPulse-scenario voor de controle achteraf (scripts/model_kaarten.py, preregistratie §10 poort 3): 15m-candles met
de range (premium en discount, evenwicht), de pool, de sweep, de shift-candle met de top ervoor, FVG en order block, limiet, stop en doel, de
naakte POC's die kandidaat waren, en een verticale streep op elk moment dat een stap herkenbaar was. Puur: een scenario uit model.scenarios en
een DataFrame met 15m-candles erin, een SVG-tekst eruit. Vaste kleuren (het bestand wordt los geopend, buiten de app)."""
from html import escape
from typing import Optional

import pandas as pd

from app import price_text

W, H = 960, 420
PAD_L, PAD_R, PAD_T, PAD_B = 10, 150, 16, 34
LEAD = pd.Timedelta(hours=6)
TAIL = pd.Timedelta(hours=8)
STEP_COLORS = {"ontdekt": "#7c8a99", "sweep": "#d9822b", "shift": "#4b8bf5", "displacement": "#8e6cd9", "entry": "#16a085"}
STEP_LETTERS = {"ontdekt": "A", "sweep": "S", "shift": "C", "displacement": "D", "entry": "B"}


def window(sc: dict, b15: pd.DataFrame) -> pd.DataFrame:
    """Van een paar uur voor het ontdekken tot een paar uur na de laatste stap (of het einde), hoogstens 220 candles."""
    times = [s["at"] for s in sc["steps"]] + [a["at"] for a in sc["attempts"]]
    if sc.get("ended_at") is not None:
        times.append(sc["ended_at"])
    start = sc["discovered_at"] - LEAD
    for s in sc["steps"]:
        if s["stap"] == "sweep":
            start = min(start, s["prik_at"] - LEAD)
    end = max(times) + TAIL
    w = b15[(b15["timestamp"] >= start) & (b15["timestamp"] <= end)].reset_index(drop=True)
    return w.iloc[-220:].reset_index(drop=True) if len(w) > 220 else w


def full_svg(sc: dict, b15: pd.DataFrame) -> str:
    w = window(sc, b15)
    if w.empty:
        return ""
    e = sc.get("entry") or {}
    steps = {s["stap"]: s for s in sc["steps"]}
    prices = list(w["low"]) + list(w["high"]) + [sc["range_low"], sc["range_high"], sc["pool0"]["level"]]
    prices += [v for v in (e.get("stop"), e.get("take"), e.get("limit")) if v is not None]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.04, hi + span * 0.04
    n = len(w)
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    step = plot_w / max(n, 1)
    t0 = w["timestamp"].iloc[0]
    bar = pd.Timedelta(minutes=15)

    def y(v: float) -> float:
        return PAD_T + (hi - v) / (hi - lo) * plot_h

    def x(ts) -> float:
        k = (pd.Timestamp(ts) - t0) / bar
        return PAD_L + min(max(k, 0), n) * step

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" '
           f'aria-label="{escape(sc.get("coin", ""))} {sc["direction"]}, HesPulse-scenario" font-family="system-ui, sans-serif" font-size="11">',
           f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0f1416"/>']
    right = PAD_L + plot_w
    # Range: discount en premium als vlak vanaf de range, het evenwicht gestreept.
    rx = x(sc["range_at"])
    lower, upper = (sc["range_low"], sc["eq"]), (sc["eq"], sc["range_high"])
    disc, prem = (lower, upper) if sc["direction"] == "long" else (upper, lower)
    out.append(f'<rect x="{rx:.1f}" y="{y(disc[1]):.1f}" width="{right - rx:.1f}" height="{y(disc[0]) - y(disc[1]):.1f}" fill="#16a085" opacity="0.08"/>')
    out.append(f'<rect x="{rx:.1f}" y="{y(prem[1]):.1f}" width="{right - rx:.1f}" height="{y(prem[0]) - y(prem[1]):.1f}" fill="#c0392b" opacity="0.07"/>')
    labels = [(sc["eq"], "#9aa5b1", f"Evenwicht {price_text.nl(sc['eq'])}", "4 3"),
              (sc["range_high"], "#9aa5b1", f"Range boven {price_text.nl(sc['range_high'])}", ""),
              (sc["range_low"], "#9aa5b1", f"Range onder {price_text.nl(sc['range_low'])}", ""),
              (sc["pool0"]["level"], "#d9822b", f"Pool {price_text.nl(sc['pool0']['level'])}", "2 2")]
    if "sweep" in steps and abs(steps["sweep"]["pool"] - sc["pool0"]["level"]) > 1e-12:
        labels.append((steps["sweep"]["pool"], "#d9822b", f"Gesweepte pool {price_text.nl(steps['sweep']['pool'])}", "2 2"))
    for c in sc.get("candidates") or []:
        if c["kind"] == "poc":
            labels.append((c["price"], "#b58900", f"{c['label']} {price_text.nl(c['price'])}", "1 3"))
    # FVG en order block als vlak vanaf hun candle.
    if e:
        for lo_, hi_, at, color, name in ((e["ob_low"], e["ob_high"], e["ob_at"], "#8e6cd9", "OB"), (e["fvg_low"], e["fvg_high"], e["fvg_at"], "#4b8bf5", "FVG")):
            fx = x(at)
            out.append(f'<rect x="{fx:.1f}" y="{y(hi_):.1f}" width="{right - fx:.1f}" height="{max(y(lo_) - y(hi_), 1):.1f}" fill="{color}" opacity="0.18"/>')
            out.append(f'<text x="{fx + 3:.1f}" y="{y(hi_) - 3:.1f}" fill="{color}">{name}</text>')
        labels += [(e["limit"], "#e8eef0", f"Limiet {price_text.nl(e['limit'])}", ""), (e["stop"], "#e74c3c", f"Stop {price_text.nl(e['stop'])}", ""),
                   (e["take"], "#2ecc71", f"Doel {price_text.nl(e['take'])} ({'range' if e['target_kind'] == 'range' else e['target_label']})", "")]
    # Candles.
    for i, c in enumerate(w.itertuples()):
        cx = PAD_L + (i + 0.5) * step
        up = c.close >= c.open
        color = "#2ecc71" if up else "#e74c3c"
        out.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(c.high):.1f}" y2="{y(c.low):.1f}" stroke="{color}" stroke-width="1"/>')
        top, bot = y(max(c.open, c.close)), y(min(c.open, c.close))
        out.append(f'<rect x="{cx - step * 0.35:.1f}" y="{top:.1f}" width="{step * 0.7:.1f}" height="{max(bot - top, 0.8):.1f}" fill="{color}"/>')
    # Shift: de top van vóór de sweep tot de shift-candle, en die candle omlijnd.
    if "shift" in steps:
        sh = steps["shift"]
        tx = x(sh["top_at"])
        cx = x(sh["at"] - bar)
        out.append(f'<line x1="{tx:.1f}" x2="{cx + step:.1f}" y1="{y(sh["top"]):.1f}" y2="{y(sh["top"]):.1f}" stroke="#4b8bf5" stroke-dasharray="3 2"/>')
        out.append(f'<text x="{tx + 2:.1f}" y="{y(sh["top"]) - 3:.1f}" fill="#4b8bf5">Top {price_text.nl(sh["top"])}</text>')
        out.append(f'<rect x="{cx:.1f}" y="{PAD_T}" width="{step:.1f}" height="{plot_h}" fill="none" stroke="#4b8bf5" stroke-width="1.2"/>')
    if "sweep" in steps:
        sw = steps["sweep"]
        px = x(sw["prik_at"]) + step / 2
        out.append(f'<circle cx="{px:.1f}" cy="{y(sw["extreme"]):.1f}" r="4.5" fill="none" stroke="#d9822b" stroke-width="2"/>')
        out.append(f'<text x="{px + 6:.1f}" y="{y(sw["extreme"]) + 12:.1f}" fill="#d9822b">Sweep {price_text.nl(sw["extreme"])}</text>')
    # Horizontale niveaus met naam en prijs rechts; labels uit elkaar geschoven.
    placed: list[float] = []
    for v, color, text, dash in sorted(labels, key=lambda l: -l[0]):
        ly = y(v)
        out.append(f'<line x1="{PAD_L}" x2="{right:.1f}" y1="{ly:.1f}" y2="{ly:.1f}" stroke="{color}" stroke-width="1" '
                   + (f'stroke-dasharray="{dash}" ' if dash else "") + 'opacity="0.85"/>')
        ty = ly + 4
        while any(abs(ty - p) < 12 for p in placed):
            ty += 12
        placed.append(ty)
        out.append(f'<text x="{right + 6:.1f}" y="{ty:.1f}" fill="{color}">{escape(text)}</text>')
    # Elke stap op het moment van herkenbaarheid (het sluiten van de candle), met een letter onderaan.
    marks = [(s["stap"], s["at"]) for s in sc["steps"]]
    for stap, at in marks:
        mx = x(at)
        color = STEP_COLORS.get(stap, "#9aa5b1")
        out.append(f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="{PAD_T}" y2="{PAD_T + plot_h}" stroke="{color}" stroke-dasharray="2 3" opacity="0.8"/>')
        out.append(f'<text x="{mx:.1f}" y="{H - 18}" fill="{color}" text-anchor="middle" font-weight="700">{STEP_LETTERS.get(stap, "?")}</text>')
    for a in sc["attempts"]:
        mx = x(a["at"])
        out.append(f'<text x="{mx:.1f}" y="{H - 4}" fill="#e74c3c" text-anchor="middle">✕</text>')
    out.append(f'<text x="{PAD_L}" y="{H - 4}" fill="#9aa5b1">15m · {w["timestamp"].iloc[0]:%d-%m %H:%M} tot {w["timestamp"].iloc[-1]:%d-%m %H:%M} UTC</text>')
    out.append("</svg>")
    return "".join(out)


def step_rows(sc: dict, tz: Optional[str] = "Europe/Amsterdam") -> list[tuple[str, str, str]]:
    """(stap, herkenbaar op, toelichting) voor de tabel onder de tekening, in volgorde van tijd. Mislukte pogingen met hun reden."""
    from app import model
    rows = []
    for s in sc["steps"]:
        note = ""
        if s["stap"] == "sweep":
            note = f"pool {price_text.nl(s['pool'])}, uiterste {price_text.nl(s['extreme'])}, prik {s['prik_at'].tz_convert(tz):%H:%M}"
        elif s["stap"] == "shift":
            note = f"slot boven de top {price_text.nl(s['top'])}" + (f", {s['label']}" if s.get("label") else "")
        elif s["stap"] == "displacement":
            note = f"candles gesloten {s['gesloten_at'].tz_convert(tz):%d-%m %H:%M}"
        elif s["stap"] == "ontdekt":
            note = f"pool {price_text.nl(sc['pool0']['level'])}, range {price_text.nl(sc['range_low'])} tot {price_text.nl(sc['range_high'])}"
        elif s["stap"] == "entry" and sc.get("entry"):
            e = sc["entry"]
            note = (f"limiet {price_text.nl(e['limit'])}, stop {price_text.nl(e['stop'])}, doel {price_text.nl(e['take'])}, R:R "
                    f"{e['rr']:.1f}".replace(".", ",") + (", OB-overlap" if e["ob_overlap"] else "")
                    + ({True: ", POC-samenval", False: "", None: ""}[e["poc_samenval"]]))
        rows.append((s["stap"], s["at"], note))
    for a in sc["attempts"]:
        rows.append(("mislukt", a["at"], model.FAIL_REASONS.get(a["reden"], a["reden"])))
    return [(stap, f"{at.tz_convert(tz):%d-%m %H:%M}", note) for stap, at, note in sorted(rows, key=lambda r: r[1])]
