"""De pagina van één kans (/kans/<id>): grafiek, feiten, gemeten kenmerken en een tijdlijn van wat er gebeurde. Pure functies die uit het
signaal en (voor Structuur) zijn setup een weergave bouwen. De route haalt candles en koers op en geeft ze hier door."""
import json
from datetime import datetime, timezone
from typing import Optional

from app import setup_chart
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
    return [{"at": _parse(e["at"]), "text": e["text"]} for e in events]


def facts(signal: dict) -> dict:
    entry, stop, take = signal["price"], signal["stop_loss"], signal["take_profit"]
    risk = abs(entry - stop) if entry and stop else 0.0
    return {"entry": entry, "stop": stop, "take": take, "risk_pct": risk / entry * 100 if entry and risk else None,
            "rr": abs(take - entry) / risk if risk and take else None, "label": TYPE_LABELS.get(signal["trade_type"], signal["trade_type"]).replace(" (ongetest)", "")}


def chart(signal: dict, setup: Optional[dict], candles: Optional[list[list]], price: Optional[float]) -> str:
    """Structuur tekent zijn eigen momentopname (met de gebroken lijn), alle andere soorten de candles van nu met instap, stop en doel."""
    if setup:
        plan = json.loads(setup["plan"])
        fired = plan.get("fired")
        if fired:
            plan = {**plan, "level": fired["entry"], "stop": fired["stop"], "targets": fired["targets"]}
        return setup_chart.setup_svg(plan.get("candles", []), setup, plan, price)
    if not candles or not signal["stop_loss"] or not signal["take_profit"]:
        return ""
    return setup_chart.trade_svg(candles, signal["direction"], signal["coin"], signal["price"], signal["stop_loss"], signal["take_profit"], price)
