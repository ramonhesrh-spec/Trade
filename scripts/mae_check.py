"""Hoe ver gingen afgeronde trades van de focus-soorten eerst tegen je in (MAE) en met je mee (MFE)? Alleen-lezen: rekent achteraf op candles van de
beurs en schrijft niets. Draai op de VPS:
.venv/bin/python3 scripts/mae_check.py [--dagen 60] [--soort zone_radar]
Per soort: aantal gemeten trades, mediaan en 75e percentiel van de MAE van winnaars en verliezers, en hoeveel stops binnen 24 uur toch het doel
haalden. Regels in app/excursion.py, dezelfde als bij de uitkomst in level_check. Dit is meting, geen advies over waar een stop hoort."""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import exchange, excursion, focus, repo  # noqa: E402

# 5m-candles tot 1000 per keer: het venster van een signaal (hoogstens twee dagen) plus 24 uur na de stop past erin.
TIMEFRAME = "5m"
LIMIT = 1000


def _candles(coin: str, start: datetime):
    return exchange.fetch_ohlcv(coin, timeframe=TIMEFRAME, limit=LIMIT, since=int((start - timedelta(minutes=10)).timestamp() * 1000))


def _fmt(x) -> str:
    return "-" if x is None else f"{x:.2f}".replace(".", ",")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=60)
    ap.add_argument("--soort", choices=focus.FOCUS_TYPES)
    a = ap.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=a.dagen)).isoformat()
    types = (a.soort,) if a.soort else focus.FOCUS_TYPES
    rows = [r for r in repo.list_signals_for_quality_report(since)
            if r["trade_type"] in types and r["auto_outcome"] in ("take_profit", "stop_loss") and r.get("auto_outcome_at")]
    print(f"MAE en MFE van afgeronde trades, laatste {a.dagen} dagen, in R van de stopafstand. Alleen-lezen.\n")
    measured, failed = [], 0
    for r in rows:
        try:
            frame = _candles(r["coin"], excursion._ts(r["created_at"]).to_pydatetime())
            m = excursion.measure_row(r, frame)
        except Exception as exc:          # één coin zonder data mag de rest niet tegenhouden
            print(f"  signaal {r['id']} ({r['coin']}): geen candles ({exc})")
            failed += 1
            continue
        if m is None:
            failed += 1
            continue
        measured.append({**r, **m, "stored_mae": r.get("mae_r")})
        time.sleep(0.1)                   # zacht voor de beurs
    stats = excursion.stats(measured)
    print(f"{'soort':<14}{'n':>4}{'win':>5}{'MAE win med':>13}{'p75':>7}{'verl':>6}{'MAE verl med':>14}{'p75':>7}{'stop->doel 24u':>16}")
    for t in types:
        s = stats.get(t)
        if not s:
            print(f"{focus.label(t):<14}{0:>4}  nog geen afgeronde trades")
            continue
        later = f"{s['stops_then_target']} van {s['stops_checked']}" if s["stops_checked"] else "-"
        print(f"{focus.label(t)[:13]:<14}{s['n']:>4}{s['win_n']:>5}{_fmt(s['win_mae_med']):>13}{_fmt(s['win_mae_p75']):>7}"
              f"{s['loss_n']:>6}{_fmt(s['loss_mae_med']):>14}{_fmt(s['loss_mae_p75']):>7}{later:>16}")
    print(f"\n{len(measured)} trades gemeten, {failed} niet te meten. 'stop->doel 24u' telt alleen stops met een doel waarvan de 24 uur voorbij zijn.")
    stored = [m for m in measured if m["stored_mae"] is not None]
    diff = [m for m in stored if abs(m["mae_r"] - m["stored_mae"]) > 0.05]
    print(f"{len(stored)} hadden al een opgeslagen meting (bij de uitkomst); {len(diff)} daarvan wijken meer dan 0,05 R af"
          " (andere candles: 15m voor oude signalen, of de meting van de motor zelf).")


if __name__ == "__main__":
    main()
