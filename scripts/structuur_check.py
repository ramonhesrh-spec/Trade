"""Komen er minder of slechtere Structuur-kansen? Alleen-lezen, via repo. Draai op de VPS:
.venv/bin/python3 scripts/structuur_check.py [--dagen 10]
Per dag: breuken (en daarvan 'h.bodem': hogere bodem of lagere top met breuk van de laatste top of bodem), plannen, gemeld (luide melding), gevuld, en van de gevulde doel, stop of nog open; 'cap' is een kans die door de volle
dagcap (STRUCTURE_MAX_ALERTS_PER_DAY) niet gemeld werd, 'vast' een plan dat ontdekt maar nooit gemeld of gehouden werd. Daaronder de hartslag
van de motor (hoeveel van de FIXED_COINS de laatste run echt bekeek) en welke coins de meeste en geen enkele plannen kregen (7 dagen).
Begrippen en telling: app/structure_report.py."""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, focus, repo, structure_report as sr  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=10)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    rows = repo.list_structure_report_rows((now - timedelta(days=max(a.dagen, 7) + 1)).isoformat())
    print(f"Structuur, laatste {a.dagen} dagen (Nederlandse tijd). Dagcap {config.STRUCTURE_MAX_ALERTS_PER_DAY} meldingen per 24 uur.\n")
    print(f"{'dag':<12}{'breuken':>8}{'h.bodem':>8}{'plannen':>8}{'gemeld':>8}{'gevuld':>8}{'doel':>6}{'stop':>6}{'open':>6}{'cap':>5}{'vast':>6}")
    days = sr.daily(rows, now, a.dagen)
    for d in days:
        print(f"{d['date']:<12}{d['breuken']:>8}{d['choch']:>8}{d['plannen']:>8}{d['gemeld']:>8}{d['gevuld']:>8}{d['doel']:>6}{d['stop']:>6}{d['open']:>6}"
              f"{d['niet_gemeld']:>5}{d['vast']:>6}")
    hit = [d["date"] for d in days if d["cap_hit"]]
    print(f"\nDagcap geraakt op: {', '.join(hit) if hit else 'geen enkele dag'}")
    stuck = sum(d["vast"] for d in days)
    if stuck:
        print(f"Let op: {stuck} plan(nen) bleven hangen in 'oordeel' (ontdekt, nooit gemeld). Een run brak af tussen ontdekken en melden.")

    b = sr.beat_view(repo.get_beat("structuur"), len(config.FIXED_COINS), now)
    print("\nHartslag 'structuur':")
    if b["minutes"] is None:
        print("  nog nooit gedraaid")
    else:
        print(f"  laatste run {b['minutes']} minuten geleden: {b['detail']}")
        if b["off"]:
            print(f"  de motor staat uit ({focus.OFF_DETAIL})")
        elif b["all"]:
            print(f"  alle {b['total']} FIXED_COINS bekeken")
        else:
            seen = "onbekend aantal" if b["checked"] is None else f"{b['checked']} van {b['total']}"
            print(f"  niet alle FIXED_COINS bekeken: {seen}")
        if b["minutes"] > 15:
            print("  ouder dan 15 minuten: controleer crypto-market-scan-smc.timer (een run die langer dan 5 minuten duurt slaat de volgende over)")

    coins = sorted(c["symbol"] for c in repo.list_coins() if c["symbol"] in config.FIXED_COINS)
    most, none = sr.coin_counts(rows, coins, now, 7)
    print("\nPlannen per coin, laatste 7 dagen (meeste eerst):")
    print("  " + (", ".join(f"{c} {n}" for c, n in most[:12]) or "geen"))
    print(f"Zonder enig plan: {', '.join(none) or 'geen'}")


if __name__ == "__main__":
    main()
