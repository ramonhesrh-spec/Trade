"""Eenmalig: zet bestaande, nog verse bron-niveaus (support/resistance uit
een screenshot) die nog geen swing_watches-regel hebben, alsnog om in een
wachtende watch. Voor niveaus van vóór deze feature bestond, zodat een nog
relevante analyse niet voorgoed onbewaakt blijft.

Maakt nooit direct een "bevestigde" watch aan, ook niet als de prijs
toevallig al dichtbij staat op het moment van draaien: de eerstvolgende
periodieke check (level_check.check_swing_watches) pakt dat vanzelf op.

Draai met: python3 scripts/backfill_swing_watches.py [--days 84]
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, repo

DEFAULT_LOOKBACK_DAYS = 84  # zelfde als signal_processor.SWING_WATCH_MAX_AGE_DAYS


def main(days: int) -> None:
    db.init_db()
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    levels = repo.list_recent_source_levels_without_watch(since_iso)

    print(f"{len(levels)} bron-niveaus van de laatste {days} dagen zonder watch gevonden.")
    created = 0
    for lvl in levels:
        # create_swing_watch is idempotent op coin+richting: bij twee niveaus
        # voor dezelfde coin+richting (bv. twee berichten over dezelfde zone)
        # verwijst de tweede aanroep terug naar de eerst aangemaakte watch in
        # plaats van een dubbele te maken. source_level_id vergelijken laat
        # zien of DIT niveau de watch heeft aangemaakt, of alleen doorverwezen is.
        watch_id = repo.create_swing_watch(lvl["message_id"], lvl["source_level_id"], lvl["coin"], lvl["direction"])
        watch = repo.get_swing_watch(watch_id)
        if watch["source_level_id"] == lvl["source_level_id"]:
            created += 1
            print(f"  watch aangemaakt: {lvl['coin']} {lvl['direction']} @ {lvl['price_level']} "
                  f"({lvl['pattern_name'] or 'geen patroonnaam'})")
        else:
            print(f"  overgeslagen, al een wachtende watch voor {lvl['coin']} {lvl['direction']}: "
                  f"{lvl['coin']} {lvl['direction']} @ {lvl['price_level']} "
                  f"({lvl['pattern_name'] or 'geen patroonnaam'})")

    print(f"\nKlaar: {created} nieuwe watches aangemaakt van de {len(levels)} gevonden niveaus, "
          f"allemaal status 'wachtend' ({len(levels) - created} verwezen naar een al bestaande watch).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                         help="Hoeveel dagen terug te kijken (standaard: 84, zelfde als het verval van een watch)")
    args = parser.parse_args()
    main(args.days)
