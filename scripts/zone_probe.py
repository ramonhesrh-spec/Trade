"""Waarom ziet de zone-sweep een voorbeeld niet? Alleen-lezen meting per voorbeeld uit een handtrades-lijst: waar en wanneer lag het laagste punt in het
venster (de prik), welke vraagzones (of aanbodzones bij short) lagen daar dicht bij de instap, was elke zone actief toen de prik kwam en hoe diep (in ATR) was
de prik onder die zone. Zo zie je of onze zone ontbreekt, te vroeg verlopen was, of de prik buiten de grenzen (0,1 tot 2,5 ATR) viel.
Draai op de VPS: .venv/bin/python3 scripts/zone_probe.py --csv docs/onderzoek/zone-sweep/handtrades.csv --venster-uren 72"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app import misser  # noqa: E402
from app.replay import rangesweep as rs, zonesweep as zs  # noqa: E402
from app.replay.lab import add_indicators  # noqa: E402

NEAR_PCT = 3.0


def probe(frames: dict, at: pd.Timestamp, direction: str, entry: float, window: pd.Timedelta) -> list[str]:
    short = direction == "short"
    bt = add_indicators(frames[zs.TRIGGER_TF]).reset_index(drop=True)
    win = bt[(bt["timestamp"] >= at - window) & (bt["timestamp"] <= at + window)]
    if win.empty:
        return ["  geen candles in het venster"]
    col = "high" if short else "low"
    k = int((win[col].idxmax() if short else win[col].idxmin()))
    extreme, when, atr = float(bt.at[k, col]), bt.at[k, "timestamp"], float(bt.at[k, "atr"])
    out = [f"  {'hoogste hoog' if short else 'laagste laag'} in het venster: {extreme:g} op {when:%Y-%m-%d %H:%M} UTC (ATR 1u {atr:g}, {100 * atr / entry:.2f}% van de instap)"]
    for tf in zs.TFS:
        b = add_indicators(rs.closed_only(frames[tf], at + window, tf)).reset_index(drop=True)
        kind = "bear" if short else "bull"
        zones = [z for z in rs.find_zones(b) if z.kind == kind and abs((z.high if not short else z.low) - entry) / entry * 100 <= NEAR_PCT]
        if not zones:
            out.append(f"  {tf}: geen {'aanbod' if short else 'vraag'}zone binnen {NEAR_PCT:g}% van de instap")
            continue
        idx_then = int(((b["timestamp"] + rs.TF_DELTA[tf]) <= when).sum()) - 1
        for z in zones[-4:]:
            edge = z.high if short else z.low
            depth = ((extreme - edge) if short else (edge - extreme)) / atr
            active = idx_then >= 0 and rs.zone_active(z, idx_then)
            known = (b["timestamp"].iloc[z.known_idx] + rs.TF_DELTA[tf])
            verdict = ("actief bij de prik" if active else "NIET actief bij de prik") + (f", prik {depth:.2f} ATR" if depth > 0 else ", de koers prikte er niet door")
            if depth > 0 and not (zs.PRIK_MIN_ATR <= depth <= zs.PRIK_MAX_ATR):
                verdict += f" (buiten {zs.PRIK_MIN_ATR:g} tot {zs.PRIK_MAX_ATR:g} ATR)"
            out.append(f"  {tf}: zone {z.low:g} tot {z.high:g}, bekend sinds {known:%d-%m %H:%M}, {verdict}")
    return out


def main() -> None:
    import misser_check
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--venster-uren", type=float, default=72.0)
    a = ap.parse_args()
    for r in misser.parse_rows(Path(a.csv).read_text(encoding="utf-8-sig")):
        at = pd.Timestamp(r["at"])
        print(f"{r['coin']} {r['direction']} instap {r['entry']:g} rond {at:%Y-%m-%d %H:%M} UTC")
        try:
            print("\n".join(probe(misser_check.fetch_rangesweep(r["coin"], at), at, r["direction"], r["entry"], pd.Timedelta(hours=a.venster_uren))))
        except Exception as exc:
            print(f"  geen data ({exc})")


if __name__ == "__main__":
    main()
