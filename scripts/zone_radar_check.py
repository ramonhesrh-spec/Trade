"""Waarom eindigen zone-radar-trades bijna altijd op de stop? Alleen-lezen. Draai op de VPS: .venv/bin/python3 scripts/zone_radar_check.py
Per afgeronde zone-radar-trade: hoe snel na de vulling kwam de uitkomst, en hoe ver de stop en het doel van de instap lagen. Een stop binnen
een kwartier na de vulling wijst op een koers die dwars door de zone loopt (of op een fout in de uitkomst); een lange tijd tot de stop op een zone die wel
even hield en daarna brak."""
import sys
from datetime import datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import repo  # noqa: E402


def minutes(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60


def main() -> None:
    rows = [r for r in repo.list_signals_for_quality_report() if r["trade_type"] == "zone_radar" and r["auto_outcome"] in ("take_profit", "stop_loss") and r["auto_outcome_at"]]
    print(f"{len(rows)} afgeronde zone-radar-trades\n")
    for label, outcome in (("doel", "take_profit"), ("stop", "stop_loss")):
        part = [r for r in rows if r["auto_outcome"] == outcome]
        if not part:
            continue
        mins = sorted(minutes(r["created_at"], r["auto_outcome_at"]) for r in part)
        stop_pct = [abs(r["price"] - r["stop_loss"]) / r["price"] * 100 for r in part]
        print(f"{label}: {len(part)} trades, mediaan {median(mins):.0f} min na de vulling, snelste {mins[0]:.0f} min, traagste {mins[-1]:.0f} min, "
              f"mediane stopafstand {median(stop_pct):.2f}%")
        for limit in (5, 15, 60):
            print(f"   binnen {limit:>2} min: {sum(1 for m in mins if m <= limit)}")
    print("\nPER TRADE (stop binnen 15 min eerst)")
    for r in sorted(rows, key=lambda r: minutes(r["created_at"], r["auto_outcome_at"])):
        m = minutes(r["created_at"], r["auto_outcome_at"])
        print(f"{r['created_at'][:16]}  {r['coin']:<6} {r['direction']:<5} {r['auto_outcome']:<12} na {m:6.0f} min  instap {r['price']}  stop {r['stop_loss']}  doel {r['take_profit']}")


if __name__ == "__main__":
    main()
