"""Eenmalig opruimscript: herbeoordeelt elk signaal zonder vastgestelde
uitkomst op candle-hoog/laag SINDS het signaal ontstond, in plaats van de
oude losse live-prijs-poll die een kort duikje kon missen (zie het
DOGE/SMC-signaal 400: zes losse duikjes onder de stop, geen van de zes
viel samen met een poll-moment). Vult alleen een auto_outcome in als er
ECHT een candle is die stop of take raakte — laat de vervallen-na-1-dag
afhandeling aan de gewone periodieke check_signal_outcomes over, dit
script raakt alleen de hit-detectie zelf aan. Puur een correctie met
terugwerkende kracht, wijzigt verder niets aan het systeem.

Met --include-vervallen worden ook signalen herbeoordeeld die als 'vervallen' zijn afgesloten: een doel of stop dat geraakt werd terwijl de check
niet draaide, werd vroeger nooit gezien. Alleen een echt geraakte stop of doel overschrijft 'vervallen'.

Draai met: python3 scripts/backfill_signal_outcomes.py [--dry-run] [--include-vervallen]"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime  # noqa: E402

from app import db, exchange, repo  # noqa: E402
from app.level_check import (  # noqa: E402
    LEVEL_CHECK_CANDLE_TIMEFRAME, _level_hit_in_candles, candles_in_validity,
)

dry_run = "--dry-run" in sys.argv
include_expired = "--include-vervallen" in sys.argv


async def main() -> None:
    signals = repo.list_unresolved_signals_with_levels() + (repo.list_expired_signals_with_levels() if include_expired else [])
    print(f"{len(signals)} signalen zonder vastgestelde uitkomst om te herbeoordelen\n")

    fixed = 0
    tally = {"take_profit": 0, "stop_loss": 0}
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

        # Zelfde geldigheid als de live controle: een raak na het vervallen van het signaal telt niet.
        hit_result = _level_hit_in_candles(signal["direction"], signal["stop_loss"], signal["take_profit"], candles_in_validity(candles, signal["created_at"]))
        if hit_result is None:
            continue

        hit, hit_price, hit_at = hit_result
        outcome = "take_profit" if hit == "take profit" else "stop_loss"
        occurred_at = hit_at.isoformat()
        delay = hit_at - __import__("pandas").Timestamp(datetime.fromisoformat(signal["created_at"]))
        print(f"  signaal {signal['id']} ({coin}, {signal['direction']}): {outcome} op {hit_price} ({occurred_at}), {delay.total_seconds() / 3600:.1f} uur na het signaal")
        if not dry_run:
            repo.mark_signal_auto_outcome(signal["id"], outcome, occurred_at)
            if outcome == "stop_loss" and signal["nearest_sr_zone_price"] is not None:
                repo.record_sr_zone_failure(coin, signal["direction"], signal["nearest_sr_zone_price"], occurred_at)
        fixed += 1
        tally[outcome] += 1

    print(f"\nDaarvan {tally['take_profit']} doel en {tally['stop_loss']} stop")
    print(f"{fixed} signalen {'zouden' if dry_run else ''} gecorrigeerd {'worden' if dry_run else ''}".strip())


asyncio.run(main())
