"""Voorbeelden voor het plan: het model zelf rekent op getekende (synthetische) candles uit tests/hespulse_model/synth.py en de uitvoer wordt
getekend als candles met de niveaus. Er is geen echte trade bij betrokken. De getallen komen uit app/model.py, niet uit de hand.
Alle voorbeelden zijn een short: de long-testdata is gespiegeld (prijs -> 200 - prijs)."""
import html
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app import model as M  # noqa: E402
from app import model_chart as MC  # noqa: E402
from tests.hespulse_model import synth as S  # noqa: E402
from tests.hespulse_model.test_model import base_rows, run  # noqa: E402

INK, GREY, RED, GREEN, ZONE = "#1b2324", "#8a9698", "#b3261e", "#1e7a46", "#eceff0"
RUN_TAIL = [[107.6, 107.65, 106.9, 107.0], [107.0, 107.05, 106.0, 106.1], [106.1, 106.15, 105.0, 105.1],
            [105.1, 105.15, 104.0, 104.1], [104.1, 104.2, 103.9, 104.0], [104.0, 104.1, 103.6, 103.7]]


def mirror(rows):
    return [[200 - o, 200 - l, 200 - h, 200 - c] for o, h, l, c in rows]


def fmt(v):
    return f"{v:.2f}".replace(".", ",")


def scenario(rows):
    mir = mirror(rows)
    return run(mir)[0], S.frames(mir)["15m"]


def hhmm(ts, tz="Europe/Amsterdam"):
    return pd.Timestamp(ts).tz_convert(tz).strftime("%d-%m %H:%M")


def chart(sc, b15, caption, marks, entry=True, extra_lines=(), start_hours=9, after_hours=2.0):
    """Candles met de niveaus. marks: (tijd van de candle, 'high'|'low'|'close', tekst, 'above'|'below')."""
    t0 = sc["discovered_at"] - pd.Timedelta(hours=start_hours)
    t_end = pd.Timestamp((sc["entry"]["known_at"] if entry and sc.get("entry") else sc["ended_at"])) + pd.Timedelta(hours=after_hours)
    w = b15[(b15["timestamp"] >= t0) & (b15["timestamp"] <= t_end)].reset_index(drop=True)
    n = len(w)
    W, H, PL, PR, PT, PB = 640, 300, 10, 150, 16, 24
    e = sc.get("entry") if entry else None
    prices = [w["high"].max(), w["low"].min()]
    if e:
        prices += [e["stop"], e["take"]]
    lo, hi = min(prices) - 0.4, max(prices) + 0.4
    X = lambda i: PL + (i + 0.5) / n * (W - PL - PR)
    Y = lambda p: PT + (hi - p) / (hi - lo) * (H - PT - PB)
    idx = lambda ts: int((w["timestamp"] <= pd.Timestamp(ts)).sum()) - 1
    step = (W - PL - PR) / n
    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="dia">']
    right = W - PR
    if e:
        a = idx(e["known_at"]) + 1
        for lim, oth, fill in ((e["limit"], e["stop"], "rgba(27,35,36,0.18)"), (e["limit"], e["take"], "rgba(27,35,36,0.06)")):
            out.append(f'<rect x="{X(a) - step / 2:.1f}" y="{Y(max(lim, oth)):.1f}" width="{right - X(a) + step / 2:.1f}" height="{abs(Y(lim) - Y(oth)):.1f}" fill="{fill}"/>')
        for key, lab in (("fvg", "FVG"), ("ob", "OB")):
            lo_, hi_ = e[f"{key}_low"], e[f"{key}_high"]
            i0 = idx(e[f"{key}_at"])
            out.append(f'<rect x="{X(i0) - step / 2:.1f}" y="{Y(hi_):.1f}" width="{X(a) - X(i0) + step:.1f}" height="{max(2, Y(lo_) - Y(hi_)):.1f}" fill="{ZONE}" stroke="{GREY}" stroke-width="0.8"/>')
    for i, r in w.iterrows():
        x = X(i)
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{Y(r["high"]):.1f}" y2="{Y(r["low"]):.1f}" stroke="#c9d0d1" stroke-width="1.6"/>')
    pts = " ".join(f"{X(i):.1f},{Y(c):.1f}" for i, c in enumerate(w["close"]))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>')
    lines = [(sc["range_high"], f"range high {fmt(sc['range_high'])}", INK, False), (sc["range_low"], f"range low {fmt(sc['range_low'])}" + (" (doel)" if e else ""), GREEN if e else INK, False),
             (sc["eq"], f"evenwicht {fmt(sc['eq'])}", GREY, True)]
    lines = [l for l in lines if lo <= l[0] <= hi]
    if e:
        lines += [(e["pool"], f"pool {fmt(e['pool'])}", GREY, True), (e["stop"], f"stop {fmt(e['stop'])}", RED, False), (e["limit"], f"limiet {fmt(e['limit'])}", INK, False)]
    lines += list(extra_lines)
    taken = []
    for p, label, col, dashed in sorted(lines, key=lambda z: -z[0]):
        y = Y(p)
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        out.append(f'<line x1="{PL}" x2="{right + 6}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="1"{dash}/>')
        ty = y + 3.5
        while any(abs(ty - t) < 11 for t in taken):
            ty += 11
        taken.append(ty)
        out.append(f'<text x="{right + 10}" y="{ty:.1f}" class="t s" fill="{col}">{html.escape(label)}</text>')
    for ts, where, text, side in marks:
        i = idx(ts)
        if i < 0 or i >= n:
            continue
        r = w.iloc[i]
        p = r["high"] if where == "high" else r["low"] if where == "low" else r["close"]
        dy = -9 if side == "above" else 14
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(p):.1f}" r="3" fill="{INK}"/>')
        out.append(f'<text x="{X(i):.1f}" y="{Y(p) + dy:.1f}" text-anchor="middle" class="t s">{html.escape(text)}</text>')
    out.append("</svg>")
    return f'<figure class="ex">{"".join(out)}<figcaption>{caption}</figcaption></figure>'


def voorbeeld_een():
    """Een complete short: het model zelf, van ontdekt tot plan."""
    sc, b15 = scenario(base_rows())
    e = sc["entry"]
    sw = next(s for s in sc["steps"] if s["stap"] == "sweep")
    sh = next(s for s in sc["steps"] if s["stap"] == "shift")
    q = pd.Timedelta(minutes=15)
    marks = [(sw["prik_at"], "high", "sweep", "above"), (pd.Timestamp(sh["at"]) - q, "close", "shift, plan klaar", "below")]
    fig = chart(sc, b15, "Getekende koersen, gerekend met de code van het model. Het grijze vak onder de limiet is het risico, het lichtgrijze vak het doel. Geen echte trade.", marks)
    rows = "".join(f"<tr><td>{html.escape(s)}</td><td>{html.escape(t)}</td><td>{html.escape(x.replace('CHOCH', 'CHoCH'))}</td></tr>" for s, t, x in MC.step_rows(sc))
    table = f'<table><tr><th>Stap</th><th>Moment</th><th>Wat het model vaststelde</th></tr>{rows}</table>'
    return fig, table, e


def voorbeeld_twee():
    """Een run: de koers loopt door de pool en sluit er niet terug. Het model geeft dan geen plan."""
    sc, b15 = scenario(base_rows(tail=RUN_TAIL, after=8))
    att = sc["attempts"][0]
    marks = [(pd.Timestamp(att["at"]) - pd.Timedelta(minutes=15), "close", "run", "below")]
    extra = [(att["pool"], f"pool {fmt(att['pool'])}", GREY, True)]
    fig = chart(sc, b15, "Dezelfde range, een andere uitkomst: de koers loopt door de pool en sluit er niet onder terug. Het model noteert 'run' en geeft geen plan.", marks,
                entry=False, extra_lines=extra, after_hours=0.5)
    reden = M.FAIL_REASONS["run"]
    return fig, reden, [a["reden"] for a in sc["attempts"]]
