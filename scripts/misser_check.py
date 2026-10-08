"""Misser-controle: een trade die jij zag en HesPulse niet meldde. Je geeft coin, richting, tijd en niveaus, het script zegt per motor of hij de trade
zag en zo niet welke regel hem weigerde. Draait op de VPS (daar staat de geschiedenis en de verbinding met de beurs).

  python3 scripts/misser_check.py --coin BTC --direction short --at "2026-10-08 02:30" --entry 86558.4 --stop 86742.5 --target 83928.2

Tijd is jouw tijd (Nederland). Entry, stop en doel zijn optioneel; met ze erbij meet het script ook of het doel of de stop eerst raakte."""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, exchange, today                                   # noqa: E402
from app.replay import breakretest as br, rejection as rj             # noqa: E402

BAR = pd.Timedelta(minutes=30)


def fetch_window(coin: str, at: pd.Timestamp) -> pd.DataFrame:
    since = int((at - pd.Timedelta(hours=110)).timestamp() * 1000)
    df = exchange.fetch_ohlcv(coin, timeframe="30m", limit=400, since=since)
    return df[df["timestamp"] <= at + pd.Timedelta(hours=14)].reset_index(drop=True)


def outcome(df: pd.DataFrame, at: pd.Timestamp, direction: str, entry: float, stop: float, target: float) -> str:
    short = direction == "short"
    for c in df[df["timestamp"] >= at].itertuples():
        hit_stop = c.high >= stop if short else c.low <= stop
        hit_take = c.low <= target if short else c.high >= target
        if hit_stop:
            return f"stop eerst, op {today.local(c.timestamp):%d-%m %H:%M}" + (" (doel in dezelfde candle, stop telt)" if hit_take else "")
        if hit_take:
            return f"doel geraakt op {today.local(c.timestamp):%d-%m %H:%M}"
    return "nog geen van beide geraakt"


def db_rows(coin: str, lo: datetime, hi: datetime) -> list[str]:
    out = []
    try:
        with db.session() as conn:
            for r in conn.execute("SELECT id, direction, kind, grade, state, created_at FROM structure_setups WHERE coin = ? AND created_at BETWEEN ? AND ? ORDER BY id",
                                  (coin, lo.isoformat(), hi.isoformat())):
                out.append(f"  Structuur #{r['id']} {r['direction']} {r['kind']} oordeel {r['grade'] or '-'} status {r['state']} ({today.local(datetime.fromisoformat(r['created_at'])):%d-%m %H:%M})")
            for r in conn.execute("SELECT id, trade_type, direction, price, stop_loss, take_profit, auto_outcome, created_at FROM signals WHERE coin = ? AND created_at BETWEEN ? AND ? ORDER BY id",
                                  (coin, lo.isoformat(), hi.isoformat())):
                out.append(f"  Signaal #{r['id']} {r['trade_type']} {r['direction']} instap {r['price']:g} stop {r['stop_loss']:g} doel {r['take_profit']:g} uitkomst {r['auto_outcome'] or 'open'}")
    except Exception as exc:                                           # geen database op deze machine
        out.append(f"  (database niet te lezen: {exc})")
    return out or ["  niets gemeld in dit venster"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coin", required=True)
    ap.add_argument("--direction", required=True, choices=["long", "short"])
    ap.add_argument("--at", required=True, help='tijd van de instap, bijvoorbeeld "2026-10-08 02:30" (Nederlandse tijd)')
    ap.add_argument("--entry", type=float)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--target", type=float)
    a = ap.parse_args()
    coin = a.coin.upper()
    at = pd.Timestamp(datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=today.LOCAL_TZ)).tz_convert("UTC")
    df = fetch_window(coin, at)
    closed = df[df["timestamp"] + BAR <= at + pd.Timedelta(hours=6)].reset_index(drop=True)
    idx = int((closed["timestamp"] <= at).sum()) - 1
    print(f"\n{coin} {a.direction} rond {a.at} (Nederlandse tijd), {len(closed)} candles van 30m")
    if a.entry and a.stop and a.target:
        risk = abs(a.entry - a.stop)
        print(f"Plan: risico {risk / a.entry * 100:.2f}%, doel {abs(a.target - a.entry) / risk:.1f}R, uitkomst: {outcome(df, at, a.direction, a.entry, a.stop, a.target)}")

    print("\nWat de live motoren toen meldden (zelfde coin, 12 uur ervoor en erna):")
    print("\n".join(db_rows(coin, (at - pd.Timedelta(hours=12)).to_pydatetime(), (at + pd.Timedelta(hours=12)).to_pydatetime())))

    lo, hi = max(0, idx - 12), min(len(closed) - 1, idx + 4)
    print("\nRejectie op een niveau:")
    ev = rj.find_rejections(closed)
    near = ev[(ev["direction"] == a.direction) & ev["bar"].between(lo, hi)]
    if len(near):
        for e in near.itertuples():
            plan = rj.plan_for(e, closed, __import__("app.smc_eval", fromlist=["floor_stop"]).floor_stop)
            when = today.local(closed["timestamp"].iloc[int(e.bar)].to_pydatetime())
            print(f"  zag een afwijzing op {when:%d-%m %H:%M}: niveau {e.level:g}, {int(e.touches)} aanrakingen" + (f", instap {plan['entry']:g}, stop {plan['stop']:g}, doelen {[round(t, 6) for t in plan['targets']]}" if plan else ", maar het plan viel af (stop te ver)"))
    else:
        d = rj.diagnose(closed, max(idx, 0), a.direction)
        print(f"  geen afwijzing gezien. Beste niveau {d['level'] if d['level'] is None else format(d['level'], 'g')} met {d['touches']} aanrakingen (nodig: {rj.TOUCHES}).")
        if d["level"] is not None:
            print(f"  afstand prik tot niveau {d['gap_to_level_atr']:.2f} ATR (nodig: ten hoogste {rj.TEST_ATR}), slot {d['close_from_level_atr']:.2f} ATR van het niveau (nodig: minstens {rj.REJECT_ATR}).")

    print("\nStructuur (breuk en terugkeer):")
    breaks = br.find_breaks(closed)
    near = breaks[(breaks["direction"] == a.direction) & breaks["bar"].between(max(0, idx - 24), hi)]
    if len(near):
        for e in near.itertuples():
            print(f"  breuk op {today.local(closed['timestamp'].iloc[int(e.bar)].to_pydatetime()):%d-%m %H:%M}, {e.kind}, {int(e.touches)} aanrakingen, niveau {e.a:g}")
    else:
        print("  geen breuk van een lijn of range in de 12 uur ervoor. Structuur meldt alleen breuken met een terugkeer, geen afwijzing zonder breuk.")
    print()


if __name__ == "__main__":
    main()
