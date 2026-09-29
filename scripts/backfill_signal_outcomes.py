"""Eenmalig opruimscript: herbeoordeelt elk signaal zonder vastgestelde
uitkomst op candle-hoog/laag SINDS het signaal ontstond, in plaats van de
oude losse live-prijs-poll die een kort duikje kon missen (zie het
DOGE/SMC-signaal 400: zes losse duikjes onder de stop, geen van de zes
viel samen met een poll-moment). Vult alleen een auto_outcome in als er
ECHT een candle is die stop of take raakte — laat de vervallen-na-1-dag
afhandeling aan de gewone periodieke check_signal_outcomes over, dit
script raakt alleen de hit-detectie zelf aan. Puur een correctie met
terugwerkende kracht, wijzigt verder niets aan het systeem.

Draai met: python3 scripts/backfill_signal_outcomes.py [--dry-run]"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime  # noqa: E402

from app import db, exchange, repo  # noqa: E402
from app.level_check import (  # noqa: E402
    LEVEL_CHECK_CANDLE_TIMEFRAME, _level_hit_in_candles,
)

dry_run = "--dry-run" in sys.argv


async def main() -> None:
    signals = repo.list_unresolved_signals_with_levels()
    print(f"{len(signals)} signalen zonder vastgestelde uitkomst om te herbeoordelen\n")

    fixed = 0
    for signal in signals:
        coin = signal["coin"]
        since_ms = int(datetime.fromisoformat(signal["created_at"]).timestamp() * 1000)
        try:
            candles = await asyncio.to_thread(
                exchange.fetch_ohlcv, coin, timeframe=LEVEL_CHECK_CANDLE_TIMEFRAME, since=since_ms, limit=1000,
            )
        except Exception as exc:
            print(f"  signaal {signal['id']} ({coin}): kon geen candles ophalen, overgeslagen ({exc})")
            continue

        hit_result = _level_hit_in_candles(signal["direction"], signal["stop_loss"], signal["take_profit"], candles)
        if hit_result is None:
            continue

        hit, hit_price, hit_at = hit_result
        outcome = "take_profit" if hit == "take profit" else "stop_loss"
        occurred_at = hit_at.isoformat()
        print(f"  signaal {signal['id']} ({coin}, {signal['direction']}): {outcome} op {hit_price} ({occurred_at})")
        if not dry_run:
            repo.mark_signal_auto_outcome(signal["id"], outcome, occurred_at)
            if outcome == "stop_loss" and signal["nearest_sr_zone_price"] is not None:
                repo.record_sr_zone_failure(coin, signal["direction"], signal["nearest_sr_zone_price"], occurred_at)
        fixed += 1

    print(f"\n{fixed} signalen {'zouden' if dry_run else ''} gecorrigeerd {'worden' if dry_run else ''}".strip())


asyncio.run(main())
