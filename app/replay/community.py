"""Samenvatting van de community-calls voor het wekelijkse kwaliteitsrapport: gaat de koers na een bericht
de kant van het bericht op (tegen een controle met dezelfde coin en richting op willekeurige momenten), en wat
levert elke call op als vaste trade. Zelfde methode als scripts/replay_community.py."""
import math

import pandas as pd

from app.replay import lab

DEDUP_WINDOW = pd.Timedelta(hours=4)
CONTROL_CATEGORY = "oefening"


def dedupe_calls(calls: pd.DataFrame) -> pd.DataFrame:
    """Maximaal één call per coin en richting per 4 uur: opeenvolgende berichten zijn geen onafhankelijke metingen."""
    calls = calls.sort_values("at")
    return calls[~(calls.groupby(["coin", "direction"])["at"].diff() < DEDUP_WINDOW)]


def paired_diff(calls: pd.DataFrame, frames: dict, delay: int, horizon: int) -> pd.DataFrame:
    """Per call het gerichte rendement na `horizon` minuten (call), het gemiddelde van de controle (ctl) en het verschil."""
    parts = []
    for coin, g in calls.groupby("coin"):
        if coin not in frames:
            continue
        g = g.reset_index(drop=True)
        fr = lab.forward_returns(g, frames[coin], delay, horizons=(horizon,))
        if fr.empty:
            continue
        ctl = lab.placebo_forward(g, frames[coin], delay, horizons=(horizon,))
        keyed = g.reset_index().rename(columns={"index": "idx"})[["idx", "at"]]
        parts.append(fr.merge(keyed, on="at", how="left").drop_duplicates("at").set_index("idx").join(ctl))
    if not parts:
        return pd.DataFrame(columns=["call", "ctl", "diff"])
    df = pd.concat(parts, ignore_index=True)
    out = pd.DataFrame({"call": df[f"pct_{horizon}"], "ctl": df[f"ctl_{horizon}"]}).dropna()
    out["diff"] = out["call"] - out["ctl"]
    return out


def community_summary(calls: pd.DataFrame, frames: dict, fee_pct: float, slippage_pct: float,
                      delay: int = 15, horizon: int = 240, rr: float = 1.5) -> dict:
    """Voor alle echte calls en voor categorie day_trading apart. De controlecategorie 'oefening' telt niet mee."""
    real = calls[(calls["category"] != CONTROL_CATEGORY) & calls["coin"].isin(frames)]
    out = {}
    for label, subset in (("alle", real), ("day_trading", real[real["category"] == "day_trading"])):
        subset = dedupe_calls(subset) if len(subset) else subset
        entry = {"n": len(subset)}
        if len(subset):
            d = paired_diff(subset, frames, delay, horizon)
            entry["n_paired"] = len(d)
            if len(d) >= 2:
                se = d["diff"].std(ddof=1) / math.sqrt(len(d))
                entry.update(call_mean=d["call"].mean(), ctl_mean=d["ctl"].mean(), diff_mean=d["diff"].mean(),
                             t=d["diff"].mean() / se if se else 0.0)
            rows = []
            for coin, g in subset.groupby("coin"):
                rows += lab.trades_from_calls(coin, g, frames[coin], delay, fee_pct, slippage_pct, rr_list=(rr,))
            t = pd.DataFrame(rows)
            if not t.empty:
                done = t[t["result"] != "expired"]
                entry["trades"] = {"n": len(t), "winrate": float((done["result"] == "take_profit").mean()) if len(done) else None,
                                   "gross": float(t["r_gross"].mean()), "net": float(t["r_net"].mean())}
        out[label] = entry
    return out
