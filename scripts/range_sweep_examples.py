"""Concept voor de handtrades-CSV uit de opgeslagen berichten op de VPS. Draai daar:

  .venv/bin/python3 scripts/range_sweep_examples.py --zoek "range,liq,order block,Cos867" --dagen 60 > data/misser/range_sweep_concept.csv

De gebruiker vult stop, doel, uitkomst en tf aan en voegt de regels toe aan docs/onderzoek/range-sweep/handtrades.csv. Het script schrijft niets in de database."""
import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, misser  # noqa: E402

FIELDS = ["coin", "richting", "tijd", "instap", "stop", "doel", "uitkomst", "bron", "notitie", "tf"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zoek", default="range,liq,order block,ob,sweep")
    ap.add_argument("--dagen", type=int, default=60)
    a = ap.parse_args()
    words = [w.strip().lower() for w in a.zoek.split(",") if w.strip()]
    since = (datetime.now(timezone.utc) - timedelta(days=a.dagen)).isoformat()
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, received_at, raw_text, coin, direction FROM messages WHERE received_at >= ? ORDER BY received_at", (since,))]
    hits = [r for r in rows if any(w in (r["raw_text"] or "").lower() for w in words)]
    drafts = misser.draft_rows(hits)
    out = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    out.writeheader()
    for d in drafts:
        out.writerow({**{k: "" for k in FIELDS}, **d})
    print(f"{len(hits)} berichten gevonden, {len(drafts)} met coin en kant", file=sys.stderr)


if __name__ == "__main__":
    main()
