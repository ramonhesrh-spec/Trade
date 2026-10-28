"""Misser-controle: een trade die jij zag en HesPulse niet meldde. Je geeft coin, richting, tijd en niveaus, het script zegt per motor of hij de trade
zag en zo niet welke regel hem weigerde. Draait op de VPS (daar staat de geschiedenis en de verbinding met de beurs).

  python3 scripts/misser_check.py --coin BTC --direction short --at "2026-10-08 02:30" --entry 86558.4 --stop 86742.5 --target 83928.2
  python3 scripts/misser_check.py --csv handtrades.csv      (kolommen coin,richting,tijd,instap,stop,doel,uitkomst; --alleen-parsen leest zonder netwerk)

  python3 scripts/misser_check.py --csv docs/onderzoek/zone-sweep/handtrades.csv --motor zonesweep --venster-uren 72   (zone-sweep, zelfde uitvoer)
  python3 scripts/misser_check.py --csv handtrades.csv --motor rangesweep --venster-uren 12   (range sweep: per variant gezien of de weigerende regel;
      --candles-map MAP leest {COIN}_{15m,1h,4h}.csv uit een map in plaats van de beurs)

Tijd is jouw tijd (Nederland). Entry, stop en doel zijn optioneel; met ze erbij meet het script ook of het doel of de stop eerst raakte."""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, exchange, misser, today                                   # noqa: E402
from app.replay import breakretest as br, rangesweep as rs, rejection as rj, zonesweep as zs   # noqa: E402

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
    breaks = br.find_structure_breaks(closed)          # wat de live motor ziet: lijn, range en hogere bodem (CHOCH)
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


def _g(value) -> str:
    return "-" if value is None else f"{value:g}"


# Zelfde combinaties als rangesweep_lab.VARIANTS zonder SPLIT en OIFLUSH. Die twee zien dezelfde setups als hun basisvariant (een andere
# ordergrootte of een filter), dus de misser-controle hoeft ze niet apart te rekenen.
RS_COMBOS = (("RZ_30M", "zone", "30m", "slot", True), ("RZ_1H", "zone", "1h", "slot", True), ("RZ_2H", "zone", "2h", "slot", True),
             ("RZ_4H", "zone", "4h", "slot", True), ("RZ_1H_CHOCH", "zone", "1h", "choch15", True), ("RZ_2H_CHOCH", "zone", "2h", "choch15", True),
             ("RZ_2H_ZONDERHTF", "zone", "2h", "slot", False), ("RS_30M", "sweep", "30m", "slot", True), ("RS_1H", "sweep", "1h", "slot", True),
             ("RS_2H", "sweep", "2h", "slot", True), ("RS_4H", "sweep", "4h", "slot", True), ("RS_1H_CHOCH", "sweep", "1h", "choch15", True),
             ("RS_1H_ZONDERHTF", "sweep", "1h", "slot", False))
# Extra combinaties zonder HTF, alleen hier: ze vertellen of juist het HTF-filter een voorbeeld weigerde. Het zijn geen geregistreerde varianten.
_REGISTERED = {c[0] for c in RS_COMBOS}
RS_DIAG_ONLY = tuple((f"{n}_ZONDERHTF", fam, tf, c, False) for n, fam, tf, c, h in RS_COMBOS
                     if h and f"{n}_ZONDERHTF" not in _REGISTERED)
# Hoe ver een variant kwam: hoe hoger, hoe dichter bij een setup. De blokkerende regel is die van de variant die het verst kwam.
RS_STAGE = (("geen range op", 0), ("range op", 1), ("range en zone", 2), ("zone ligt niet", 2), ("prik te diep", 3), ("geen terugkeer", 3),
            ("HTF-filter", 4), ("geen 15m", 4), ("geen CHoCH", 5), ("geen geldige limiet", 6), ("al een sweep", 6), ("cooldown", 6), ("zone had al", 6))


def _stage(reason: str) -> int:
    return max((v for k, v in RS_STAGE if reason.startswith(k)), default=0)


def cache_fetch(directory: str):
    """Candles uit een map met {COIN}_{tf}.csv (kolommen van data/candles), in de vorm van exchange.fetch_ohlcv: voor draaien zonder verbinding."""
    def fetch(coin: str, timeframe: str, limit: int, since: int) -> pd.DataFrame:
        df = pd.read_csv(Path(directory) / f"{coin.upper()}_{timeframe}.csv")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df[df["timestamp"] >= pd.Timestamp(since, unit="ms", tz="UTC")].head(limit).reset_index(drop=True)
    return fetch


def fetch_rangesweep(coin: str, at: pd.Timestamp, fetch=None) -> dict:
    """15m, 1u en 4u tot 14 uur na `at`, daaruit 30m en 2u zoals het lab. 4u: genoeg voor 180 candles HTF plus de EMA van 200."""
    fetch = fetch or exchange.fetch_ohlcv
    parts = []
    for tf, back in (("15m", pd.Timedelta(days=9)), ("1h", pd.Timedelta(days=40)), ("4h", pd.Timedelta(days=160))):
        df = fetch(coin, timeframe=tf, limit=1000, since=int((at - back).timestamp() * 1000))
        parts.append(df[df["timestamp"] <= at + pd.Timedelta(hours=14)].reset_index(drop=True))
    return rs.build_frames(*parts)


def judge_rangesweep(frames: dict, at: pd.Timestamp, direction: str, tf_hint: str = "", window_hours: float = 12, price: float | None = None) -> dict:
    """Per variant: gezien, of de regel die weigerde (rangesweep.diagnose). `engines` bevat ook de varianten zonder HTF-filter die de trade zagen;
    `htf_only` zegt dat alleen die hem zagen, dus dat het HTF-filter hem weigerde. price: de instap van de trader (zie diagnose)."""
    per, engines = {}, []
    for name, family, tf, confirm, htf in RS_COMBOS + RS_DIAG_ONLY:
        if tf_hint and tf != tf_hint:
            continue
        d = rs.diagnose(frames, at, direction, tf, family, "zone" if family == "zone" else "ob", confirm, htf, pd.Timedelta(hours=window_hours), price=price)
        per[name] = "gezien" if d["seen"] else d["reason"]
        if d["seen"]:
            engines.append(f"range_sweep:{name}")
    blocker = None
    if not engines and per:
        name = max(per, key=lambda n: _stage(per[n]))
        blocker = f"range_sweep: {per[name]} ({name})"
    return {"engines": engines, "blocker": blocker, "per_variant": per, "htf_only": bool(engines) and all(e.endswith("ZONDERHTF") for e in engines)}


# Varianten van de zone-sweep (docs/onderzoek/zone-sweep/preregistratie.md): naam, timeframe, instap, HTF-filter.
ZS_COMBOS = (("ZS_1H", "1h", "zone", True), ("ZS_2H", "2h", "zone", True), ("ZS_4H", "4h", "zone", True), ("ZS_1H_ZONDERHTF", "1h", "zone", False),
             ("ZS_2H_ZONDERHTF", "2h", "zone", False), ("ZS_4H_ZONDERHTF", "4h", "zone", False), ("ZS_2H_MIDDEN", "2h", "midden", True))
ZS_STAGE = (("geen actieve", 0), ("wel een zone", 1), ("uitbraak", 2), ("geen herstel", 2), ("HTF-filter", 3), ("geen geldige limiet", 4), ("zone had al", 4))


def _zs_stage(reason: str) -> int:
    return max((v for k, v in ZS_STAGE if reason.startswith(k)), default=0)


def judge_zonesweep(frames: dict, at: pd.Timestamp, direction: str, tf_hint: str = "", window_hours: float = 12, price: float | None = None) -> dict:
    """Per variant van de zone-sweep: gezien, of de regel die weigerde (zonesweep.diagnose). Zelfde vorm als judge_rangesweep."""
    per, engines = {}, []
    for name, tf, entry, htf in ZS_COMBOS:
        if tf_hint and tf != tf_hint:
            continue
        d = zs.diagnose(frames, at, direction, tf, entry, htf, pd.Timedelta(hours=window_hours), price=price)
        per[name] = "gezien" if d["seen"] else d["reason"]
        if d["seen"]:
            engines.append(f"zone_sweep:{name}")
    blocker = None
    if not engines and per:
        name = max(per, key=lambda n: _zs_stage(per[n]))
        blocker = f"zone_sweep: {per[name]} ({name})"
    return {"engines": engines, "blocker": blocker, "per_variant": per, "htf_only": bool(engines) and all(e.endswith("ZONDERHTF") for e in engines)}


def _print_variants(res: dict) -> None:
    for name, reason in res["per_variant"].items():
        print(f"    {name}: {reason}")


def run_csv(path: str, only_parse: bool, fetch=None, motor: str = "alle", window_hours: float = 12, fetch_rs=None) -> dict | None:
    fetch = fetch or window_for
    try:
        rows = misser.parse_rows(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        sys.exit(f"{path}: {exc}")
    results = []
    for r in rows:
        when = f"{today.local(r['at']):%Y-%m-%d %H:%M}"
        if only_parse:
            print(f"{r['coin']} {r['direction']} {when} instap {r['entry']:g} stop {_g(r['stop'])} doel {_g(r['target'])} uitkomst {r['outcome']}")
            continue
        try:
            if motor in ("rangesweep", "zonesweep"):
                at = pd.Timestamp(r["at"])
                judge_fn = judge_rangesweep if motor == "rangesweep" else judge_zonesweep
                res = judge_fn((fetch_rs or fetch_rangesweep)(r["coin"], at), at, r["direction"], r["tf"], window_hours, price=r["entry"])
            else:
                _, closed, idx = fetch(r["coin"], pd.Timestamp(r["at"]))
                res = judge(closed, idx, r["direction"])
            extra = ""
        except Exception as exc:                                       # een coin zonder data mag de rest van de lijst niet stoppen
            res, extra = {"engines": [], "blocker": "geen data"}, f" ({exc})"
        results.append(res)
        print(f"{r['coin']} {r['direction']} {when}: " + (", ".join(res["engines"]) if res["engines"] else "geen motor") + (f" | {res['blocker']}" if res["blocker"] else "") + (" | alleen zonder HTF-filter gezien" if res.get("htf_only") else "") + extra)
        if "per_variant" in res:
            _print_variants(res)
    if only_parse:
        print(f"{len(rows)} rijen gelezen")
        return None
    s = misser.summarize(results)
    print(f"\n{s['n']} trades, {s['seen']} door minstens een motor gezien")
    print("per motor:", s["by_engine"] or "-")
    print("geweigerd door:", s["by_blocker"] or "-")
    return s


def _rs_fetcher(candles_map: str | None):
    return (lambda coin, at: fetch_rangesweep(coin, at, fetch=cache_fetch(candles_map))) if candles_map else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coin")
    ap.add_argument("--direction", choices=["long", "short"])
    ap.add_argument("--at", help='tijd van de instap, bijvoorbeeld "2026-10-08 02:30" (Nederlandse tijd)')
    ap.add_argument("--entry", type=float)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--target", type=float)
    ap.add_argument("--csv", help="lijst handtrades met de kolommen coin,richting,tijd,instap,stop,doel,uitkomst; sluit de losse opties uit")
    ap.add_argument("--motor", choices=("alle", "rangesweep", "zonesweep"), default="alle")
    ap.add_argument("--venster-uren", type=float, default=12.0)
    ap.add_argument("--candles-map", help="map met {COIN}_{tf}.csv (15m, 1h, 4h) in plaats van de beurs, alleen voor --motor rangesweep")
    ap.add_argument("--alleen-parsen", action="store_true", help="met --csv: alleen inlezen en tonen, zonder verbinding met de beurs")
    a = ap.parse_args()
    if a.csv:
        if any(v is not None for v in (a.coin, a.direction, a.at, a.entry, a.stop, a.target)):
            ap.error("--csv kan niet samen met --coin, --direction, --at, --entry, --stop of --target")
        return run_csv(a.csv, a.alleen_parsen, motor=a.motor, window_hours=a.venster_uren, fetch_rs=_rs_fetcher(a.candles_map))
    if a.alleen_parsen:
        ap.error("--alleen-parsen hoort bij --csv")
    if not (a.coin and a.direction and a.at):
        ap.error("geef --coin, --direction en --at, of --csv")
    coin = a.coin.upper()
    at = pd.Timestamp(datetime.strptime(a.at, "%Y-%m-%d %H:%M").replace(tzinfo=today.LOCAL_TZ)).tz_convert("UTC")
    if a.motor in ("rangesweep", "zonesweep"):
        judge_fn = judge_rangesweep if a.motor == "rangesweep" else judge_zonesweep
        res = judge_fn((_rs_fetcher(a.candles_map) or fetch_rangesweep)(coin, at), at, a.direction, window_hours=a.venster_uren, price=a.entry)
        print(f"\n{coin} {a.direction} rond {a.at} (Nederlandse tijd), {'range sweep' if a.motor == 'rangesweep' else 'zone-sweep'}:")
        _print_variants(res)
        print("gezien door: " + (", ".join(res["engines"]) or "geen variant") + (f" | {res['blocker']}" if res["blocker"] else ""))
        return None
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
        print("  geen breuk van een lijn, range of laatste top/bodem in de 12 uur ervoor. Structuur meldt alleen breuken met een terugkeer, geen afwijzing zonder breuk.")
    print()


if __name__ == "__main__":
    main()
