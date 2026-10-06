"""Eerlijk, automatisch gemeten trackrecord per soort melding, in R na kosten: de rekenlaag voor /bewijs.
R is de winst als veelvoud van het risico: een take telt als afstand tot take gedeeld door afstand tot stop,
een stop als -1. Alleen signalen met een vaststaande uitkomst (take of stop) tellen mee in winrate en R; vervallen
en open signalen staan er apart bij, zodat niemand ze kan missen. Kosten komen per signaal in R af: de kosten per
rondreis gedeeld door de stopafstand in procenten (een strakke stop maakt de kosten zwaarder)."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

RECENT_DAYS = 90
MIN_FOR_STATUS = 30
MIN_FOR_PROVEN = 100
WEEKS_SHOWN = 12

TYPE_LABELS = {
    "smc": "SMC liquidity sweep",
    "patroon": "Chart-patroon",
    "day_trading": "Day trading (4u)",
    "swing": "Swing",
    "samenval": "Samenval SMC en community (ongetest)",
    "script": "Markt-script (ongetest)",
    "structuur": "Structuur-breuk (ongetest)",
    "structuur_c": "Structuur oordeel C",
    "smc_waarschuwing": "SMC met waarschuwing",
    "trend": "Trend-pullback (ongetest)",
}
SOURCE_LABELS = {"scan": "Door HesPulse gevonden", "community": "Via de community"}
STATUS_LABELS = {
    "te_weinig": "Nog te weinig data",
    "positief": "Positief, nog niet bewezen",
    "voordeel": "Voordeel gemeten",
    "verlies": "Verlies gemeten",
}


def signal_r(row: dict) -> Optional[float]:
    risk = abs((row["price"] or 0) - (row["stop_loss"] or 0))
    if row["auto_outcome"] == "take_profit" and risk > 0 and row["take_profit"] is not None:
        return abs(row["take_profit"] - row["price"]) / risk
    if row["auto_outcome"] == "stop_loss" and risk > 0:
        return -1.0
    return None


def _cost_r(row: dict, round_trip_cost_pct: float) -> float:
    stop_pct = abs(row["price"] - row["stop_loss"]) / row["price"] * 100
    return round_trip_cost_pct / stop_pct if stop_pct else 0.0


def _status(n_resolved: int, avg_net: Optional[float]) -> str:
    if n_resolved < MIN_FOR_STATUS or avg_net is None:
        return "te_weinig"
    if avg_net <= 0:
        return "verlies"
    return "voordeel" if n_resolved >= MIN_FOR_PROVEN else "positief"


def _week_key(moment: datetime) -> tuple[int, int]:
    iso = moment.isocalendar()
    return iso[0], iso[1]


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def summarize(rows: list[dict], round_trip_cost_pct: float, now: Optional[datetime] = None) -> list[dict]:
    """Eén entry per (bron, soort), gesorteerd op aantal afgeronde trades. Alles samen staat als laatste entry
    met bron 'alles'. 'recent' zijn de laatste RECENT_DAYS dagen, de status gaat uit van alles sinds het begin."""
    now = now or datetime.now(timezone.utc)
    recent_cut = now - timedelta(days=RECENT_DAYS)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        source = "community" if r["message_id"] is not None else "scan"
        groups[(source, r["trade_type"])].append(r)
        groups[("alles", "alles")].append(r)
        if r.get("samenval"):
            groups[("scan", "samenval")].append(r)    # ook los zichtbaar, zonder het totaal dubbel te tellen

    out = []
    for (source, trade_type), items in groups.items():
        resolved = [(r, signal_r(r)) for r in items]
        resolved = [(r, g) for r, g in resolved if g is not None]
        net = [g - _cost_r(r, round_trip_cost_pct) for r, g in resolved]
        gross = [g for _, g in resolved]
        wins = sum(1 for g in gross if g > 0)
        recent = [(r, n) for (r, _), n in zip(resolved, net) if _parse(r["created_at"]) >= recent_cut]
        weekly: dict[tuple, float] = defaultdict(float)
        for (r, _), n in zip(resolved, net):
            weekly[_week_key(_parse(r["auto_outcome_at"] or r["created_at"]))] += n
        weeks = []
        cursor = now
        for _ in range(WEEKS_SHOWN):
            weeks.append(_week_key(cursor))
            cursor -= timedelta(days=7)
        weeks.reverse()
        cumulative, running = [], 0.0
        before = sum(v for k, v in weekly.items() if k < weeks[0])
        running = before
        for k in weeks:
            running += weekly.get(k, 0.0)
            cumulative.append(running)
        n_resolved = len(resolved)
        avg_net = sum(net) / n_resolved if n_resolved else None
        out.append({
            "source": source, "trade_type": trade_type,
            "label": "Alle meldingen samen" if source == "alles" else f"{TYPE_LABELS.get(trade_type, trade_type)}",
            "source_label": "" if source == "alles" else SOURCE_LABELS[source],
            "total": len(items), "resolved": n_resolved, "wins": wins, "losses": n_resolved - wins,
            "open_or_expired": len(items) - n_resolved,
            "winrate": wins / n_resolved if n_resolved else None,
            "avg_gross": sum(gross) / n_resolved if n_resolved else None,
            "avg_net": avg_net,
            "recent_resolved": len(recent), "recent_avg_net": sum(n for _, n in recent) / len(recent) if recent else None,
            "status": _status(n_resolved, avg_net), "cumulative": cumulative, "cost_pct": round_trip_cost_pct,
        })
    out.sort(key=lambda e: (e["source"] == "alles", -e["resolved"]))
    return out


def sparkline_svg(values: list[float], width: int = 300, height: int = 56) -> str:
    """Lijn van het cumulatieve resultaat in R over de laatste weken, met een nullijn. Lege of vlakke reeksen
    geven een vlakke lijn in plaats van een fout."""
    if not values:
        return ""
    lo, hi = min(min(values), 0.0), max(max(values), 0.0)
    span = hi - lo or 1.0
    pad = 4

    def y(v: float) -> float:
        return pad + (hi - v) / span * (height - 2 * pad)

    step = (width - 2 * pad) / max(1, len(values) - 1)
    points = " ".join(f"{pad + i * step:.1f},{y(v):.1f}" for i, v in enumerate(values))
    trend = "up" if values[-1] >= values[0] else "down"
    return (f'<svg class="proof-spark proof-spark-{trend}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
            f'aria-label="Cumulatief resultaat in R per week">'
            f'<line class="proof-zero" x1="{pad}" x2="{width - pad}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>'
            f'<polyline points="{escape(points)}"/></svg>')
