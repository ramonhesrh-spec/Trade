"""De pagina van één kans (/kans/<id>): grafiek, feiten, gemeten kenmerken en een tijdlijn van wat er gebeurde. Pure functies die uit het
signaal en (voor Structuur) zijn setup een weergave bouwen. De route haalt candles en koers op en geeft ze hier door."""
import json
from datetime import datetime, timezone
from typing import Optional

from app import ceo, setup_chart, today
from app.track_record import TYPE_LABELS

OUTCOME_TEXT = {"take_profit": "Doel geraakt", "stop_loss": "Stop geraakt", "vervallen": "Vervallen zonder uitkomst"}


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def timeline(signal: dict, setup: Optional[dict]) -> list[dict]:
    """Gebeurtenissen oud naar nieuw: plan gemeld, limiet geraakt, doelen en stop (alleen Structuur kent die tijden), uitkomst."""
    events = []
    if setup:
        events.append({"at": setup["created_at"], "text": "Plan gemeld, limietorder klaarzetten"})
        fired = (json.loads(setup["plan"]).get("fired") or {})
        events += [e for e in fired.get("events", [])]
    else:
        events.append({"at": signal["created_at"], "text": "Gemeld"})
    outcome = signal.get("auto_outcome")
    if outcome and not any(e["text"].startswith(("Stop", "T")) for e in events if setup):
        events.append({"at": signal.get("auto_outcome_at") or signal["created_at"], "text": OUTCOME_TEXT.get(outcome, outcome)})
    events.sort(key=lambda e: _parse(e["at"]))
    return [{"at": today.local(_parse(e["at"])), "text": ceo.timeline_text(e["text"])} for e in events]    # Nederlandse tijd, zoals de rest van de site


def facts(signal: dict) -> dict:
    entry, stop, take = signal["price"], signal["stop_loss"], signal["take_profit"]
    risk = abs(entry - stop) if entry and stop else 0.0
    return {"entry": entry, "stop": stop, "take": take, "risk_pct": risk / entry * 100 if entry and risk else None,
            "rr": abs(take - entry) / risk if risk and take else None, "label": TYPE_LABELS.get(signal["trade_type"], signal["trade_type"]).replace(" (ongetest)", "")}


def _event_levels(fired: dict) -> list[dict]:
    """Elke tijdlijngebeurtenis van Structuur met het prijsniveau waar ze gebeurde: de limiet, het doel of de stop."""
    out = []
    for e in fired.get("events", []):
        text = e["text"]
        if text.startswith("Limiet"):
            level = fired["entry"]
        elif text.startswith("T") and text[1:2].isdigit():
            level = fired["targets"][int(text[1]) - 1]
        elif "instap" in text:
            level = fired["entry"]
        else:
            level = fired["stop"]
        out.append({"at": e["at"], "text": text, "level": level})
    return out


def chart(signal: dict, setup: Optional[dict], candles: Optional[list[list]], price: Optional[float]) -> str:
    """Structuur tekent zijn momentopname (met de gebroken lijn) verlengd met de candles sindsdien en met stippen voor wat er gebeurde.
    Alle andere soorten krijgen de candles van nu met instap, stop en doel."""
    if setup:
        plan = json.loads(setup["plan"])
        fired = plan.get("fired")
        snapshot = plan.get("candles", [])
        if snapshot and candles:
            last = _parse(snapshot[-1][0]).timestamp()
            snapshot = snapshot + [c for c in candles if _parse(c[0]).timestamp() > last]
        events = None
        if fired:
            events = _event_levels(fired)
            plan = {**plan, "level": fired["entry"], "stop": fired["stop"], "targets": fired["targets"]}
        return setup_chart.setup_svg(snapshot, setup, plan, price, events)
    if not candles or not signal["stop_loss"] or not signal["take_profit"]:
        return ""
    return setup_chart.trade_svg(candles, signal["direction"], signal["coin"], signal["price"], signal["stop_loss"], signal["take_profit"], price)
