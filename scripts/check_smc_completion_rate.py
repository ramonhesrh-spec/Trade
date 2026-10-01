"""Eenmalige check: hoe vaak wordt een "bouwende" SMC-setup een echt
signaal, en hoe vaak loopt hij dood (vervallen zonder afwijzing, of
nooit afgewezen binnen SMC_SETUP_MAX_AGE_HOURS)?

Draai met: python3 scripts/check_smc_completion_rate.py
Alleen SELECT-queries, raakt de database niet aan.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db


def main() -> None:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, created_at, updated_at, signal_id, invalidated_at
               FROM smc_setups ORDER BY created_at"""
        ).fetchall()

    total = len(rows)
    completed = [r for r in rows if r["signal_id"] is not None]
    invalidated_only = [r for r in rows if r["signal_id"] is None and r["invalidated_at"] is not None]
    still_building = [r for r in rows if r["signal_id"] is None and r["invalidated_at"] is None]

    print(f"Totaal aantal SMC-setups ooit aangemaakt: {total}")
    print(f"  Geworden tot een echt signaal: {len(completed)} ({len(completed)/total*100:.0f}%)" if total else "")
    print(f"  Vervallen zonder ooit afgewezen te zijn: {len(invalidated_only)} ({len(invalidated_only)/total*100:.0f}%)" if total else "")
    print(f"  Nu nog bouwend: {len(still_building)} ({len(still_building)/total*100:.0f}%)" if total else "")

    if still_building:
        now = datetime.now(timezone.utc)
        print("\nNog bouwende setups, met leeftijd:")
        for r in still_building:
            age_hours = (now - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600
            print(f"  {r['coin']:10s} {r['direction']:5s}  {age_hours:5.1f} uur oud  (id {r['id']})")

    # Eerste helft vs tweede helft van alle ooit aangemaakte setups (ruwe
    # tijdsvergelijking, geen harde knip op een specifieke commit-datum):
    # is de voltooiingsrate recent anders dan in het begin?
    if total >= 10:
        half = total // 2
        first_half, second_half = rows[:half], rows[half:]
        for label, chunk in [("Eerste helft (oudste)", first_half), ("Tweede helft (nieuwste)", second_half)]:
            done = sum(1 for r in chunk if r["signal_id"] is not None)
            print(f"\n{label}: {len(chunk)} setups, {done} voltooid ({done/len(chunk)*100:.0f}%)")


if __name__ == "__main__":
    main()
