"""M3: placebo's voor afgeronde modeltrades zonder placebo (app/model_placebo.py). Draait elke nacht via scripts/nacht_export.py.

  .venv/bin/python3 scripts/model_placebo.py [--droog]

Alleen meting: niets in de app of de motor leest dit, behalve Bewijs en de nachtexport."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db, model, model_placebo as mp, outcome_measure, repo  # noqa: E402


def run(now: datetime, save: bool = True) -> int:
    done = 0
    for t in repo.model_placebo_due():
        start = pd.Timestamp(t["start_at"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = min(pd.Timestamp(now), start - mp.GAP + model.TIME_LIMIT + mp.STEP)
        try:
            candles = outcome_measure.candles_between(t["coin"], start - mp.WINDOW - mp.STEP, end)
        except Exception as exc:
            print(f"{t['coin']} {t['kind']}{t['ref_id']}: candles niet op te halen ({exc}), volgende nacht opnieuw")
            continue
        if not len(candles):
            continue
        rs = mp.placebo_rs(f"{t['kind']}:{t['ref_id']}", t["direction"], t["entry"], t["stop_loss"], t["take_profit"], start, candles)
        print(f"{t['coin']} {t['code']} {t['kind']}{t['ref_id']}: {len(rs)} placebo's, gemiddeld "
              + (f"{sum(rs) / len(rs):+.2f} R bruto" if rs else "–"))
        if save:
            repo.save_model_placebo(t["kind"], t["ref_id"], rs)
        done += 1
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--droog", action="store_true", help="alleen tonen, niets opslaan")
    a = ap.parse_args()
    db.init_db()
    n = run(datetime.now(timezone.utc), save=not a.droog)
    print(f"{n} trades bijgewerkt" + (" (niet opgeslagen)" if a.droog else ""))


if __name__ == "__main__":
    main()
