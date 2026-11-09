"""Lekken per focus-soort: waar kansen weglekken tussen ontdekken en een afgeronde trade, over een venster van dagen. Zuiver: de invoer komt uit
repo.leak_inputs (en de stop-dan-doel-meting van scripts/nacht_export.py). Alleen meting voor de wekelijkse verbetersessie, geen motor leest het.

Per soort: kaarten, gevuld, wachtend, vervallen per reden (app/end_reason.py), afgeronde trades en hun gemiddelde netto R (track_record.net_signal_r,
zelfde kosten als Bewijs), stops die binnen 24 uur toch het doel haalden (excursion.AFTER_STOP), mediaan MAE van winnaars en verliezers, hoeveel
kansen de dagcap tegenhield, de vertraging van de meldingen (latency.stats) en de auto-missers per weigerreden van deze motor."""
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from app import config, end_reason, excursion, latency, track_record
from app.auto_misser import _ts

KINDS = ("structuur", "zone_radar", "zone_sweep", "poc_radar")
# Welke trade_types bij een soort horen: Structuur meldt als structuur of structuur_c (het oordeel van Claude), het is één motor.
TYPES = {"structuur": ("structuur", "structuur_c"), "zone_radar": ("zone_radar",), "zone_sweep": ("zone_sweep",), "poc_radar": ("poc_radar",)}
FILLED = {"filled", "fired"}
WAITING = {"waiting", "oordeel"}
WINDOWS = (7, 30)


def _in(value: Optional[str], since: datetime) -> bool:
    return bool(value) and _ts(value) >= since


def _reason_group(text: str) -> str:
    """Een weigerreden zonder de getallen tussen haakjes, zodat dezelfde regel bij elkaar telt."""
    return text.split(" (", 1)[0].strip()


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def per_kind(inputs: dict, now: datetime, days: int, cost_pct: Optional[float] = None) -> dict:
    cost_pct = config.TRACK_RECORD_COST_PCT if cost_pct is None else cost_pct
    since = _ts(now) - timedelta(days=days)
    later = inputs.get("stop_then_target") or {}
    timings = [t for t in inputs.get("timings", []) if _in(t.get("sent_at"), since)]
    out = {}
    for kind in KINDS:
        cards = [c for c in inputs.get("cards", []) if c["kind"] == kind and _in(c["created_at"], since)]
        ended = Counter(c["state"] for c in cards if c["state"] not in FILLED | WAITING)
        sigs = [s for s in inputs.get("signals", []) if s["trade_type"] in TYPES[kind] and _in(s["created_at"], since)]
        done = [s for s in sigs if s.get("auto_outcome") in ("take_profit", "stop_loss")]
        nets = [r for r in (track_record.net_signal_r(s, cost_pct) for s in done) if r is not None]
        gross = [r for r in (track_record.signal_r(s) for s in done) if r is not None]
        stops = [s for s in done if s["auto_outcome"] == "stop_loss" and later.get(s["id"]) is not None]
        moves = excursion.stats([{**s, "trade_type": kind} for s in done]).get(kind, {})
        lag = latency.stats([{**t, "trade_type": kind} for t in timings if t.get("trade_type") in TYPES[kind]]).get(kind)
        missers = [m for m in inputs.get("missers", []) if not m.get("seen_by") and _in(m["begin_at"], since)]
        out[kind] = {
            "kaarten": len(cards),
            "gevuld": sum(1 for c in cards if c["state"] in FILLED),
            "wachtend": sum(1 for c in cards if c["state"] in WAITING),
            "vervallen": {state: {"n": n, "tekst": end_reason.text(kind, state)} for state, n in sorted(ended.items())},
            "afgerond": len(done),
            "netto_r": _mean(nets),
            "bruto_r": _mean(gross),
            "stop_dan_doel": {"gecontroleerd": len(stops), "toch_doel": sum(1 for s in stops if later[s["id"]])},
            "mae_mediaan_winnaars": moves.get("win_mae_med"),
            "mae_mediaan_verliezers": moves.get("loss_mae_med"),
            "dagcap": sum(1 for h in inputs.get("cap_holds", []) if h["engine"] == kind and _in(h["at"], since)),
            "vertraging": lag,
            "missers": {"n": sum(1 for m in missers if kind in (m.get("reasons") or {})),
                        "redenen": dict(Counter(_reason_group(m["reasons"][kind]) for m in missers if kind in (m.get("reasons") or {})))},
        }
    return out


def report(inputs: dict, now: datetime) -> dict:
    """Beide vensters: {'7d': per_kind, '30d': per_kind}."""
    return {f"{d}d": per_kind(inputs, now, d) for d in WINDOWS}
