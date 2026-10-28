"""De eigen kaartgrafiek per soort op Kansen, voor Zone-radar, Zone-sweep en POC-radar: de tekenstijl van de galerij (setup_chart.zone_svg) op het
tijdframe van de zone. Pure functies: de route haalt de candles uit de minuutcache en geeft de rij uit zone_radar_setups of zone_sweep_setups
mee. Structuur tekent zijn eigen momentopname (setup_chart.setup_svg) en komt hier niet langs.

Zone-radar: de zone als vlak vanaf de ontstaanscandle (zone_key) met een markering op die candle, de doelzone als vlak, limiet, stop en doel.
Zone-sweep: daarbij de prik (sweep_at, het uiterste) en de herstelcandle (de laatste gesloten candle vóór placed_at)."""
from typing import Optional

import pandas as pd

from app import poc, price_text, setup_chart, trade_plan as tp, zone_radar

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
