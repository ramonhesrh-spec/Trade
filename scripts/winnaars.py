"""Welke trades gaan goed? Alleen-lezen overzicht van echte signalen met een vaststaande uitkomst (doel of stop), geen oefentrades.
Draai op de VPS: .venv/bin/python3 scripts/winnaars.py [--vanaf 2026-09-01] [--min 3]
Delen: per soort, per soort en coin en richting (minstens --min afgeronde), en de laatste trades die het doel haalden. R is netto na
TRACK_RECORD_COST_PCT, zoals Bewijs het rekent. Het beschrijft wat was; een groep met weinig trades zegt niets over wat komt."""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, repo, track_record as tr  # noqa: E402


def stats(rows: list[dict]) -> dict:
    done = [(r, tr.net_signal_r(r, config.TRACK_RECORD_COST_PCT)) for r in rows if r["auto_outcome"] in ("take_profit", "stop_loss")]
    done = [(r, n) for r, n in done if n is not None]
    wins = sum(1 for r, _ in done if r["auto_outcome"] == "take_profit")
    total = sum(n for _, n in done)
    return {"n": len(done), "tp": wins, "sl": len(done) - wins, "net": total, "avg": total / len(done) if done else 0.0}


def line(name: str, s: dict) -> str:
    rate = 100 * s["tp"] / s["n"] if s["n"] else 0
    return f"{name:<34} {s['n']:>3} afgerond  {s['tp']:>3} doel  {s['sl']:>3} stop  {rate:>3.0f}%  netto {s['net']:+6.1f} R  gem {s['avg']:+5.2f} R"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vanaf", default=None, help="alleen signalen vanaf deze datum (JJJJ-MM-DD)")
    ap.add_argument("--min", type=int, default=3, help="minimum afgeronde trades per groep")
    a = ap.parse_args()
    rows = repo.list_signals_for_quality_report(a.vanaf)
    print(f"{len(rows)} signalen" + (f" vanaf {a.vanaf}" if a.vanaf else "") + f", kosten {config.TRACK_RECORD_COST_PCT}% per rondreis\n")
    by_type, by_group = defaultdict(list), defaultdict(list)
    for r in rows:
        by_type[r["trade_type"]].append(r)
        by_group[(r["trade_type"], r["coin"], r["direction"])].append(r)
    print("PER SOORT")
    for t, rs in sorted(by_type.items(), key=lambda kv: -stats(kv[1])["net"]):
        print(line(t, stats(rs)))
    print(f"\nPER SOORT, COIN EN RICHTING (minstens {a.min} afgerond), beste eerst")
    groups = [(k, stats(v)) for k, v in by_group.items()]
    for k, s in sorted((g for g in groups if g[1]["n"] >= a.min), key=lambda g: -g[1]["net"]):
        print(line(f"{k[0]} {k[1]} {k[2]}", s))
    print("\nLAATSTE TRADES DIE HET DOEL HAALDEN")
    wins = [r for r in rows if r["auto_outcome"] == "take_profit"]
    for r in sorted(wins, key=lambda r: r["auto_outcome_at"] or "", reverse=True)[:40]:
        net = tr.net_signal_r(r, config.TRACK_RECORD_COST_PCT)
        print(f"{(r['auto_outcome_at'] or '')[:16]}  {r['trade_type']:<12} {r['coin']:<6} {r['direction']:<5} entry {r['price']}  doel {r['take_profit']}  {net:+.2f} R" if net is not None else "")


if __name__ == "__main__":
    main()
