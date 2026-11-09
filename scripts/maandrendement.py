"""Wat had elke gemelde kans per maand opgeleverd met een vast risico per trade (standaard 1% van het account)?
Draai op de VPS:   .venv/bin/python3 scripts/maandrendement.py [--risico 1.0] [--kosten 0.06] [--vast] [--soort smc,patroon] [--sinds 2026-08-01]
Telt alleen afgeronde take- of stopuitkomsten, netto R zoals Bewijs. Dit is een terugblik, geen belofte."""
import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, monthly_sim, repo, track_record  # noqa: E402


def pct(value) -> str:
    return "-" if value is None else f"{value:+.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--risico", type=float, default=1.0, help="procent van het account dat per trade op het spel staat")
    ap.add_argument("--kosten", type=float, default=config.TRACK_RECORD_COST_PCT)
    ap.add_argument("--vast", action="store_true", help="vast bedrag per trade in plaats van samengesteld")
    ap.add_argument("--soort", default=None, help="kommalijst van soorten, bijvoorbeeld smc,patroon")
    ap.add_argument("--sinds", default=None, help="alleen signalen gemeld vanaf deze datum (YYYY-MM-DD)")
    a = ap.parse_args()

    types = [t.strip() for t in a.soort.split(",") if t.strip()] if a.soort else None
    rows = repo.list_signals_for_quality_report(a.sinds)
    kw = {"risk_pct": a.risico, "cost_pct": a.kosten, "compound": not a.vast}
    res = monthly_sim.simulate(rows, trade_types=types, **kw)
    t = res["totals"]

    print(f"Maandrendement, {a.risico:g}% risico per trade")
    print(f"{'vast bedrag' if a.vast else 'samengesteld'}, start 100")
    print()
    print(f"{'maand':<8}{'trades':>7}{'winst':>6}{'R netto':>9}{'rend.':>8}{'eind':>8}")
    for m in res["months"]:
        print(f"{m['month']:<8}{m['trades']:>7}{m['wins']:>6}{m['net_r']:>+9.2f}{pct(m['return_pct']):>8}{m['end_equity']:>8.1f}")
    if not res["months"]:
        print("(geen afgeronde trades)")

    print()
    print("Totaal")
    if t["n"]:
        print(f"trades {t['n']}, winrate {t['winrate_pct']:.0f}%, gem. R {t['avg_net_r']:+.2f}")
        print(f"totaal rendement {pct(t['total_return_pct'])}, eind {t['end_equity']:.1f}")
        print(f"beste maand {t['best_month']['month']} {pct(t['best_month']['return_pct'])}")
        print(f"slechtste maand {t['worst_month']['month']} {pct(t['worst_month']['return_pct'])}")
        print(f"max. daling {t['max_drawdown_pct']:.1f}%")
        print(f"langste verliesreeks {t['longest_losing_streak']} trades")

    by_type = monthly_sim.simulate_by_type(rows, **kw)
    by_type = {k: v for k, v in by_type.items() if v["n"] and (types is None or k in types)}
    if by_type:
        print()
        print("Per soort")
        print(f"{'soort':<14}{'n':>4}{'win%':>6}{'R':>7}{'rend.':>8}{'daling':>8}")
        for name, v in sorted(by_type.items(), key=lambda kv: -kv[1]["total_return_pct"]):
            print(f"{track_record.TYPE_LABELS.get(name, name).split(' (')[0][:13]:<14}{v['n']:>4}{v['winrate_pct']:>6.0f}{v['avg_net_r']:>+7.2f}{pct(v['total_return_pct']):>8}{v['max_drawdown_pct']:>7.1f}%")

    print()
    print("Let op")
    for w in res["warnings"]:
        print(textwrap.fill(w, 58, initial_indent="- ", subsequent_indent="  "))


if __name__ == "__main__":
    main()
