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


def trailing_outcome(signal: dict, r_value: Optional[float]) -> Optional[dict]:
    """Uitkomst van een trade met een meelopende stop: die heeft geen doel, dus winst of verlies in R in plaats van "doel geraakt"."""
    outcome = signal.get("auto_outcome")
    if outcome not in ("take_profit", "stop_loss"):
        return None
    win = outcome == "take_profit"
    return {"win": win, "text": f"Afgesloten met {'winst' if win else 'verlies'}" + (f", {r_value:+.2f}R" if r_value is not None else "")}


def reference_outcome(signal: dict, r_value: Optional[float]) -> Optional[dict]:
    """Een range sweep heeft geen doel; de R op Bewijs komt van een referentie-uitgang. Dat moet op de kans staan, anders lijkt +1,4R jouw resultaat."""
    if signal.get("auto_outcome") not in ("take_profit", "stop_loss") or r_value is None:
        return None
    r_text = f"{r_value:+.2f}".replace(".", ",")
    return {"win": r_value > 0, "r": r_value, "text": f"Referentie-uitgang (meelopende stop 3 ATR op 1u): {r_text}R. Jouw trade beslis je zelf."}


def range_sweep_events(setup: dict, trade: Optional[dict]) -> list[dict]:
    """Wat er met een range sweep gebeurde, uit de meting van de motor: melding, elke vulling, elk R-niveau dat vóór de stop viel, de stop, de
    referentie-uitgang en het einde van de meting. Alleen wat vaststaat; een niveau dat niet viel staat er niet."""
    events = [{"at": setup["placed_at"], "text": "Plan gemeld, limietorder klaarzetten"}]
    if not trade:
        return events
    raw = trade.get("legs_filled")
    legs = (json.loads(raw) if isinstance(raw, str) else raw) or []
    total = sum(leg[0] for leg in legs) or 1.0
    events += [{"at": leg[2], "text": f"Limiet {i} gevuld ({round(leg[0] / total * 100)}%)" if len(legs) > 1 else "Limiet gevuld"} for i, leg in enumerate(legs, 1)]
    events += [{"at": trade[f"reached_{k}r_at"], "text": f"+{k}R bereikt vóór de stop"} for k in range(1, 7) if trade.get(f"reached_{k}r_at")]
    if trade.get("stop_hit_at"):
        events.append({"at": trade["stop_hit_at"], "text": "Stop geraakt"})
    if trade.get("ref_closed_at") and trade.get("ref_closed_at") != trade.get("stop_hit_at"):
        events.append({"at": trade["ref_closed_at"], "text": "Referentie-uitgang bereikt"})
    if trade.get("closed_at"):
        events.append({"at": trade["closed_at"], "text": "Meting klaar"})
    events.sort(key=lambda e: _parse(e["at"]))       # stabiel: bij gelijke tijd blijft de volgorde hierboven
    return events


def timeline(signal: dict, setup: Optional[dict], outcome_text: Optional[str] = None) -> list[dict]:
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
        events.append({"at": signal.get("auto_outcome_at") or signal["created_at"], "text": outcome_text or OUTCOME_TEXT.get(outcome, outcome)})
    events.sort(key=lambda e: _parse(e["at"]))
    return format_events(events)


def format_events(events: list[dict]) -> list[dict]:
    """Nederlandse tijd, zoals de rest van de site, en de tijdlijnregels in CEO-taal."""
    return [{"at": today.local(_parse(e["at"])), "text": ceo.timeline_text(e["text"])} for e in events]


def facts(signal: dict) -> dict:
    entry, stop, take = signal["price"], signal["stop_loss"], signal["take_profit"]
    risk = abs(entry - stop) if entry and stop else 0.0
    label = TYPE_LABELS.get(signal["trade_type"], signal["trade_type"])
    return {"entry": entry, "stop": stop, "take": take, "risk_pct": risk / entry * 100 if entry and risk else None,
            "rr": abs(take - entry) / risk if risk and take else None, "label": label.replace(" (ongetest)", ""), "untested": label.endswith(" (ongetest)")}


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
