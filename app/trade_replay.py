"""Replay van een afgeronde trade (fase 2, ontwerp D): pure functies zonder database of netwerk. De route haalt de candles op via de
exchange-laag en geeft signaal, plan en checklist mee.

Het venster loopt van een uur voor de vulling tot de candle van de uitkomst, op 5 minuten; past dat niet in MAX_CANDLES, dan 15 minuten of
een uur (de kop zegt welke). Elk moment (plan actief, in zone, order gezet, gevuld, doel of stop) komt uit een echt tijdstip. R staat er pas
na de vulling, gemeten uit de sluiting van die candle; vanaf de candle van de uitkomst geldt het gemeten resultaat (track_record.signal_r)."""
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from app import logbook, track_record

LEAD = timedelta(hours=1)
MAX_CANDLES = 600
TIMEFRAMES = (("5m", 5), ("15m", 15), ("1h", 60))
TF_LABEL = {"5m": "5 min", "15m": "15 min", "1h": "1 uur"}
OUTCOME_LABEL = {"take_profit": "Doel geraakt", "stop_loss": "Stop geraakt"}

W, H, PAD_L, PAD_R, PAD_Y = 340.0, 260.0, 4.0, 48.0, 10.0


def _parse(value: str) -> datetime:
    return logbook._parse(value)


def window(fill_at: str, close_at: str) -> tuple[datetime, datetime, str]:
    start, end = _parse(fill_at) - LEAD, _parse(close_at)
    for tf, minutes in TIMEFRAMES:
        if (end - start) / timedelta(minutes=minutes) + 1 <= MAX_CANDLES:
            return _floor(start, minutes), end, tf
    return _floor(start, 60), end, "1h"


def _floor(dt: datetime, minutes: int) -> datetime:
    seconds = minutes * 60
    return datetime.fromtimestamp(int(dt.timestamp()) // seconds * seconds, tz=timezone.utc)


def candle_count(start: datetime, end: datetime, tf: str) -> int:
    minutes = dict(TIMEFRAMES)[tf]
    return int((end - start) / timedelta(minutes=minutes)) + 1


def moments(signal: dict, plan: Optional[dict], run: Optional[dict]) -> list[dict]:
    """De momenten met een echt tijdstip, op volgorde. In zone valt weg als het samenvalt met de vulling (bij de zone-radar is dat zo)."""
    out = []
    fill = signal["created_at"]
    if plan and plan.get("created_at"):
        out.append({"key": "plan", "label": "Plan actief", "at": plan["created_at"]})
    if plan and plan.get("zone_at") and _parse(plan["zone_at"]) != _parse(fill):
        out.append({"key": "zone", "label": "In zone", "at": plan["zone_at"]})
    if run and run.get("done_at"):
        out.append({"key": "order", "label": "Order gezet", "at": run["done_at"], "seconds": logbook.checklist_seconds(run.get("opened_at"), run["done_at"])})
    out.append({"key": "filled", "label": "Gevuld", "at": fill})
    if signal.get("auto_outcome") in OUTCOME_LABEL and signal.get("auto_outcome_at"):
        out.append({"key": "target" if signal["auto_outcome"] == "take_profit" else "stop", "label": OUTCOME_LABEL[signal["auto_outcome"]],
                    "at": signal["auto_outcome_at"]})
    return sorted(out, key=lambda m: _parse(m["at"]))


def _sentence(m: dict, signal: dict, final_r: Optional[float]) -> str:
    key = m["key"]
    if key == "plan":
        return f"Plan actief. Limiet op {logbook.price_text(signal['price'])}, prijs nog niet in de zone."
    if key == "zone":
        return "In zone. De koers kwam bij de limiet."
    if key == "order":
        return "Order gezet." + (f" Checklist in {logbook.duration_text(m['seconds'])}." if m.get("seconds") is not None else "")
    if key == "filled":
        return f"Gevuld op {logbook.price_text(signal['price'])}. Stop {logbook.price_text(signal['stop_loss'])}."
    what = "Doel geraakt" if key == "target" else "Stop geraakt"
    return f"{what}. Trade gesloten" + (f" op {logbook.r_text(final_r)}." if final_r is not None else ".")


def build(rows: list, signal: dict, ms: list[dict], tf: str, tz) -> Optional[dict]:
    """rows: [[unix_s, open, high, low, close], ...] oudste eerst. Per candle een frame met R en de zin van het laatste moment ervoor."""
    if not rows:
        return None
    step = dict(TIMEFRAMES)[tf] * 60
    first = rows[0][0]

    def index_of(at: str) -> int:
        return max(0, min(len(rows) - 1, int((_parse(at).timestamp() - first) // step)))

    placed = [{**m, "index": index_of(m["at"]), "time": f"{_parse(m['at']).astimezone(tz):%H:%M}"} for m in ms]
    final_r = track_record.signal_r(signal)
    fill_i = next((m["index"] for m in placed if m["key"] == "filled"), None)
    end_i = next((m["index"] for m in placed if m["key"] in ("target", "stop")), None)
    entry, stop = signal["price"], signal["stop_loss"]
    risk = abs(entry - stop)
    sign = 1 if signal["direction"] == "long" else -1

    frames = []
    for i, (t, _o, _h, _l, close) in enumerate(rows):
        if fill_i is None or i < fill_i or not risk:
            r_label, r_text = "Niet gevuld", "—"
        elif end_i is not None and i >= end_i and final_r is not None:
            r_label, r_text = "Resultaat", logbook.r_text(final_r)
        else:
            r_label, r_text = "Open", logbook.r_text(sign * (close - entry) / risk)
        past = [k for k, m in enumerate(placed) if m["index"] <= i]
        if past:
            k = past[-1]
            step_text, event = f"Moment {k + 1} van {len(placed)}", _sentence(placed[k], signal, final_r)
        else:
            step_text, event = "Voor het eerste moment", "Voor de vulling. Prijs nog niet op de limiet."
        frames.append({"time": f"{datetime.fromtimestamp(t, tz=timezone.utc).astimezone(tz):%H:%M}", "r_label": r_label, "r_text": r_text,
                       "step": step_text, "event": event, "x": round(_x(i, len(rows)), 2)})

    levels = [{"label": "Stop", "value": stop, "tone": "loss"}, {"label": "Instap", "value": entry, "tone": "entry"}]
    if signal.get("take_profit") is not None:
        levels.append({"label": "Doel", "value": signal["take_profit"], "tone": "win"})
    for lv in levels:
        lv["text"] = logbook.price_text(lv["value"])
    return {"frames": frames, "moments": placed, "levels": levels, "tf": tf, "tf_label": TF_LABEL[tf], "start_index": end_i if end_i is not None else len(rows) - 1,
            "svg": svg(rows, levels)}


def _x(i: int, n: int) -> float:
    return PAD_L + (i + 0.5) * (W - PAD_L - PAD_R) / n


def svg(rows: list, levels: list[dict]) -> str:
    """Candles grijs (op en neer twee tinten), alleen stop en doel in kleur, de instap gestippeld in accent. Een cursorlijn die replay.js
    verschuift; zonder JavaScript staat de hele trade er gewoon."""
    lows = [r[3] for r in rows] + [lv["value"] for lv in levels]
    highs = [r[2] for r in rows] + [lv["value"] for lv in levels]
    lo, hi = min(lows), max(highs)
    span = (hi - lo) or abs(hi) * 0.01 or 1.0
    lo, hi = lo - span * 0.04, hi + span * 0.04

    def y(p: float) -> float:
        return round(PAD_Y + (hi - p) / (hi - lo) * (H - 2 * PAD_Y), 2)

    n = len(rows)
    cw = (W - PAD_L - PAD_R) / n
    body = max(1.0, min(6.0, cw * 0.62))
    parts = [f'<svg class="rp-svg" viewBox="0 0 {W:g} {H:g}" role="img" aria-label="Candles van de trade met stop, instap en doel">']
    for lv in levels:
        cls = {"loss": "is-loss", "win": "is-win"}.get(lv["tone"], "is-entry")
        yy = y(lv["value"])
        dash = ' stroke-dasharray="4 3"' if lv["tone"] != "loss" else ""
        parts.append(f'<line class="rp-lvl {cls}" x1="0" x2="{W - PAD_R + 2:g}" y1="{yy}" y2="{yy}"{dash}/>'
                     f'<text class="rp-tag {cls}" x="{W - 2:g}" y="{yy + 4}" text-anchor="end">{escape(lv["label"])}</text>')
    for i, (_t, o, h, l, c) in enumerate(rows):
        x = round(_x(i, n), 2)
        top, bot = y(max(o, c)), y(min(o, c))
        kind = "rp-up" if c >= o else "rp-down"
        parts.append(f'<g class="rp-candle {kind}" data-i="{i}"><line x1="{x}" x2="{x}" y1="{y(h)}" y2="{y(l)}"/>'
                     f'<rect x="{round(x - body / 2, 2)}" y="{top}" width="{round(body, 2)}" height="{max(1.0, round(bot - top, 2))}" rx="0.6"/></g>')
    last = round(_x(n - 1, n), 2)
    parts.append(f'<line class="rp-cursor" x1="{last}" x2="{last}" y1="0" y2="{H:g}"/></svg>')
    return "".join(parts)
