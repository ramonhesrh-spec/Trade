"""Limiet, market of stop-order: welk ordertype werkt het best voor de plannen van het HesPulse-model? (B-2026-11-03-13, preregistratie
aanvulling 2026-11-03 nacht). Laat het model over de laatste dagen lopen op alle vaste coins, alleen op gesloten candles (prefix-vast: een
plan staat er pas op het moment dat het bekend was), en meet per plan de drie instappen uit app/entry_compare.py met dezelfde stop en
hetzelfde doel. Alleen lezen: niets gaat de database in, er gaat geen melding uit.

    .venv/bin/python3 scripts/instap_vergelijking.py                  # 30 dagen, alle coins
    .venv/bin/python3 scripts/instap_vergelijking.py --dagen 30 --coins BTC,ETH

Uitvoer per instappunt en ordertype: plannen, gevuld, afgerond, winst, netto R per trade en per plan (een plan zonder vulling telt als 0), en
het verschil met de limiet per plan met het weekinterval (98,75%). Dit is een terugblik op de regels van nu, geen live meting."""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app import config, entry_compare as ec, model, model_measure as mm  # noqa: E402
from app.replay import stats  # noqa: E402

CODES = {"entry": "A", "b": "B", "b0": "B0", "r": "R", "k": "K"}
EXTRA = {"1d": pd.Timedelta(days=400), "4h": pd.Timedelta(days=12), "1h": pd.Timedelta(days=6), "15m": pd.Timedelta(days=3), "5m": pd.Timedelta(days=8)}
PAGE = 1000


def fetch_since(coin: str, tf: str, since: pd.Timestamp, until: pd.Timestamp) -> pd.DataFrame:
    from app import exchange
    parts, ms = [], int(since.timestamp() * 1000)
    while True:
        df = exchange.fetch_ohlcv(coin, timeframe=tf, limit=PAGE, since=ms)
        if df is None or not len(df):
            break
        parts.append(df)
        last = df["timestamp"].iloc[-1]
        if last >= until or len(df) < PAGE:
            break
        ms = int((last + model.TF[tf]).timestamp() * 1000)
        time.sleep(0.1)
    if not parts:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def plans_of(coin: str, now: pd.Timestamp, days: int, fetch=fetch_since):
    start = now - pd.Timedelta(days=days)
    frames = {tf: fetch(coin, tf, start - EXTRA[tf], now) for tf in ("1d", "4h", "1h", "15m")}
    b5 = fetch(coin, "5m", start, now)
    from model_kaarten import stored_pocs
    scs = model.scenarios(frames, now, stored_pocs(coin, now))
    breaks = model.break_times(frames["4h"], now)
    out = []
    for sc in scs:
        for key, code in CODES.items():
            p = sc.get(key)
            if not p or pd.Timestamp(p["known_at"]) < start or p.get("take") is None:
                continue
            res = ec.compare_plan(sc["direction"], p, b5, frames["15m"], breaks)
            out.append({"coin": coin, "code": code, "direction": sc["direction"], "known_at": pd.Timestamp(p["known_at"]), "plan": p, "arms": res})
    return out


def summarize(rows: list[dict], cost_pct: float) -> list[dict]:
    """Per instappunt en ordertype. netto = bruto R min de kosten van een rondreis in R (dezelfde kosten voor alle drie: in werkelijkheid is
    een market- of stop-order duurder dan een limiet, dus dit bevoordeelt die twee)."""
    out = []
    for code in ("A", "B", "B0", "R", "K", "alle"):
        rs = [r for r in rows if code == "alle" or r["code"] == code]
        if not rs:
            continue
        per_plan = {}
        for arm in ec.ARMS:
            trades, plan_r, weeks = [], [], []
            filled = 0
            for r in rs:
                a = r["arms"].get(arm) or {}
                net = 0.0
                if a.get("state") == "gevuld":
                    filled += 1
                    if a.get("outcome") in ("take_profit", "stop_loss"):
                        stop_pct = abs(a["entry"] - r["plan"]["stop"]) / a["entry"] * 100
                        net = a["r"] - (cost_pct / stop_pct if stop_pct else 0.0)
                        trades.append({"net": net, "direction": r["direction"], "start": r["known_at"].to_pydatetime(),
                                       "end": pd.Timestamp(a["end"]).to_pydatetime()})
                plan_r.append(net)
                weeks.append(stats.week_key(r["known_at"].to_pydatetime()))
            per_plan[arm] = (plan_r, weeks)
            arm_stats = mm.arm(trades)
            wins = sum(1 for t in trades if t["net"] > 0)
            out.append({"code": code, "arm": arm, "plans": len(rs), "filled": filled, "done": len(trades),
                        "win": wins / len(trades) if trades else None, "mean": arm_stats["mean"], "ci": arm_stats["ci"],
                        "per_plan": sum(plan_r) / len(plan_r) if plan_r else None, "diff": None})
        base, weeks = per_plan["limiet"]
        for row in out[-len(ec.ARMS):]:
            if row["arm"] == "limiet" or not base:
                continue
            other = per_plan[row["arm"]][0]
            diffs = [o - b for o, b in zip(other, base)]
            row["diff"] = stats.cluster_bootstrap_mean(diffs, weeks, level=mm.LEVEL)
    return out


def _r(x) -> str:
    return "–" if x is None else f"{x:+.2f}".replace(".", ",")


def report(summary: list[dict], coins: int, days: int, n_plans: int) -> str:
    lines = [f"Instap-vergelijking HesPulse-model: {n_plans} plannen, {coins} coins, {days} dagen. Netto na {config.TRACK_RECORD_COST_PCT}% per rondreis.",
             "Per plan: een plan zonder vulling telt als 0 R. Verschil: per plan min de limiet, weekinterval 98,75%.", "",
             f"{'punt':<5} {'type':<7} {'plannen':>7} {'gevuld':>7} {'af':>5} {'winst':>6} {'R/trade':>8} {'R/plan':>8}  verschil met limiet"]
    for s in summary:
        win = "–" if s["win"] is None else f"{s['win'] * 100:.0f}%"
        diff = "" if s["arm"] == "limiet" else ("–" if not s["diff"] else f"{_r(s['diff'][0])} tot {_r(s['diff'][1])}")
        lines.append(f"{s['code']:<5} {s['arm']:<7} {s['plans']:>7} {s['filled']:>7} {s['done']:>5} {win:>6} {_r(s['mean']):>8} {_r(s['per_plan']):>8}  {diff}")
    lines += ["", "Lezen: een ordertype is pas beter als het hele interval van het verschil boven 0 ligt. Drie typen en zes rijen zijn veel",
              "vergelijkingen; één interval net boven 0 is geen bewijs. Market en stop betalen in werkelijkheid meer kosten dan hier staat."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dagen", type=int, default=30)
    ap.add_argument("--coins", default=",".join(config.FIXED_COINS))
    a = ap.parse_args()
    now = pd.Timestamp(datetime.now(timezone.utc)).floor("5min")
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    rows = []
    for coin in coins:
        try:
            got = plans_of(coin, now, a.dagen)
            rows += got
            print(f"{coin}: {len(got)} plannen", file=sys.stderr)
        except Exception as exc:
            print(f"{coin}: overgeslagen ({type(exc).__name__}: {exc})", file=sys.stderr)
    print(report(summarize(rows, config.TRACK_RECORD_COST_PCT), len(coins), a.dagen, len(rows)))


if __name__ == "__main__":
    main()
