"""Beoordeling van Structuur met aantallen en marges: draai op de VPS (daar staat de data).

  cd /opt/crypto-alerts && .venv/bin/python3 scripts/structure_review.py [--cost 0.06] [--dagen 30]

Toont de trechter (gezien, plan, gevuld, afgerond), het resultaat zoals Bewijs het meet (doel 2 of stop) en zoals jij het handelt (ladder met stop naar de
instap), en daarna dezelfde cijfers per eigenschap. Een groep onder 20 trades krijgt geen conclusie."""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, db, structure_live, structure_review as sr   # noqa: E402


def load(days: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.id, s.coin, s.direction, s.kind, s.grade, s.state, s.created_at, s.break_at, s.features, s.plan, s.signal_id,
                      g.price, g.stop_loss, g.take_profit, g.auto_outcome, g.created_at AS fired_at
               FROM structure_setups s LEFT JOIN signals g ON g.id = s.signal_id
               WHERE s.created_at >= ? ORDER BY s.id""", (since,)).fetchall()
    out = []
    for r in map(dict, rows):
        plan = json.loads(r["plan"]) if r["plan"] else {}
        r["risk_pct"] = plan.get("risk_pct")
        r["target2_r"] = (plan.get("targets_r") or [None, None])[1] if len(plan.get("targets_r") or []) > 1 else (plan.get("targets_r") or [None])[0]
        if r["fired_at"]:
            fired = datetime.fromisoformat(r["fired_at"])
            r["hour_utc"] = fired.astimezone(timezone.utc).hour
            r["wait_hours"] = (fired - datetime.fromisoformat(r["break_at"])).total_seconds() / 3600
        out.append(r)
    return out


def fmt(s: dict) -> str:
    if not s["n"]:
        return "geen afgeronde trades"
    lo, hi = s["avg_ci"]
    wlo, whi = s["winrate_ci"]
    return (f"n={s['n']:<3} winst {s['winrate'] * 100:3.0f}% ({wlo * 100:.0f}-{whi * 100:.0f}%)  netto {s['total']:+6.1f}R  gemiddeld {s['avg']:+.2f}R "
            f"({lo:+.2f} tot {hi:+.2f})  {s['verdict']}")


def report_missed(rows: list[dict]) -> None:
    import pandas as pd
    from app import exchange
    expired = [r for r in rows if r["state"] == "expired"]
    print(f"\nBreuken die nooit vulden ({len(expired)}): wat deed de koers in de 12 uur na de breuk?")
    tally: dict[str, int] = {}
    for r in expired:
        plan = json.loads(r["plan"]) if r["plan"] else {}
        if not plan.get("targets") or "stop" not in plan:
            continue
        start = datetime.fromisoformat(r["break_at"])
        try:
            df = exchange.fetch_ohlcv(r["coin"], timeframe="5m", limit=144, since=int(start.timestamp() * 1000))
        except Exception as exc:
            print(f"  #{r['id']} {r['coin']}: geen candles ({exc})")
            continue
        result = sr.after_break(r["direction"], lambda t, r=r: structure_live.line_value(r, t), plan["stop"], plan["targets"], df[df["timestamp"] < pd.Timestamp(start + timedelta(hours=12))])
        tally[result] = tally.get(result, 0) + 1
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v}")
    print("  doel 2 en doel 1 zijn kansen die zonder terugkeer wegliepen: daar kost wachten op de limiet je de trade.")
    print("  kwam terug zonder vulling kan niet, tenzij de limiet net gemist is; stop betekent dat wachten je een verlies bespaarde.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=config.TRACK_RECORD_COST_PCT, help="kosten per rondreis in procenten van de instap")
    ap.add_argument("--dagen", type=int, default=30)
    ap.add_argument("--gemist", action="store_true", help="kijk wat de breuken deden die nooit vulden (haalt candles op bij de beurs)")
    a = ap.parse_args()
    rows = load(a.dagen)
    print(f"\nStructuur, laatste {a.dagen} dagen, kosten {a.cost}% per rondreis\n")

    f = sr.funnel(rows)
    print("Trechter")
    print(f"  {f['gezien']} breuken gezien, {f['gevuld']} gevuld ({f['gevuld'] / f['gezien'] * 100 if f['gezien'] else 0:.0f}%), {f['afgerond']} afgerond")
    print("  status: " + ", ".join(f"{k} {v}" for k, v in sorted(f["per_status"].items(), key=lambda kv: -kv[1])))

    print("\nPer oordeel, alle breuken (ook die niet vulden)")
    for g, e in sorted(sr.funnel_by_grade(rows).items(), key=lambda kv: -kv[1]["gezien"]):
        print(f"  {g:<16} {e['gezien']:>3} gezien, {e['gevuld']:>3} gevuld ({e['gevuld'] / e['gezien'] * 100:.0f}%)")

    if a.gemist:
        report_missed(rows)

    done = [r for r in rows if r.get("signal_id") and r.get("auto_outcome") in ("take_profit", "stop_loss")]
    for r in done:
        r["net"] = sr.net_r(r, a.cost)
        r["ladder"] = sr.ladder_r(r["plan"], 0.0)
    open_n = sum(1 for r in rows if r.get("signal_id") and r.get("auto_outcome") not in ("take_profit", "stop_loss"))
    print(f"\nGevuld maar nog zonder uitkomst of vervallen: {open_n} (tellen niet mee in de cijfers hieronder, ze staan wel naast de uitkomsten)")

    ordered = sorted(done, key=lambda r: r["fired_at"])
    print("\nZoals Bewijs het meet (tweede doel of stop)")
    print("  " + fmt(sr.summarize([r["net"] for r in ordered])))
    if ordered:
        print(f"  slechtste reeks verliezen {sr.longest_losing_streak([r['net'] for r in ordered])}, grootste daling {sr.max_drawdown([r['net'] for r in ordered]):.1f}R")
    ladder = [r["ladder"] for r in ordered if r["ladder"] is not None]
    print("\nZoals jij het handelt (een derde per doel, stop naar de instap na T1, zonder kosten)")
    print("  " + fmt(sr.summarize(ladder)))
    print("  Bewijs en ladder verschillen omdat Bewijs alleen het tweede doel meet. Wijken ze ver af, dan meet Bewijs niet wat jij handelt.")

    for name, key in sr.DIMENSIONS.items():
        groups: dict[str, list[float]] = {}
        for r in ordered:
            groups.setdefault(key(r), []).append(r["net"])
        print(f"\nPer {name}")
        for label, values in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"  {label:<24} {fmt(sr.summarize(values))}")
    print("\nLees dit zo: de marge tussen haakjes is het 95%-bereik van het gemiddelde in R. Omvat de marge 0, dan weten we het nog niet.\n")


if __name__ == "__main__":
    main()
