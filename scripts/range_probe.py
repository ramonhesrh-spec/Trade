"""Meet waarom de misser-controle jouw voorbeelden niet ziet en toetst losse, vooraf benoemde instellingen van de range-detector. Draai op de VPS:

  .venv/bin/python3 scripts/range_probe.py --csv docs/onderzoek/range-sweep/handtrades.csv

Eerst per voorbeeld de gemeten waarden van de beste range op het moment van de trade (aanrakingen, breedte in ATR, grootste slot buiten de range),
dan per instelling hoeveel voorbeelden minstens één variant zag. Er verandert niets aan de code of de database: dit is een meting, geen afstelling.
Een instelling die hier meer voorbeelden ziet, gaat pas de detector in na een nieuwe poort 1 (30 willekeurige kaarten)."""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import misser_check  # noqa: E402
from app import misser  # noqa: E402
from app.replay import rangesweep as rs, trendlab as tl  # noqa: E402
from app.replay.lab import add_indicators  # noqa: E402

SETTINGS = {
    "basis": {},
    "aanrakingen 2": {"TOUCHES": 2},
    "breedte min 2 ATR": {"RANGE_MIN_ATR": 2.0},
    "breedte min 1,5 ATR": {"RANGE_MIN_ATR": 1.5},
    "slot buiten 0,5 ATR": {"CONTAIN_ATR": 0.5},
    "slot buiten 1,0 ATR": {"CONTAIN_ATR": 1.0},
    "cluster 0,75 ATR": {"CLUSTER_ATR": 0.75},
    "cluster 1,0 ATR": {"CLUSTER_ATR": 1.0},
    "aanrakingen 2 + breedte 2": {"TOUCHES": 2, "RANGE_MIN_ATR": 2.0},
    "aanrakingen 2 + breedte 2 + slot 0,5": {"TOUCHES": 2, "RANGE_MIN_ATR": 2.0, "CONTAIN_ATR": 0.5},
    "aanrakingen 2 + breedte 2 + slot 1,0 + cluster 0,75": {"TOUCHES": 2, "RANGE_MIN_ATR": 2.0, "CONTAIN_ATR": 1.0, "CLUSTER_ATR": 0.75},
}


def measure(frame: pd.DataFrame, at: pd.Timestamp, tf: str) -> dict:
    """De beste range zoals range_at hem bouwt, maar zonder af te kappen: wat is er gemeten en welke grens zou hem afwijzen."""
    b = add_indicators(frame).reset_index(drop=True)
    i = int(((b["timestamp"] + rs.TF_DELTA[tf]) <= at).sum()) - 1
    hi, lo, close, atr = (b[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    ph, pl = tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N)
    lo_idx, hi_idx = max(0, i - rs.RANGE_LOOKBACK[tf]), i - rs.PIVOT_N
    highs = np.flatnonzero(ph[lo_idx:hi_idx + 1]) + lo_idx
    lows = np.flatnonzero(pl[lo_idx:hi_idx + 1]) + lo_idx
    a = float(atr[i])
    hc = highs[rs._best_cluster(hi[highs], rs.CLUSTER_ATR * a)] if len(highs) else highs
    lc = lows[rs._best_cluster(lo[lows], rs.CLUSTER_ATR * a)] if len(lows) else lows
    out = {"aanrakingen boven": len(hc), "aanrakingen onder": len(lc)}
    if len(hc) and len(lc):
        top, bottom = float(hi[hc].max()), float(lo[lc].min())
        start = int(min(hc.min(), lc.min()))
        inside = close[start:i + 1]
        out.update({"breedte ATR": round((top - bottom) / a, 2),
                    "grootste slot buiten ATR": round(float(max((inside - top).max(), (bottom - inside).max(), 0.0)) / a, 2)})
    return out


def seen_by(frames: dict, row: dict, at: pd.Timestamp) -> int:
    res = misser_check.judge_rangesweep(frames, at, row["direction"], row["tf"], 12, price=row["entry"])
    return len(res.get("engines") or [])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()
    rows = misser.parse_rows(Path(a.csv).read_text(encoding="utf-8-sig"))
    data = []
    for r in rows:
        at = pd.Timestamp(r["at"])
        frames = misser_check.fetch_rangesweep(r["coin"], at)
        data.append((r, at, frames))
        print(f"{r['coin']} {r['direction']} {r['tf']} {r['at']}")
        for tf in ([r["tf"]] if r["tf"] else list(rs.TFS)):
            try:
                print("   ", tf, measure(frames[tf], at, tf))
            except Exception as exc:
                print("   ", tf, "niet te meten:", exc)
    print("\nper instelling: aantal voorbeelden dat minstens één variant zag")
    base = {k: getattr(rs, k) for k in ("TOUCHES", "RANGE_MIN_ATR", "CONTAIN_ATR", "CLUSTER_ATR")}
    for name, change in SETTINGS.items():
        for k, v in {**base, **change}.items():
            setattr(rs, k, v)
        seen = [f"{r['coin']}{'' if seen_by(fr, r, at) else '(nee)'}" for r, at, fr in data]
        n = sum(1 for s in seen if "(nee)" not in s)
        print(f"{n}/{len(data)}  {name}: {' '.join(seen)}")
    for k, v in base.items():
        setattr(rs, k, v)


if __name__ == "__main__":
    main()
