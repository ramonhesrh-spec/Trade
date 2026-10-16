"""Keuren met het oog. Twee standen, draai op de VPS (of lokaal met --candles-map):

  # poort 0b: elk voorbeeld uit de CSV met onze ranges en zones op dat moment, naast de screenshot te leggen
  .venv/bin/python3 scripts/range_sweep_gallery.py --csv docs/onderzoek/range-sweep/handtrades.csv --uit /tmp/range_sweep_voorbeelden.html
  # poort 1: willekeurige setups uit de historie, vaste seed
  .venv/bin/python3 scripts/range_sweep_gallery.py --coins BTC,ETH,SOL,ARB,APT,AAVE --n 30 --uit /tmp/range_sweep_galerij.html

Per kaart: klopt / klopt niet, met een reden (in docs/onderzoek/range-sweep/missers.md). Poort 1: minstens 80% klopt.
De pagina is statisch: open het bestand in de browser, er is geen server nodig."""
import argparse
import random
import sys
from html import escape
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app import misser, setup_chart  # noqa: E402
from app.replay import candles as cc, rangesweep as rs  # noqa: E402
from app.replay.lab import add_indicators  # noqa: E402

COMBOS = (("zone", "zone", "slot"), ("sweep", "ob", "slot"))
STOP = "zone_025"
SEED = 7
PAGE_CSS = "body{background:var(--bg);color:var(--text);font-family:var(--font,sans-serif);max-width:680px;margin:0 auto;padding:16px}section{margin:0 0 28px}h2{font-size:14px;margin:0 0 8px}p{color:var(--text-dim);font-size:13px}"


def _candles(frame: pd.DataFrame, t0, t1) -> list[list]:
    w = frame[(frame["timestamp"] >= t0) & (frame["timestamp"] <= t1)]
    return [[r.timestamp.isoformat(), r.open, r.high, r.low, r.close] for r in w.itertuples()]


def zones_at(frame: pd.DataFrame, at, tf: str) -> list[dict]:
    """De zones die op het laatste gesloten slot vóór `at` actief waren."""
    b = add_indicators(frame).reset_index(drop=True)
    idx = int(((b["timestamp"] + rs.TF_DELTA[tf]) <= at).sum()) - 1
    return [{"low": z.low, "high": z.high, "from": b["timestamp"].iloc[z.ob_idx].isoformat(), "kind": z.kind}
            for z in rs.find_zones(b) if rs.zone_active(z, idx)]


def card(title: str, frame: pd.DataFrame, setup: dict, zones: list[dict]) -> str:
    span = setup["placed_at"] - setup["range_first_at"]
    candles = _candles(frame, setup["range_first_at"] - span * 0.15, setup["placed_at"] + pd.Timedelta(hours=24))
    own = {(round(setup["zone_low"], 8), round(setup["zone_high"], 8)), }
    others = [z for z in zones if (round(z["low"], 8), round(z["high"], 8)) not in own]
    return (f"<section><h2>{escape(title)}</h2>{setup_chart.range_sweep_svg(candles, setup, rs.final_stop(setup, STOP), zones=others)}"
            "<p>klopt / klopt niet: ______</p></section>")


def page(cards: list[str]) -> str:
    css = (ROOT / "web" / "static" / "style.css").read_text(encoding="utf-8")
    return f"<!doctype html><html lang=nl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Range sweep keuring</title><style>{css}{PAGE_CSS}</style><body>" + "".join(cards) + "</body></html>"


def from_csv(path: str, fetch_frames) -> list[str]:
    cards = []
    for r in misser.parse_rows(Path(path).read_text(encoding="utf-8-sig")):
        at = pd.Timestamp(r["at"])
        frames = fetch_frames(r["coin"], at)
        for tf in ([r["tf"]] if r["tf"] else list(rs.TFS)):
            found = False
            for family, entry, confirm in COMBOS:
                d = rs.diagnose(frames, at, r["direction"], tf, family, entry, confirm, False, pd.Timedelta(hours=36), price=r["entry"])
                if d["seen"]:
                    cards.append(card(f"{r['coin']} {r['direction']} {tf} {family}: gezien · {r['source']}", frames[tf], d["setup"], zones_at(frames[tf], at, tf)))
                    found = True
            if not found:
                zs = ", ".join(f"{z['kind']} {z['low']:g}-{z['high']:g}" for z in zones_at(frames[tf], at, tf)) or "geen"
                cards.append(f"<section><h2>{escape(r['coin'])} {r['direction']} {tf}: niet gezien · {escape(r['source'])}</h2><p>zones op dat moment: {escape(zs)}</p></section>")
    return cards


def random_cards(coins: list[str], n: int, years: float) -> list[str]:
    pool = []
    for coin in coins:
        frames = rs.build_frames(*(cc.ensure_candles(coin, years, timeframe=tf) for tf in ("15m", "1h", "4h")))
        for tf in rs.TFS:
            for family, entry, confirm in COMBOS:
                pool += [(coin, tf, family, s, frames[tf]) for s in rs.find_setups(frames, tf, family, entry, confirm, use_htf=True)[0]]
    random.Random(SEED).shuffle(pool)
    return [card(f"{k}. {coin} {s['direction']} · {tf} · {family} · {s['placed_at']:%Y-%m-%d %H:%M} UTC", fr, s, [])
            for k, (coin, tf, family, s, fr) in enumerate(pool[:n], 1)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv")
    ap.add_argument("--coins", default="BTC,ETH,SOL,ARB,APT,AAVE")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--jaren", type=float, default=1.0)
    ap.add_argument("--candles-map", help="map met {COIN}_{tf}.csv in plaats van de beurs, alleen voor --csv")
    ap.add_argument("--uit", default="/tmp/range_sweep_galerij.html")
    a = ap.parse_args()
    if a.csv:
        import misser_check
        fetch = misser_check.cache_fetch(a.candles_map) if a.candles_map else None
        cards = from_csv(a.csv, lambda coin, at: misser_check.fetch_rangesweep(coin, at, fetch=fetch))
    else:
        cards = random_cards(a.coins.split(","), a.n, a.jaren)
    Path(a.uit).write_text(page(cards), encoding="utf-8")
    print(f"{len(cards)} kaarten in {a.uit}")


if __name__ == "__main__":
    main()
