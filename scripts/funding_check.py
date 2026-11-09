"""Funding van afgeronde trades van de focus-soorten achteraf narekenen. Zonder --opslaan alleen-lezen: toont per soort de som en het gemiddelde
in R en hoeveel trades onbekend bleven. Met --opslaan schrijft hij elke meting in trade_funding (ook 'onbekend'), zoals bij de uitkomst.
Draai op de VPS:
.venv/bin/python3 scripts/funding_check.py [--dagen 60] [--soort zone_radar] [--opslaan]
De regel staat in app/funding.py: elk funding-moment na de vulling en vóór het einde van de uitgangscandle, long betaalt een positieve rate,
short ontvangt hem, omgerekend naar R met de stopafstand. Eén aanroep per coin (app/outcome_measure.py houdt de momenten vast)."""
import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import focus, outcome_measure, repo  # noqa: E402


def _fmt(x) -> str:
    return "-" if x is None else f"{x:+.3f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=60)
    ap.add_argument("--soort", choices=focus.FOCUS_TYPES)
    ap.add_argument("--opslaan", action="store_true", help="schrijf elke meting in trade_funding")
    a = ap.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=a.dagen)).isoformat()
    types = (a.soort,) if a.soort else focus.FOCUS_TYPES
    rows = [r for r in repo.list_signals_for_quality_report(since)
            if r["trade_type"] in types and r["auto_outcome"] in ("take_profit", "stop_loss") and r.get("auto_outcome_at")]
    refs = repo.reference_exits()
    windows = [(r, r["created_at"], outcome_measure.exit_end(r, refs.get(r["id"]))) for r in rows]
    print(f"Funding van afgeronde trades, laatste {a.dagen} dagen, in R van de stopafstand. "
          + ("Slaat op in trade_funding." if a.opslaan else "Alleen-lezen: met --opslaan wordt het bewaard.") + "\n")
    by_coin = defaultdict(list)
    for w in windows:
        by_coin[w[0]["coin"]].append(w)
    per_type = defaultdict(lambda: {"r": [], "unknown": 0})
    for coin, items in by_coin.items():
        # Eén aanroep per coin: het hele venster van al zijn trades; de trades daarna komen uit de cache.
        first = min(outcome_measure._ts(s) for _, s, _ in items)
        last = max(e for _, _, e in items)
        try:
            outcome_measure.funding_events(coin, first, last)
            failed = False
        except Exception as exc:
            print(f"  {coin}: funding niet op te halen ({exc})")
            failed = True
        for r, start, end in items:
            g = per_type[r["trade_type"]]
            if failed:          # niet per trade opnieuw proberen: één aanroep per coin
                g["unknown"] += 1
                if a.opslaan:
                    repo.set_trade_funding(r["id"], None, None, None, outcome_measure.UNKNOWN, outcome_measure._ts(start).isoformat(), end.isoformat())
                continue
            m = outcome_measure.record_funding(r, start, end) if a.opslaan else outcome_measure.measure_funding(r, start, end)
            if m is None:
                g["unknown"] += 1
            else:
                g["r"].append(m["funding_r"])
    print(f"{'soort':<14}{'n':>4}{'gemeten':>9}{'onbekend':>10}{'som R':>9}{'per trade':>11}")
    measured = unknown = 0
    for t in types:
        g = per_type.get(t)
        if not g:
            print(f"{focus.label(t)[:13]:<14}{0:>4}  nog geen afgeronde trades")
            continue
        n = len(g["r"]) + g["unknown"]
        measured += len(g["r"])
        unknown += g["unknown"]
        avg = sum(g["r"]) / len(g["r"]) if g["r"] else None
        print(f"{focus.label(t)[:13]:<14}{n:>4}{len(g['r']):>9}{g['unknown']:>10}{_fmt(sum(g['r']) if g['r'] else None):>9}{_fmt(avg):>11}")
    print(f"\n{measured} gemeten, {unknown} onbekend. Positief is betaald (kost R), negatief ontvangen. Onbekend telt op Bewijs niet mee, nooit als nul.")


if __name__ == "__main__":
    main()
