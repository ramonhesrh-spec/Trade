"""Controle van het SMC-meetraam: speelt een periode af en vergelijkt met de
echte SMC-signalen uit de database. Alleen lezen.

Een live signaal geldt als teruggevonden als de replay voor dezelfde coin en
richting binnen 15 minuten een signaal had en de stop van dat replay-signaal
binnen 0,5% van de live stop ligt. Criterium: minstens 70% teruggevonden.
Alleen trade_type = 'smc', geen oefensignalen.

Draai met: python3 scripts/replay_smc_compare_live.py --since 2026-09-01 --until 2026-10-04T10:00
--until is exclusief. --refresh haalt de 1m-candles opnieuw op (nodig als de cache
vóór --until eindigt).

Op de VPS staat de echte database niet in de dev-kloon: wijs hem aan met
DATABASE_PATH, anders stopt het script (er wordt geen lege database aangemaakt):
DATABASE_PATH=/opt/crypto-alerts/data/trading.db /opt/crypto-alerts/.venv/bin/python3 \
    scripts/replay_smc_compare_live.py --since 2026-09-01 --until 2026-10-04T10:00"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db  # noqa: E402
from app.replay import candles, smc_engine, smc_report  # noqa: E402

PASS_RATIO = 0.7
MATCH_WINDOW = pd.Timedelta(minutes=15)
STOP_TOLERANCE = 0.005
STEP_MINUTES = 5
OFFSET_MINUTES = 3


def _utc(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def matches(live: dict, replayed: list) -> bool:
    return any(
        s.coin == live["coin"] and s.direction == live["direction"] and abs(s.at - live["at"]) <= MATCH_WINDOW
        and live["stop"] and abs(s.stop - live["stop"]) / abs(live["stop"]) <= STOP_TOLERANCE
        for s in replayed
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--coins", default=",".join(config.FIXED_COINS))
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    start, end = _utc(a.since), _utc(a.until)
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]

    db_file = Path(config.DATABASE_PATH)
    if not db_file.exists():
        sys.exit(f"Database {db_file} bestaat niet. Zet DATABASE_PATH naar de echte database "
                 "(op de VPS: DATABASE_PATH=/opt/crypto-alerts/data/trading.db).")
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'signals'").fetchone() is None:
            sys.exit(f"Database {db_file} heeft geen tabel 'signals'. Zet DATABASE_PATH naar de echte database "
                     "(op de VPS: DATABASE_PATH=/opt/crypto-alerts/data/trading.db).")
        live = conn.execute(
            """SELECT id, coin, direction, created_at, price, stop_loss, take_profit FROM signals
               WHERE trade_type = 'smc' AND is_practice = 0 AND created_at >= ? AND created_at < ?
               ORDER BY created_at""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    live_rows = [
        {"id": r["id"], "coin": r["coin"], "direction": r["direction"], "at": _utc(r["created_at"]),
         "entry": r["price"], "stop": r["stop_loss"]}
        for r in live if r["coin"] in coins
    ]
    if not live_rows:
        print("GEEN LIVE SIGNALEN, niet te beoordelen")
        return

    base = {}
    for c in sorted({r["coin"] for r in live_rows}):
        print(f"{c}: 1m-candles laden...", flush=True)
        base[c] = candles.ensure_candles(c, 1.1, refresh=a.refresh, timeframe="1m")
    cache_end = min(df["timestamp"].iloc[-1] for df in base.values())
    if not smc_report.cache_covers_until(cache_end, end):
        sys.exit(f"De 1m-candle-cache eindigt op {cache_end:%Y-%m-%d %H:%M}, dat is vóór --until ({end:%Y-%m-%d %H:%M}). "
                 "Draai opnieuw met --refresh (of kies een eerdere --until); er is geen oordeel gegeven.")

    try:
        first = smc_report.first_step(start, STEP_MINUTES, OFFSET_MINUTES)
    except ValueError as e:
        sys.exit(str(e))
    replayed = []
    for c, frame in base.items():
        # Vanaf een dag eerder beginnen geeft setups de tijd om op te bouwen, zoals live al gebeurd was.
        warm = smc_report.first_step(first - pd.Timedelta(days=1), STEP_MINUTES, OFFSET_MINUTES)
        book = smc_engine.SmcBook()
        sigs = smc_engine.replay_smc(c, {c: frame}, frame, warm, end - pd.Timedelta(minutes=1), pd.Timedelta(minutes=STEP_MINUTES), book=book)
        replayed += [s for s in sigs if s.at >= start - MATCH_WINDOW]
        print(f"{c}: {len(sigs)} replay-signalen", flush=True)

    found = [r for r in live_rows if matches(r, replayed)]
    replay_only = [s for s in replayed if start <= s.at < end and not any(
        r["coin"] == s.coin and r["direction"] == s.direction and abs(s.at - r["at"]) <= MATCH_WINDOW for r in live_rows)]
    ratio = len(found) / len(live_rows)
    print(f"\nLive SMC-signalen: {len(live_rows)}, terug in replay: {len(found)}")
    if len(live) != len(live_rows):
        print(f"Buiten de gekozen coins gelaten: {len(live) - len(live_rows)} live signalen")
    print(f"Replay-signalen zonder live signaal: {len(replay_only)}")
    print(f"Dekking live in replay: {ratio:.0%} (criterium {PASS_RATIO:.0%})")
    print("\nLive en NIET teruggevonden:")
    for r in live_rows:
        if r not in found:
            print(f"  #{r['id']} {r['coin']} {r['direction']} {r['at']:%Y-%m-%d %H:%M}")
    if ratio >= PASS_RATIO:
        print("\nRESULTAAT: GESLAAGD")
    else:
        print("\nRESULTAAT: NIET GESLAAGD, het raam klopt nog niet")
        sys.exit(1)


if __name__ == "__main__":
    main()
