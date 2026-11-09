"""Vertraging per kansmelding: van het slot van de candle waarop de kans ontstond (of vulde) tot de verzonden push. Zuivere functies; de momenten
staan per verzonden push in de tabel alert_timing (push_notify.send_kans_push) en scripts/vertraging.py telt ze per soort.

Het candlemoment is de sluiting van de candle die de kans liet zien. Lag die nog in de toekomst (een vulling in de candle die nog vormt), dan telt
het laatste 5m-slot vóór de detectie: dat is ook het slot waarop de snelcyclus start (deploy/crypto-market-scan-smc.timer)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import track_record

SLOT = timedelta(minutes=5)


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _parse(value: str) -> datetime:
    return _aware(datetime.fromisoformat(value))


def slot_floor(moment: datetime) -> datetime:
    moment = _aware(moment)
    return moment - timedelta(minutes=moment.minute % 5, seconds=moment.second, microseconds=moment.microsecond)


def candle_moment(candle_close: Optional[datetime], detected: datetime) -> datetime:
    last_slot = slot_floor(detected)
    if candle_close is None:
        return last_slot
    return min(_aware(candle_close), last_slot)


def timing(trade_type: str, event: str, candle_close, detected) -> dict:
    """Wat een motor aan send_kans_push meegeeft. candle_close en detected mogen ook pandas-Timestamps zijn."""
    to_dt = lambda t: None if t is None else _aware(t.to_pydatetime() if hasattr(t, "to_pydatetime") else t)
    detected = to_dt(detected)
    return {"trade_type": trade_type, "event": event, "candle_at": candle_moment(to_dt(candle_close), detected).isoformat(),
            "detected_at": detected.isoformat()}


def stats(rows: list[dict]) -> dict[str, dict]:
    """Per soort: aantal aangekomen pushes, mediaan en 90e percentiel van candle tot verzonden (seconden), de mediaan van candle tot detectie (het
    deel van de motor; de rest is oordeel, budget en verzenden), en het aantal mislukte pushes apart (die tellen niet mee in de vertraging)."""
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r.get("trade_type") or "onbekend", {"total": [], "detect": [], "failed": 0})
        if not r.get("ok"):
            g["failed"] += 1
            continue
        sent = _parse(r["sent_at"])
        g["total"].append((sent - _parse(r["candle_at"])).total_seconds())
        g["detect"].append((_parse(r["detected_at"]) - _parse(r["candle_at"])).total_seconds())
    q = lambda v, p: track_record._quantile(sorted(v), p) if v else None
    return {t: {"n": len(g["total"]), "failed": g["failed"], "median_s": q(g["total"], 0.5), "p90_s": q(g["total"], 0.9),
                "detect_median_s": q(g["detect"], 0.5)} for t, g in groups.items()}
