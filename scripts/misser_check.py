"""Misser-controle: een trade die jij zag en HesPulse niet meldde. Je geeft coin, richting, tijd en niveaus, het script zegt per motor of hij de trade
zag en zo niet welke regel hem weigerde. Draait op de VPS (daar staat de geschiedenis en de verbinding met de beurs).

  python3 scripts/misser_check.py --coin BTC --direction short --at "2026-10-08 02:30" --entry 86558.4 --stop 86742.5 --target 83928.2
  python3 scripts/misser_check.py --csv handtrades.csv      (kolommen coin,richting,tijd,instap,stop,doel,uitkomst; --alleen-parsen leest zonder netwerk)

Tijd is jouw tijd (Nederland). Entry, stop en doel zijn optioneel; met ze erbij meet het script ook of het doel of de stop eerst raakte."""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, exchange, misser, today                                   # noqa: E402
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


def judge(closed: pd.DataFrame, idx: int, direction: str) -> dict:
    """Per motor: zag hij de trade, en zo niet, welke regel weigerde hem. `engines` en `blocker` zijn wat misser.summarize leest; `blocker` is de
    reden van de rejectie-regel (de specifiekste die het script kent), want Structuur weigert alleen met 'geen breuk met terugkeer'."""
    from app import smc_eval
    lo, hi = max(0, idx - 12), min(len(closed) - 1, idx + 4)
    ev = rj.find_rejections(closed)
    rej = ev[(ev["direction"] == direction) & ev["bar"].between(lo, hi)]
    rej_plans = [rj.plan_for(e, closed, smc_eval.floor_stop) for e in rej.itertuples()]
    diag = None if len(rej) else rj.diagnose(closed, max(idx, 0), direction)
    breaks = br.find_breaks(closed)
    near_breaks = breaks[(breaks["direction"] == direction) & breaks["bar"].between(max(0, idx - 24), hi)]

    engines = []
    if any(rej_plans):
        engines.append("rejectie")
    if len(near_breaks):
        engines.append("structuur")
    blocker = None
    if not engines:
        if len(rej):
            blocker = "rejectie: plan viel af (stop te ver)"
        elif not diag["atr"] == diag["atr"]:                           # NaN: te weinig candles voor de ATR, alle vergelijkingen zouden onwaar zijn
            blocker = "rejectie: te weinig candles voor de ATR"
        elif diag["level"] is None or diag["touches"] < rj.TOUCHES:
            blocker = f"rejectie: te weinig aanrakingen (nodig: {rj.TOUCHES})"
        elif diag["gap_to_level_atr"] > rj.TEST_ATR:
            blocker = "rejectie: prik te ver van het niveau"
        elif diag["close_from_level_atr"] < rj.REJECT_ATR:
            blocker = "rejectie: slot te dicht bij het niveau"
        elif not diag.get("bearish", diag.get("bullish")):
            blocker = "rejectie: candle heeft de verkeerde kleur voor de richting"
        else:
            blocker = "rejectie: geen oorzaak aan te wijzen op de instapcandle"   # detector kijkt ook naar idx-12..idx+4 en kent een afkoeltijd
    return {"engines": engines, "blocker": blocker, "rejections": rej, "rejection_plans": rej_plans, "diagnosis": diag, "breaks": near_breaks}


def window_for(coin: str, at: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    df = fetch_window(coin, at)
    closed = df[df["timestamp"] + BAR <= at + pd.Timedelta(hours=6)].reset_index(drop=True)
    return df, closed, int((closed["timestamp"] <= at).sum()) - 1


def run_csv(path: str, only_parse: bool, fetch=None) -> dict | None:
    fetch = fetch or window_for
    try:
        rows = misser.parse_rows(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        sys.exit(f"{path}: {exc}")
    results = []
    for r in rows:
        when = f"{today.local(r['at']):%Y-%m-%d %H:%M}"
        if only_parse:
            print(f"{r['coin']} {r['direction']} {when} instap {r['entry']:g} stop {r['stop']:g} doel {r['target']:g} uitkomst {r['outcome']}")
            continue
        try:
            _, closed, idx = fetch(r["coin"], pd.Timestamp(r["at"]))
            res = judge(closed, idx, r["direction"])
            extra = ""
        except Exception as exc:                                       # een coin zonder data mag de rest van de lijst niet stoppen
            res, extra = {"engines": [], "blocker": "geen data"}, f" ({exc})"
        results.append(res)
        print(f"{r['coin']} {r['direction']} {when}: " + (", ".join(res["engines"]) if res["engines"] else "geen motor") + (f" | {res['blocker']}" if res["blocker"] else "") + extra)
    if only_parse:
        print(f"{len(rows)} rijen gelezen")
        return None
    s = misser.summarize(results)
    print(f"\n{s['n']} trades, {s['seen']} door minstens een motor gezien")
    print("per motor:", s["by_engine"] or "-")
    print("geweigerd door:", s["by_blocker"] or "-")
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coin")
    ap.add_argument("--direction", choices=["long", "short"])
    ap.add_argument("--at", help='tijd van de instap, bijvoorbeeld "2026-10-08 02:30" (Nederlandse tijd)')
    ap.add_argument("--entry", type=float)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--target", type=float)
    ap.add_argument("--csv", help="lijst handtrades met de kolommen coin,richting,tijd,instap,stop,doel,uitkomst; sluit de losse opties uit")
    ap.add_argument("--alleen-parsen", action="store_true", help="met --csv: alleen inlezen en tonen, zonder verbinding met de beurs")
    a = ap.parse_args()
    if a.csv:
        if any(v is not None for v in (a.coin, a.direction, a.at, a.entry, a.stop, a.target)):
            ap.error("--csv kan niet samen met --coin, --direction, --at, --entry, --stop of --target")
        return run_csv(a.csv, a.alleen_parsen)
    if a.alleen_parsen:
        ap.error("--alleen-parsen hoort bij --csv")
    if not (a.coin and a.direction and a.at):
        ap.error("geef --coin, --direction en --at, of --csv")
    coin = a.coin.upper()
    at = pd.Timestamp(datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=today.LOCAL_TZ)).tz_convert("UTC")
    df, closed, idx = window_for(coin, at)
    print(f"\n{coin} {a.direction} rond {a.at} (Nederlandse tijd), {len(closed)} candles van 30m")
    if a.entry and a.stop and a.target:
        risk = abs(a.entry - a.stop)
        print(f"Plan: risico {risk / a.entry * 100:.2f}%, doel {abs(a.target - a.entry) / risk:.1f}R, uitkomst: {outcome(df, at, a.direction, a.entry, a.stop, a.target)}")

    print("\nWat de live motoren toen meldden (zelfde coin, 12 uur ervoor en erna):")
    print("\n".join(db_rows(coin, (at - pd.Timedelta(hours=12)).to_pydatetime(), (at + pd.Timedelta(hours=12)).to_pydatetime())))

    j = judge(closed, idx, a.direction)
    print("\nRejectie op een niveau:")
    if len(j["rejections"]):
        for e, plan in zip(j["rejections"].itertuples(), j["rejection_plans"]):
            when = today.local(closed["timestamp"].iloc[int(e.bar)].to_pydatetime())
            print(f"  zag een afwijzing op {when:%d-%m %H:%M}: niveau {e.level:g}, {int(e.touches)} aanrakingen" + (f", instap {plan['entry']:g}, stop {plan['stop']:g}, doelen {[round(t, 6) for t in plan['targets']]}" if plan else ", maar het plan viel af (stop te ver)"))
    else:
        d = j["diagnosis"]
        print(f"  geen afwijzing gezien. Beste niveau {d['level'] if d['level'] is None else format(d['level'], 'g')} met {d['touches']} aanrakingen (nodig: {rj.TOUCHES}).")
        if d["level"] is not None:
            print(f"  afstand prik tot niveau {d['gap_to_level_atr']:.2f} ATR (nodig: ten hoogste {rj.TEST_ATR}), slot {d['close_from_level_atr']:.2f} ATR van het niveau (nodig: minstens {rj.REJECT_ATR}).")

    print("\nStructuur (breuk en terugkeer):")
    if len(j["breaks"]):
        for e in j["breaks"].itertuples():
            print(f"  breuk op {today.local(closed['timestamp'].iloc[int(e.bar)].to_pydatetime()):%d-%m %H:%M}, {e.kind}, {int(e.touches)} aanrakingen, niveau {e.a:g}")
    else:
        print("  geen breuk van een lijn of range in de 12 uur ervoor. Structuur meldt alleen breuken met een terugkeer, geen afwijzing zonder breuk.")
    print()


if __name__ == "__main__":
    main()
