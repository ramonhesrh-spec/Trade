"""Hoe lang was een kansmelding onderweg? Alleen-lezen, uit de tabel alert_timing (één rij per verzonden push uit send_kans_push). Draai op de VPS:
.venv/bin/python3 scripts/vertraging.py [--dagen 7]
Per soort: aantal aangekomen pushes, mediaan en 90e percentiel van candle-slot tot verzonden, en de mediaan van candle-slot tot detectie (het deel
van de motor; de rest is oordeel, budget en verzenden). Begrippen in app/latency.py. Mislukte pushes staan apart en tellen niet mee."""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import focus, latency, repo  # noqa: E402


def _s(x) -> str:
    return "-" if x is None else f"{x:.0f} s"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=7)
    ap.add_argument("--soort", help="alleen deze soort (trade_type), bijvoorbeeld zone_radar")
    a = ap.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=a.dagen)).isoformat()
    rows = [r for r in repo.list_alert_timings(since) if not a.soort or r["trade_type"] == a.soort]
    print(f"Vertraging van kansmeldingen, laatste {a.dagen} dagen, van het candle-slot tot de verzonden push. Alleen-lezen.\n")
    if not rows:
        print("Nog geen metingen. Ze komen er vanaf deze versie bij elke verzonden kansmelding van de focus-soorten.")
        return
    for event in ("nieuw", "vulling"):
        part = [r for r in rows if r["event"] == event]
        if not part:
            continue
        print(f"{'Nieuwe kaart' if event == 'nieuw' else 'Vulling'}:")
        print(f"  {'soort':<16}{'n':>5}{'mediaan':>10}{'90%':>10}{'tot detectie':>14}{'mislukt':>9}")
        stats = latency.stats(part)
        for t in sorted(stats, key=lambda t: (t not in focus.FOCUS_TYPES, t)):
            s = stats[t]
            print(f"  {focus.label(t)[:15]:<16}{s['n']:>5}{_s(s['median_s']):>10}{_s(s['p90_s']):>10}{_s(s['detect_median_s']):>14}{s['failed']:>9}")
        print()
    print("Een push per gebruiker: tien leerlingen maken van één kans tien rijen. Een vulling in de candle die nog vormde telt vanaf het laatste"
          " 5m-slot vóór de detectie.")


if __name__ == "__main__":
    main()
