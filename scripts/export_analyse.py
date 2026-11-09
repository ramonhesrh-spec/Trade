"""Alleen-lezen analyse van een nachtexport (scripts/nacht_export.py): netto R per soort, richting, stopafstand, week, coin en 4u-context,
met een bootstrap per ISO-week en het aantal unieke uren (trades in hetzelfde uur zijn niet onafhankelijk).

  python3 scripts/export_analyse.py data/export/hespulse-2026-11-02.json
  python3 scripts/export_analyse.py --tak 2026-11-02        # leest export/hespulse-<datum>.json van origin/hespulse-data
  python3 scripts/export_analyse.py <pad> --vanaf 2026-11-03  # alleen signalen vanaf die datum (H1 telt pas vanaf daar)

Een interval over twee of drie weken zegt bijna niets; het script noemt het aantal weken erbij. Bewijsregister: docs/onderzoek/bewijsregister.md."""
import argparse
import collections
import json
import random
import statistics as st
import subprocess
import sys
from datetime import datetime

DONE = ("take_profit", "stop_loss")


def load(args) -> dict:
    if args.tak:
        text = subprocess.run(["git", "show", f"origin/hespulse-data:export/hespulse-{args.tak}.json"], check=True, capture_output=True, text=True).stdout
        return json.loads(text)
    return json.load(open(args.pad))


def week_interval(rows: list[dict], n: int = 4000, seed: int = 1):
    weeks = collections.defaultdict(list)
    for x in rows:
        weeks[datetime.fromisoformat(x["created_at"]).isocalendar()[:2]].append(x["r_netto"])
    if len(weeks) < 2:
        return None, len(weeks)
    rnd, keys, out = random.Random(seed), list(weeks), []
    for _ in range(n):
        v = [r for k in (rnd.choice(keys) for _ in keys) for r in weeks[k]]
        out.append(sum(v) / len(v))
    out.sort()
    return (out[int(0.025 * n)], out[int(0.975 * n)]), len(weeks)


def line(rows: list[dict], label: str) -> str:
    if not rows:
        return f"{label:34s} n=0"
    r = [x["r_netto"] for x in rows]
    hours = len({x["created_at"][:13] for x in rows})
    ci, weeks = week_interval(rows)
    ci_text = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "-"
    win = sum(1 for x in rows if x["auto_outcome"] == "take_profit") / len(r)
    cost = st.mean(x["r_bruto"] - x["r_netto"] for x in rows)
    return (f"{label:34s} n={len(r):4d} uren={hours:4d} weken={weeks} winst={win:4.0%} netto={st.mean(r):+.3f}R "
            f"95% per week={ci_text} kosten={cost:.3f}R")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pad", nargs="?")
    ap.add_argument("--tak")
    ap.add_argument("--vanaf")
    args = ap.parse_args()
    if not args.pad and not args.tak:
        ap.error("geef een pad of --tak")
    data = load(args)
    rows = [x for x in data["signalen"] if x.get("auto_outcome") in DONE and x.get("r_netto") is not None]
    if args.vanaf:
        rows = [x for x in rows if x["created_at"] >= args.vanaf]
    print(f"Export {data['gemaakt'][:10]}, {len(rows)} afgeronde signalen met R" + (f" vanaf {args.vanaf}" if args.vanaf else ""))
    by = collections.defaultdict(list)
    for x in rows:
        by[x["trade_type"]].append(x)
    print("\n-- per soort --")
    for t in sorted(by):
        print(line(by[t], t))
    print(line(rows, "alles"))
    print("\n-- per soort en richting --")
    for t in sorted(by):
        for d in ("long", "short"):
            print(line([x for x in by[t] if x["direction"] == d], f"{t} {d}"))
    print("\n-- stopafstand (% van de instap) --")
    for lo, hi in ((0, 0.5), (0.5, 1), (1, 2), (2, 100)):
        print(line([x for x in rows if lo <= abs(x["price"] - x["stop_loss"]) / x["price"] * 100 < hi], f"stop {lo}-{hi}%"))
    print("\n-- per ISO-week --")
    weeks = collections.defaultdict(list)
    for x in rows:
        weeks[datetime.fromisoformat(x["created_at"]).strftime("%G-W%V")].append(x)
    for k in sorted(weeks):
        print(line(weeks[k], k))
    print("\n-- trades per (uur, richting): grootte van een cluster -> aantal clusters --")
    clusters = collections.Counter((x["created_at"][:13], x["direction"]) for x in rows)
    print(sorted(collections.Counter(clusters.values()).items()))
    if any("context_4u" in x for x in rows):
        for key, name in (("context_4u", "4u-context eigen coin"), ("btc_4u", "4u-context BTC")):
            print(f"\n-- {name} (H1) --")
            for g in ("mee", "tegen", "neutraal", "onbekend"):
                sel = [x for x in rows if x.get(key) == g]
                print(line(sel, g))
                for d in ("long", "short"):
                    print(line([x for x in sel if x["direction"] == d], f"  {g} {d}"))
    print("\n-- per coin (n >= 8), slechtste eerst --")
    coins = collections.defaultdict(list)
    for x in rows:
        coins[x["coin"]].append(x["r_netto"])
    for c, r in sorted(coins.items(), key=lambda kv: st.mean(kv[1])):
        if len(r) >= 8:
            print(f"{c:6s} n={len(r):3d} netto={st.mean(r):+.2f}R")


if __name__ == "__main__":
    sys.exit(main())
