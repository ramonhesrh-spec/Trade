"""Eenmalig alsnog een klare-taal samenvatting genereren voor berichten die
al verwerkt waren voor de prompt van explain.summarize_message verbeterd
werd. De eerste versie van die prompt liet het model vaak te dicht bij de
letterlijke tekst blijven (voelde aan als kopiëren/plakken) en had een te
krappe max_tokens (200), waardoor een zin soms halverwege afbrak in plaats
van een nette samenvatting. Draai dit één keer na de fix.

Draai met: python3 scripts/regenerate_message_summaries.py [--limit 50]

Kost tijd en Anthropic-calls: één call per bericht, met een korte pauze
ertussen om de API niet in één keer te bestoken.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, explain, repo

SLEEP_BETWEEN_CALLS_SECONDS = 1.0


def main(limit: int | None) -> None:
    db.init_db()
    messages = repo.list_messages_for_summary_backfill()
    if limit:
        messages = messages[:limit]

    print(f"{len(messages)} berichten om opnieuw samen te vatten.")
    updated = 0
    failed = 0
    for i, msg in enumerate(messages, start=1):
        summary = explain.summarize_message(msg["coin"] or "", msg["raw_text"])
        if summary:
            repo.set_message_summary(msg["id"], summary)
            updated += 1
            print(f"[{i}/{len(messages)}] bericht {msg['id']} ({msg['coin']}): OK")
        else:
            failed += 1
            print(f"[{i}/{len(messages)}] bericht {msg['id']} ({msg['coin']}): mislukt, overgeslagen")
        time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)

    print(f"\nKlaar: {updated} bijgewerkt, {failed} mislukt van de {len(messages)} berichten.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Maximaal aantal berichten (standaard: alle)")
    args = parser.parse_args()
    main(args.limit)
