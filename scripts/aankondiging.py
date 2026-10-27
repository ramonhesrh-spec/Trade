"""Het moment van de aankondiging zetten, zonder herstart: /nieuw telt ernaartoe af, daarna ziet elke gebruiker één keer het verhaal "Wat is
nieuw" en gaat er één pushmelding uit (in de 5-minutencyclus, app/announce_live.py).

    python3 scripts/aankondiging.py --zet 2026-11-02T18:00   # Amsterdamse tijd, bewaard als UTC
    python3 scripts/aankondiging.py --toon
    python3 scripts/aankondiging.py --wis                    # ook ANNOUNCEMENT_AT uit .env telt dan niet meer
    python3 scripts/aankondiging.py --test-push              # alleen naar de eigenaar, de echte push blijft staan
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import announce, db, push_notify, repo  # noqa: E402


def _show() -> None:
    at = repo.get_announcement_at()
    if at is None:
        print("Geen aankondiging gezet: /nieuw toont de live-versie, het verhaal opent niet vanzelf en er gaat geen push uit.")
        return
    now = datetime.now(timezone.utc)
    left = announce.remaining(at, now)
    print(f"Aankondiging: {announce.fmt_local(at)} (Amsterdam), {at.isoformat()} UTC")
    if announce.phase(at, now) == "before":
        print(f"Nog {left['days']}d {left['hours']}u {left['minutes']}m {left['seconds']}s")
    else:
        print("Het moment is voorbij: /nieuw staat op live.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Moment van de aankondiging op /nieuw")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--zet", metavar="JJJJ-MM-DDTUU:MM", help="lokale tijd Europe/Amsterdam")
    g.add_argument("--toon", action="store_true")
    g.add_argument("--wis", action="store_true")
    g.add_argument("--test-push", action="store_true", help="stuurt de push alleen naar de eigenaar")
    args = p.parse_args(argv)
    db.init_db()

    if args.zet:
        at = announce.parse_moment(args.zet)
        if at is None:
            print(f"Ongeldige tijd: {args.zet!r}. Gebruik bijvoorbeeld 2026-11-02T18:00.")
            return 2
        repo.set_announcement_at(at)
        _show()
    elif args.wis:
        repo.clear_announcement_at()
        print("Aankondiging gewist.")
    elif args.test_push:
        owner = repo.get_ceo_user()
        if not owner:
            print("Geen eigenaar gevonden.")
            return 1
        asyncio.run(push_notify.send_push(owner["id"], announce.PUSH_TITLE, announce.PUSH_BODY, announce.PUSH_URL, tag="aankondiging-test"))
        print(f"Testpush naar {owner['username']} verstuurd (als er een abonnement is).")
    else:
        _show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
