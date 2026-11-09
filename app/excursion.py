"""Hoe ver een afgeronde trade eerst tegen je in ging (MAE) en hoe ver met je mee (MFE), in R van de stopafstand. Zuivere functies; de aanroepers
geven de candles van na de vulling. Dit is meting: geen motor, filter of melding leest het, en Bewijs toont het zonder advies.

Dezelfde regels als level_check bij de uitkomst: een candle die de stop raakt telt als stop (1R tegen, zijn meebeweging telt niet, want de volgorde
binnen de candle is onbekend), en een candle die het doel raakt telt tot het doel; zijn tegenbeweging telt wel mee, de voorzichtige kant. Na de
uitkomst telt niets meer. De vulcandle zelf geven de aanroepers niet mee (level_check.candles_after), net als bij het zoeken naar de uitkomst."""
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import track_record

# Hoe lang na een stop mae_check kijkt of het doel alsnog geraakt werd.
AFTER_STOP = timedelta(hours=24)


def measure(direction: str, entry: float, stop: float, take: Optional[float], candles) -> Optional[dict]:
    risk = abs(entry - stop)
    if not risk or candles is None or len(candles) == 0:
        return None
    short = direction == "short"
    take_r = abs(take - entry) / risk if take is not None else None
    mae = mfe = 0.0
    for high, low in zip(candles["high"], candles["low"]):
        if (high >= stop) if short else (low <= stop):
            mae = max(mae, 1.0)
            break
        mae = max(mae, ((high - entry) if short else (entry - low)) / risk)
        fav = ((entry - low) if short else (high - entry)) / risk
        if take_r is not None and fav >= take_r:
            mfe = max(mfe, take_r)
            break
        mfe = max(mfe, fav)
    return {"mae_r": mae, "mfe_r": mfe}


def target_reached(direction: str, take: float, candles) -> bool:
    """Raakte een van deze candles het doel? Voor mae_check: haalde een stop later alsnog het doel."""
    if direction == "short":
        return bool((candles["low"] <= take).any())
    return bool((candles["high"] >= take).any())


def _ts(value: str) -> pd.Timestamp:
    t = datetime.fromisoformat(value)
    return pd.Timestamp(t if t.tzinfo else t.replace(tzinfo=timezone.utc))


def measure_row(row: dict, candles) -> Optional[dict]:
    """Voor mae_check: de meting van één afgerond signaal op candles die het venster dekken, plus of een stop binnen 24 uur toch het doel haalde
    (None als er geen doel was of de 24 uur nog niet in de candles zitten). Een soort die zijn uitkomst zelf zet (r_override, zonder doel) meet
    tot het moment van die uitkomst."""
    created, closed = _ts(row["created_at"]), _ts(row["auto_outcome_at"])
    take = row.get("take_profit") if row.get("r_override") is None else None
    window = candles[(candles["timestamp"] >= created) & (candles["timestamp"] <= closed)]
    m = measure(row["direction"], row["price"], row["stop_loss"], take, window)
    if m is None:
        return None
    later = None
    if row["auto_outcome"] == "stop_loss" and take is not None:
        after = candles[(candles["timestamp"] > closed) & (candles["timestamp"] <= closed + AFTER_STOP)]
        if target_reached(row["direction"], take, after):
            later = True
        elif len(after) and after["timestamp"].iloc[-1] >= closed + AFTER_STOP - timedelta(minutes=15):
            later = False
    return {**m, "stop_then_target": later}


def timeframe_of(candles) -> Optional[str]:
    """'5m' of '15m' uit de afstand tussen twee candles; level_check kiest zelf welke het ophaalt."""
    if candles is None or len(candles) < 2:
        return None
    minutes = int((candles["timestamp"].iloc[1] - candles["timestamp"].iloc[0]).total_seconds() // 60)
    return f"{minutes // 60}h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes}m"


def _q(values: list[float], q: float) -> Optional[float]:
    return track_record._quantile(sorted(values), q) if values else None


def stats(rows: list[dict]) -> dict[str, dict]:
    """Per soort: afgeronde trades (doel of stop) met een meting, apart voor winnaars en verliezers. `unmeasured` telt afgeronde trades zonder
    meting, zodat niemand denkt dat de mediaan alles omvat."""
    out: dict[str, dict] = {}
    for r in rows:
        gross = track_record.signal_r(r)
        if gross is None:
            continue
        g = out.setdefault(r["trade_type"], {"win_mae": [], "loss_mae": [], "win_mfe": [], "loss_mfe": [], "unmeasured": 0, "later": []})
        if r.get("stop_then_target") is not None:
            g["later"].append(bool(r["stop_then_target"]))
        if r.get("mae_r") is None:
            g["unmeasured"] += 1
            continue
        side = "win" if gross > 0 else "loss"
        g[f"{side}_mae"].append(r["mae_r"])
        g[f"{side}_mfe"].append(r["mfe_r"])
    return {t: {"n": len(g["win_mae"]) + len(g["loss_mae"]), "win_n": len(g["win_mae"]), "loss_n": len(g["loss_mae"]), "unmeasured": g["unmeasured"],
                "stops_checked": len(g["later"]), "stops_then_target": sum(g["later"]),
                "win_mae_med": _q(g["win_mae"], 0.5), "win_mae_p75": _q(g["win_mae"], 0.75),
                "loss_mae_med": _q(g["loss_mae"], 0.5), "loss_mae_p75": _q(g["loss_mae"], 0.75),
                "win_mfe_med": _q(g["win_mfe"], 0.5), "loss_mfe_med": _q(g["loss_mfe"], 0.5)} for t, g in out.items()}


def r1(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " R"


def line(s: Optional[dict]) -> str:
    """Eén regel voor Bewijs: gemeten, zonder advies over waar een stop hoort."""
    if not s or not s["win_n"]:
        return "Nog geen gemeten winnaar."
    return f"Winnaars gingen eerst mediaan {r1(s['win_mae_med'])} tegen je in ({s['win_n']} gemeten)."
