"""De eigen kaartgrafiek per soort op Kansen, voor Zone-radar, Zone-sweep en POC-radar: de tekenstijl van de galerij (setup_chart.zone_svg) op het
tijdframe van de zone. Pure functies: de route haalt de candles uit de minuutcache en geeft de rij uit zone_radar_setups of zone_sweep_setups
mee. Structuur tekent zijn eigen momentopname (setup_chart.setup_svg) en komt hier niet langs.

Zone-radar: de zone als vlak vanaf de ontstaanscandle (zone_key) met een markering op die candle, de doelzone als vlak, limiet, stop en doel.
Zone-sweep: daarbij de prik (sweep_at, het uiterste) en de herstelcandle (de laatste gesloten candle vóór placed_at).
HesPulse-model: een eigen tekening in analistenstijl (model_svg, onderaan), op het tijdframe uit model_tf."""
from html import escape
from typing import Optional

import pandas as pd

from app import poc, price_text, setup_chart, trade_plan as tp, zone_radar
from app.ladder import spread

LEAD_BARS = 4          # een paar candles vóór het ontstaan, zodat je ziet waar de beweging vandaan kwam
MIN_BARS = 40          # een jonge zone krijgt toch genoeg aanloop om de structuur te lezen
MAX_BARS = 80          # op ~200 pixels plotbreedte is een candle dan nog 2 pixels; ouder ontstaan wordt tegen de linkerrand gezet
TF_TEXT = {"1h": "1u", "2h": "2u", "4h": "4u"}


def candle_tf(tf: str) -> str:
    """Het tijdframe uit de candlecache van de web-app (1h of 4h); een 2u-zone tekent op 1u, waar zijn ontstaan als twee candles staat."""
    return "4h" if tf == "4h" else "1h"


def window(candles: list[list], origin_ts: Optional[float]) -> int:
    """Index van de eerste candle om te tonen: de ontstaanscandle met LEAD_BARS ervoor, minstens MIN_BARS en hoogstens MAX_BARS tot nu."""
    n = len(candles)
    if origin_ts is None:
        return max(0, n - MIN_BARS)
    i = next((k for k, c in enumerate(candles) if c[0] >= origin_ts), n - 1)
    return max(0, n - MAX_BARS, min(n - MIN_BARS, i - LEAD_BARS))


def _ts(value) -> Optional[float]:
    if value is None:
        return None
    t = pd.Timestamp(value)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).timestamp()


def _candle_at(candles: list[list], ts: float) -> Optional[list]:
    return next((c for c in reversed(candles) if c[0] <= ts), None)


def _lines(direction: str, limit: float, stop: float, take: Optional[float]) -> list[tuple]:
    out = [(limit, "sc-limit", f"Limiet {price_text.nl(limit)}"), (stop, "sc-stop", f"Stop {price_text.nl(stop)}")]
    if take is not None:
        out.append((take, "sc-target", f"Doel {price_text.nl(take)}"))
    return out


def _target_zone(row: dict) -> Optional[dict]:
    if row.get("target_low") is None or row.get("target_high") is None or row.get("take_profit") is None:
        return None
    return {"low": row["target_low"], "high": row["target_high"], "label": f"Doelzone {TF_TEXT.get(row.get('target_tf'), row.get('target_tf') or '')}".strip()}


def _origin_point(candles: list[list], origin: Optional[float], direction: str) -> list[tuple]:
    c = _candle_at(candles, origin) if origin is not None else None
    if c is None or c[0] < candles[0][0]:
        return []
    return [(c[0], c[3] if direction == "long" else c[2], "Ontstaan")]


def zone_radar_svg(row: dict, candles: list[list], price: Optional[float]) -> str:
    """Een rij uit zone_radar_setups. `candles` op candle_tf(zone-tf), alle die de cache heeft; het venster kiest deze functie."""
    if not candles:
        return ""
    origin = zone_radar.zone_origin(row.get("zone_key", ""))
    origin_ts = float(origin[2]) if origin else None
    shown = candles[window(candles, origin_ts):]
    plan = tp.limit_plan(row["direction"], row["zone_low"], row["zone_high"], row["stop_loss"], row["take_profit"])
    limit = plan.limit if plan else (row["zone_high"] if row["direction"] == "long" else row["zone_low"])
    tf = origin[0] if origin else row.get("tf")
    zone = {"low": row["zone_low"], "high": row["zone_high"], "from": origin_ts,
            "label": f"{'Vraag' if row['direction'] == 'long' else 'Aanbod'} {TF_TEXT.get(tf, tf)}"}
    return setup_chart.zone_svg(shown, row["coin"], row["direction"], zone, _lines(row["direction"], limit, row["stop_loss"], row["take_profit"]),
                                _origin_point(shown, origin_ts, row["direction"]), _target_zone(row), price, limit)


def zone_sweep_svg(row: dict, candles: list[list], price: Optional[float]) -> str:
    """Een rij uit zone_sweep_setups: zone vanaf zone_at, de prik op sweep_at bij het uiterste, de herstelcandle vlak vóór placed_at."""
    if not candles:
        return ""
    origin_ts = _ts(row.get("zone_at"))
    shown = candles[window(candles, origin_ts):]
    zone = {"low": row["zone_low"], "high": row["zone_high"], "from": origin_ts,
            "label": f"{'Vraag' if row['direction'] == 'long' else 'Aanbod'} {TF_TEXT.get(row['tf'], row['tf'])}"}
    points = _origin_point(shown, origin_ts, row["direction"])
    sweep_ts = _ts(row.get("sweep_at"))
    if sweep_ts is not None and row.get("extreme") is not None:
        points.append((sweep_ts, row["extreme"], "Prik"))
    placed = _ts(row.get("placed_at"))
    bar = (shown[1][0] - shown[0][0]) if len(shown) > 1 else 3600
    rec = _candle_at(shown, placed - bar) if placed is not None else None
    if rec is not None and (sweep_ts is None or rec[0] > sweep_ts):
        points.append((rec[0], rec[4], "Herstel"))
    return setup_chart.zone_svg(shown, row["coin"], row["direction"], zone,
                                _lines(row["direction"], row["limit_price"], row["stop_loss"], row.get("take_profit")),
                                points, _target_zone(row), price, row["limit_price"])


def poc_tf(period: str) -> str:
    """Een dag-POC op 1u (zijn dag is 24 candles), een week-POC op 4u (zijn week is 42 candles)."""
    return "4h" if period == "week" else "1h"


def poc_radar_svg(row: dict, candles: list[list], price: Optional[float]) -> str:
    """Een rij uit poc_radar_setups: geen zonevlak (een POC is één prijs), de lijnen limiet op de POC, stop en doel met naam en prijs, en een
    markering op de eerste candle van de periode waar de POC uit komt. `candles` op poc_tf(periode)."""
    if not candles:
        return ""
    start = _ts(row.get("period_start"))
    shown = candles[window(candles, start):]
    limit = row["limit_price"]
    lines = [(limit, "sc-limit", f"Limiet op POC {price_text.nl(limit)}"), (row["stop_loss"], "sc-stop", f"Stop {price_text.nl(row['stop_loss'])}")]
    if row.get("take_profit") is not None:
        lines.append((row["take_profit"], "sc-target", f"Doel {price_text.nl(row['take_profit'])}"))
    c = _candle_at(shown, start) if start is not None else None
    name = poc.period_text(row["period"], row["period_start"])
    points = [(c[0], row["level"], name[0].upper() + name[1:])] if c is not None and c[0] >= shown[0][0] else []
    return setup_chart.zone_svg(shown, row["coin"], row["direction"], None, lines, points, _target_zone(row), price, limit)


# ---------------------------------------------------------------------------------------------------------------------------------------
# HesPulse-model: de kaart zoals een analist hem tekent (CEO, 2026-11-02). Rustige candles zonder kleur, de 4u-range met evenwicht over de
# breedte, de zones van het model als licht vlak dat tot voorbij de laatste candle doorloopt met de naam erin, swing, sweep en structuurbreuk
# als korte lijn met label, en limiet, stop en doel met prijs rechts. Alles komt uit de opgeslagen rij (model_card.row_of en de stappen van
# model.scenarios); de tekening rekent niets opnieuw uit en kiest nooit een richting. Kleuren in CSS (.mc-*), zodat licht en donker kloppen.

MODEL_W, MODEL_H = 316, 236          # de kaart is op 375px 317 breed: 1:1, dus 11px tekst blijft 11px
# "Groot": dezelfde tekening hoger, zodat dicht bijeen liggende niveaus uit elkaar gaan. 340 breed past op 375px tussen de marges van het
# venster (343): breder liet de browser hem verkleinen en werd 11px tekst 10,5px.
MODEL_BIG_W, MODEL_BIG_H = 340, 600
MODEL_PAD_L, MODEL_PAD_T, MODEL_PAD_B = 4, 22, 8
MODEL_CHAR_W = 6.6                   # 11px: mono is 0,6 em per teken, de schreefloze letter is smaller
MODEL_GAP = 13                       # minimale afstand tussen twee labels rechts (ladder.spread)
MODEL_FUTURE_PX = 56                 # lege strook rechts van de laatste candle: daar staan de namen van de zones, nooit over een candle
# Het getoonde tijdframe: het kleinste waarop de range vanaf zijn swing tot nu in MODEL_MAX_BARS candles past, zodat range en entry samen in
# beeld zijn (een range leeft tot 60 candles van 4u, dus 4u past altijd). 96 candles op ~200 pixels is 2 pixels per candle: nog leesbaar.
MODEL_MAX_BARS = 96
MODEL_LEAD = 3                       # candles vóór de swing, zodat je ziet waar de range begon
MODEL_TFS = (("15m", 900), ("1h", 3600), ("4h", 14400))
MODEL_TF_TEXT = {900: "15m", 3600: "1u", 14400: "4u"}
SHIFT_WORDS = {"CHOCH": "CHoCH", "BOS": "BOS", None: "MSB"}


def _model_detail(row: dict) -> dict:
    import json
    try:
        return json.loads(row.get("steps") or "{}") or {}
    except ValueError:
        return {}


def model_tf(row: dict, now=None) -> str:
    """Het tijdframe van de candles voor de modelkaart: van de swing van de 4u-range (swing_at) tot nu in hoogstens MODEL_MAX_BARS candles."""
    d = _model_detail(row)
    start = _ts(d.get("swing_at") or d.get("range_at") or row.get("discovered_at"))
    if start is None:
        return "1h"
    end = _ts(now) if now is not None else pd.Timestamp.now(tz="UTC").timestamp()
    for tf, seconds in MODEL_TFS:
        if (end - start) / seconds + MODEL_LEAD <= MODEL_MAX_BARS:
            return tf
    return MODEL_TFS[-1][0]


def _model_range(row: dict, e: dict) -> tuple[float, float, float]:
    """(laag, hoog, evenwicht) van de range zoals het model hem bij de entry gebruikte. De rand aan de kant van het doel groeit tot de entry mee
    (model.Context4h: H is de top tot nu); oudere rijen zonder range in de entry leiden hem af uit het evenwicht van de entry, de andere rand
    ligt vast."""
    L, H, eq = row["range_low"], row["range_high"], row["eq"]
    if e.get("range_low") is not None and e.get("range_high") is not None:
        L, H = e["range_low"], e["range_high"]
        return L, H, (L + H) / 2
    if e.get("eq") is not None:
        eq = e["eq"]
        if row["direction"] == "long":
            H = 2 * eq - L
        else:
            L = 2 * eq - H
    return L, H, eq


def _model_zones(row: dict, e: dict, steps: dict) -> list[dict]:
    """Alleen wat het model gebruikt: de gap op 15m, en het order block als de limiet op hun overlap ligt."""
    if row.get("limit_price") is None:
        return []
    if e.get("fvg_low") is not None:
        out = [{"low": e["fvg_low"], "high": e["fvg_high"], "from": _ts(e.get("fvg_at")), "label": "15m FVG"}]
    else:
        shift = _ts((steps.get("shift") or {}).get("at")) or _ts(row.get("entry_at"))
        out = [{"low": row["zone_low"], "high": row["zone_high"], "from": shift - 3 * 900 if shift else None, "label": "15m FVG"}]
    if (row.get("ob_overlap") or e.get("ob_overlap")) and e.get("ob_low") is not None:
        out.append({"low": e["ob_low"], "high": e["ob_high"], "from": _ts(e.get("ob_at")), "label": "15m OB"})
    return out


def _target_tag(row: dict) -> Optional[str]:
    """'dag-POC' of 'week-POC' als een naakte POC het doel is (model_card.target_word komt uit dezelfde rij)."""
    if row.get("target_kind") != "poc":
        return None
    word = (row.get("target_text") or "POC").split()[0]
    return word[:1].lower() + word[1:]


def model_svg(row: dict, candles: list[list], price: Optional[float] = None, big: bool = False) -> str:
    """Een rij uit model_scenarios. `candles` op model_tf(row): [[unix_s, open, high, low, close], ...] oud naar nieuw, alle die de cache heeft;
    het venster (vanaf de swing van de range tot nu) kiest deze functie. `price` wordt niet getekend: de laatste candle is de koers, en een
    lijn meer is ruis. big: de grote weergave, dezelfde tekening hoger."""
    if not candles:
        return ""
    W, H = (MODEL_BIG_W, MODEL_BIG_H) if big else (MODEL_W, MODEL_H)
    d = _model_detail(row)
    steps = {s["stap"]: s for s in d.get("steps") or []}
    e = d.get("entry") or {}
    long = row["direction"] == "long"
    plan = row.get("limit_price") is not None and row.get("stop_loss") is not None

    times_all = [float(c[0]) for c in candles]
    diffs = sorted(b - a for a, b in zip(times_all, times_all[1:]))
    bar = diffs[len(diffs) // 2] if diffs else 3600.0
    start = _ts(d.get("swing_at") or d.get("range_at") or row.get("discovered_at"))
    n_all = len(candles)
    i0 = next((k for k, c in enumerate(candles) if start is not None and c[0] >= start - MODEL_LEAD * bar), max(0, n_all - 24))
    i0 = max(0, n_all - MODEL_MAX_BARS, min(i0, n_all - 12))
    shown = candles[i0:]
    n = len(shown)
    t0 = float(shown[0][0])

    L, Hi, eq = _model_range(row, e)
    zones = _model_zones(row, e, steps)
    sweep, shift = steps.get("sweep"), steps.get("shift")
    lo_word = "low" if long else "high"

    # Rechts: de niveaus over de breedte (range en evenwicht) en de order (limiet, stop, doel met prijs).
    levels = [(Hi, "mc-level", "4u range high"), (L, "mc-level", "4u range low"), (eq, "mc-level is-eq", "evenwicht")]
    if plan:
        levels += [(row["limit_price"], "sc-limit", f"Limiet {price_text.nl(row['limit_price'])}"),
                   (row["stop_loss"], "sc-stop", f"Stop {price_text.nl(row['stop_loss'])}")]
        if row.get("take_profit") is not None:
            levels.append((row["take_profit"], "sc-target", f"Doel {price_text.nl(row['take_profit'])}"))
    col_w = max(len(t) for _, _, t in levels) * MODEL_CHAR_W + 10
    plot_r = W - col_w
    left = float(MODEL_PAD_L)
    step = (plot_r - MODEL_FUTURE_PX - left) / n
    plot_t, plot_b = float(MODEL_PAD_T), float(H - MODEL_PAD_B)

    pool_level = sweep["pool"] if sweep and sweep.get("pool") is not None else row.get("pool_level")
    values = [c[3] for c in shown] + [c[2] for c in shown] + [v for v, _, _ in levels]
    values += [v for v in (pool_level, (sweep or {}).get("extreme"), (shift or {}).get("top")) if v is not None]
    values += [z[k] for z in zones for k in ("low", "high")]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    lo, hi = lo - span * 0.05, hi + span * 0.05

    def y(v: float) -> float:
        return plot_t + (hi - v) / (hi - lo) * (plot_b - plot_t)

    def x(i: float) -> float:
        return left + (i + 0.5) * step

    def bar_at(ts: Optional[float]) -> Optional[int]:
        """De getoonde candle waarin dit moment valt; None als het vóór het venster ligt of onbekend is."""
        if ts is None:
            return None
        k = int((ts - t0) // bar)
        return min(k, n - 1) if k >= 0 else None

    def x_at(ts: Optional[float]) -> float:
        k = bar_at(ts)
        return left if k is None else x(k)

    taken: list[tuple[float, float, float, float]] = []

    def box(tx: float, ty: float, text: str, anchor: str) -> tuple[float, float, float, float]:
        w = len(text) * MODEL_CHAR_W
        x0 = tx if anchor == "start" else tx - w if anchor == "end" else tx - w / 2
        return (x0, ty - 10, x0 + w, ty + 2)

    def free(r: tuple, right: float) -> bool:
        return (r[0] >= left and r[2] <= right and r[1] >= plot_t - 6 and r[3] <= H
                and not any(r[0] < t[2] and t[0] < r[2] and r[1] < t[3] and t[1] < r[3] for t in taken))

    def place(options: list[tuple[float, float, str]], text: str, cls: str, right: Optional[float] = None) -> str:
        """De eerste plek zonder andere tekst; de laatste optie als alles bezet is (dan schuift hij omlaag tot hij vrij is)."""
        right = plot_r - 2 if right is None else right
        for tx, ty, anchor in options:
            r = box(tx, ty, text, anchor)
            if free(r, right):
                break
        else:
            tx, ty, anchor = options[0]
            r = box(tx, ty, text, anchor)
            while not free(r, right) and r[3] + 13 <= H:
                ty += 13
                r = box(tx, ty, text, anchor)
        taken.append(r)
        return f'<text class="{cls}" x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{escape(text)}</text>'

    # Tekst komt na alle lijnen en vlakken: een stoplijn die later getekend werd, streepte een label door.
    words: list[str] = []
    tf_text = MODEL_TF_TEXT.get(int(bar), f"{int(bar // 60)}m")
    meta = f"{row['coin']} · {tf_text} · {row['direction']}"
    what = ", ".join(z["label"] for z in zones) or "scenario"
    cls = "sc mc is-big" if big else "sc mc is-card"
    out = [f'<svg class="{cls}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(row["coin"])} {escape(row["direction"])}, {tf_text}-candles: '
           f'4u-range, {escape(what)}">']
    mx = W - 4
    taken.append(box(mx, 13, meta, "end"))
    words.append(f'<text class="mc-meta" x="{mx:.1f}" y="13" text-anchor="end">{escape(meta)}</text>')

    # Vlakken eerst, dan candles erover. De naam staat in het vlak in de lege strook rechts; past hij er niet in, dan er net buiten.
    zone_labels = []
    for z in sorted(zones, key=lambda z: -z["high"]):
        top, bottom = y(z["high"]), y(z["low"])
        zx = max(left, x_at(z["from"]) - step / 2) if z["from"] is not None else left
        out.append(f'<rect class="mc-zone" x="{zx:.1f}" y="{top:.1f}" width="{max(1.0, plot_r - zx):.1f}" height="{max(1.0, bottom - top):.1f}"/>')
        lx = plot_r - 3
        inside = [((top + bottom) / 2 + 4, "mc-zone-label")] if bottom - top >= 13 else []
        # Te smal voor de naam: erboven (long) of eronder (short), weg van de stop die aan de andere kant ligt.
        above = [(top - 3, "mc-zone-label is-out"), (top - 16, "mc-zone-label is-out")]
        below = [(bottom + 11, "mc-zone-label is-out"), (bottom + 24, "mc-zone-label is-out")]
        outside = above + below if long else below + above
        zone_labels.append((lx, inside + outside, z["label"]))
    for lx, opts, text in zone_labels:
        for ty, c in opts:
            r = box(lx, ty, text, "end")
            if free(r, plot_r):
                break
        else:
            ty, c = opts[0]
        taken.append(box(lx, ty, text, "end"))
        words.append(f'<text class="{c}" x="{lx:.1f}" y="{ty:.1f}" text-anchor="end">{escape(text)}</text>')

    # Range en evenwicht over de hele breedte.
    for v, c, _ in levels[:3]:
        out.append(f'<line class="{c}" x1="{left:.1f}" x2="{plot_r:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')

    body_w = max(1.0, step * 0.62)
    for i, (_, o, h, low, c) in enumerate(shown):
        up = c >= o
        top, bottom = y(max(o, c)), y(min(o, c))
        out.append(f'<line class="mc-w" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(h):.1f}" y2="{y(low):.1f}"/>'
                   f'<rect class="mc-c {"is-up" if up else "is-dn"}" x="{x(i) - body_w / 2:.1f}" y="{top:.1f}" width="{body_w:.1f}" '
                   f'height="{max(1.0, bottom - top):.1f}"/>')

    # Korte lijnen vanaf hun punt: de pool (de swing op 1u, of gelijke lows), de sweep-lont en de structuurbreuk op 15m.
    tags = []
    if pool_level is not None:
        pool_at = _ts((sweep or {}).get("pool_at"))
        p0 = d.get("pool0") or {}
        if pool_at is None and p0.get("key") and abs((p0.get("level") or 0) - pool_level) <= 1e-9 * max(1.0, abs(pool_level)):
            pool_at = _ts(p0["key"])
        count = (sweep or {}).get("pool_n") if sweep else p0.get("n")
        name = ("EQL" if long else "EQH") if (count or 1) >= 2 else f"1u swing {lo_word}"
        end_i = bar_at(_ts(sweep["prik_at"])) if sweep else n - 1
        end_x = x(end_i) if end_i is not None else x(n - 1)
        start_x = x_at(pool_at) if pool_at is not None else max(left, end_x - 8 * step)
        py = y(pool_level)
        out.append(f'<line class="mc-pool" x1="{start_x:.1f}" x2="{max(end_x, start_x + 6):.1f}" y1="{py:.1f}" y2="{py:.1f}"/>')
        dy = 13 if long else -5
        tags.append(([(start_x, py + dy, "start"), (start_x, py - (18 - dy) if long else py + 13, "start"),
                      (end_x, py + dy, "end"), (end_x, py + (-5 if long else 13), "end")], name))
    if sweep and sweep.get("extreme") is not None:
        k = bar_at(_ts(sweep.get("prik_at")))
        if k is not None:
            sx, sy = x(k), y(sweep["extreme"])
            out.append(f'<circle class="mc-sweep" cx="{sx:.1f}" cy="{sy:.1f}" r="3.5"/>')
            dy = 14 if long else -7
            tags.append(([(sx, sy + dy, "middle"), (sx + 6, sy + dy, "start"), (sx - 6, sy + dy, "end"), (sx + 7, sy + 4, "start")], "sweep"))
    if shift and shift.get("top") is not None:
        a = _ts(shift.get("top_at"))
        b = _ts(shift.get("at"))
        bx = x_at(b - 900) if b is not None else x(n - 1)
        ax = x_at(a) if a is not None else max(left, bx - 6 * step)
        ty = y(shift["top"])
        out.append(f'<line class="mc-bos" x1="{ax:.1f}" x2="{max(bx, ax + 6):.1f}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        name = f"15m {SHIFT_WORDS.get(shift.get('label'), 'MSB')}"
        dy = -4 if long else 13
        tags.append(([(ax, ty + dy, "start"), (bx, ty + dy, "end"), (ax, ty + (13 if long else -4), "start")], name))
    tag = _target_tag(row) if plan else None
    if tag:
        ty = y(row["take_profit"])
        tags.append(([(plot_r - 3, ty - 4 if long else ty + 13, "end"), (plot_r - 3, ty + 13 if long else ty - 4, "end")], tag))
    for options, text in tags:
        words.append(place(options, text, "mc-tag"))

    # De order: van de entry (moment B) tot de rand, en alle labels rechts uit elkaar zoals de ladder.
    ex = x_at(_ts(row.get("entry_at"))) if plan else plot_r
    ys = spread([y(v) for v, _, _ in levels], MODEL_GAP, top=plot_t, bottom=H - 6)
    lines_out = []
    for (v, c, text), ly in zip(levels, ys):
        if c.startswith("sc-"):
            line = f'<line class="sc-line {c}" x1="{ex:.1f}" x2="{plot_r:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
            label = f'<text class="sc-label {c} mc-price" x="{plot_r + 5:.1f}" y="{ly + 4:.1f}">{escape(text)}</text>'
        else:
            line = f'<line class="mc-tick" x1="{plot_r:.1f}" x2="{plot_r + 3:.1f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
            label = f'<text class="mc-label" x="{plot_r + 5:.1f}" y="{ly + 4:.1f}">{escape(text)}</text>'
        lines_out.append(line + label)
    out += lines_out + words
    out.append("</svg>")
    return "".join(out)
