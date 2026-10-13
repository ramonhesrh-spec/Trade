"""In welke marktfase (balans of onbalans, uit een volumeprofiel van 1u) werd elke gemelde kans gemeld, en deed elke soort het per fase anders?
Draai op de VPS:   .venv/bin/python3 scripts/fase_check.py [--sinds 2026-08-01] [--coins BTC,ETH]
Alleen meten: er verandert niets aan meldingen of motoren. Telt alleen afgeronde take- of stopuitkomsten, netto R zoals Bewijs."""
import argparse
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, market_state, repo, structure_review, track_record  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402

YEARS = 0.5
MIN_N = 20
STATES = ["balans", "onbalans_op", "onbalans_neer"]


def avg(values):
    return sum(values) / len(values) if values else None


def fmt_r(values, star=False):
    if not values:
        return "-"
    return f"{avg(values):+.2f}" + ("*" if star and len(values) < MIN_N else "")


def collect(rows, coins, cost_pct, frame_for):
    """Geeft (metingen, aantal zonder candles). Een meting is (soort, richting, R, fase-dict)."""
    out, no_candles = [], 0
    for row in rows:
        if row.get("auto_outcome") not in ("take_profit", "stop_loss"):
            continue
        if coins and row["coin"].upper() not in coins:
            continue
        r = track_record.net_signal_r(row, cost_pct)
        if r is None:
            continue
        df = frame_for(row["coin"])
        phase = None
        if df is not None:
            before = market_state.closed_before(df, market_state.parse_time(row["created_at"]))
            phase = market_state.classify(before, row["direction"])
        if phase is None:
            no_candles += 1
            continue
        out.append((row.get("trade_type") or "onbekend", row["direction"], r, phase))
    return out, no_candles


def short_label(kind):
    return track_record.TYPE_LABELS.get(kind, kind).split(" (")[0][:14]


def report(meas, no_candles):
    lines = []
    add = lines.append
    add(f"Fase-check, {len(meas)} afgeronde kansen")
    add("")
    add("Per fase")
    add(f"{'fase':<14}{'n':>4}{'win%':>6}{'gem R':>7}  95%-interval")
    for s in STATES:
        rs = [m[2] for m in meas if m[3]["state"] == s]
        if not rs:
            add(f"{s:<14}{0:>4}")
            continue
        win = 100 * sum(r > 0 for r in rs) / len(rs)
        if len(rs) >= MIN_N:
            lo, hi = structure_review.bootstrap_mean(rs)
            ci = f"{lo:+.2f} tot {hi:+.2f}"
        else:
            ci = "-"
        add(f"{s:<14}{len(rs):>4}{win:>6.0f}{avg(rs):>+7.2f}  {ci}")

    cells = defaultdict(list)
    for kind, _, r, ph in meas:
        cells[(kind, ph["state"])].append(r)
    kinds = sorted({k for k, _ in cells}, key=lambda k: -sum(len(cells[(k, s)]) for s in STATES))
    add("")
    add("Per soort en fase: n / gem R  (* = n onder 20)")
    add(f"{'soort':<14}{'balans':>14}{'onb. op':>14}{'onb. neer':>14}")
    for k in kinds:
        cols = []
        for s in STATES:
            v = cells.get((k, s), [])
            cols.append(f"{len(v)} / {fmt_r(v, True)}" if v else "-")
        add(f"{short_label(k):<14}{cols[0]:>14}{cols[1]:>14}{cols[2]:>14}")

    add("")
    add("Met of tegen de onbalans")
    for rel in ("met", "tegen"):
        rs = [m[2] for m in meas if m[3]["relatie"] == rel]
        add(f"{rel:<8}n {len(rs):>4}   gem R {fmt_r(rs, True)}")

    add("")
    add("Premium en discount (alleen binnen het gebied)")
    for d, good in (("long", "discount"), ("short", "premium")):
        bad = "premium" if d == "long" else "discount"
        g = [m[2] for m in meas if m[1] == d and m[3]["positie"] == good]
        b = [m[2] for m in meas if m[1] == d and m[3]["positie"] == bad]
        add(f"{d} in {good} (goede kant): n {len(g)}, R {fmt_r(g, True)}")
        add(f"{d} in {bad}: n {len(b)}, R {fmt_r(b, True)}")

    n_cells = len(cells)
    add("")
    add("Let op")
    notes = [
        f"Er zijn {n_cells} vakjes soort x fase vergeleken. Bij zoveel vakjes zien er een paar bij toeval goed uit.",
        f"Het kleinste vakje heeft n {min(len(v) for v in cells.values()) if cells else 0}; "
        f"het grootste n {max(len(v) for v in cells.values()) if cells else 0}. Onder n {MIN_N} (*) valt niets te lezen.",
        f"Kansen zonder candles of zonder genoeg historie: {no_candles}.",
        "Dit beschrijft wat er gebeurde en bewijst geen oorzaak. Pas als een fase op nieuwe kansen standhoudt is een filter te overwegen.",
    ]
    for note in notes:
        lines.extend(textwrap.wrap(note, 58, initial_indent="- ", subsequent_indent="  "))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sinds", default=None, help="alleen signalen gemeld vanaf deze datum (YYYY-MM-DD)")
    ap.add_argument("--coins", default=None, help="kommalijst, bijvoorbeeld BTC,ETH")
    a = ap.parse_args()
    coins = {c.strip().upper() for c in a.coins.split(",") if c.strip()} if a.coins else None

    cache = {}

    def frame_for(coin):
        if coin not in cache:
            try:
                cache[coin] = candle_cache.ensure_candles(coin, YEARS, timeframe="1h")
            except Exception as exc:
                print(f"(geen candles voor {coin}: {exc})", file=sys.stderr)
                cache[coin] = None
        return cache[coin]

    rows = repo.list_signals_for_quality_report(a.sinds)
    meas, no_candles = collect(rows, coins, config.TRACK_RECORD_COST_PCT, frame_for)
    print(report(meas, no_candles))


if __name__ == "__main__":
    main()
