"""Krijgt elke coin wel kansen en meldingen? Alleen-lezen, per gevolgde coin over de laatste dagen. Draai op de VPS:
.venv/bin/python3 scripts/coin_dekking.py [--dagen 7]
Kolommen: zone-radar-kaarten (en hoeveel een melding kregen), Structuur-plannen, signalen, en pushes die de eigenaar echt kreeg (push_log).
Een coin met kaarten of plannen maar zonder pushes valt door het dagbudget, de conflictregel, de dagcap of de pauze. Een coin zonder kaarten
heeft geen zone binnen de afstand of geen doel van minstens 2R."""
import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import repo  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=7)
    a = ap.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=a.dagen)).isoformat()
    coins = sorted(c["symbol"] for c in repo.list_coins())
    zr = [z for z in repo.list_zone_radar_setups(("waiting", "filled", "doel_geraakt", "zone_weg", "expired")) if z["created_at"] >= since]
    zr_alert = Counter(z["coin"] for z in zr if z.get("alert_sent"))
    zr_all = Counter(z["coin"] for z in zr)
    st = Counter(s["coin"] for s in repo.list_structure_setups(("waiting", "fired", "expired", "invalid", "closed"), 1000) if s["created_at"] >= since)
    sig = Counter(r["coin"] for r in repo.list_signals_for_quality_report(since))
    owner = repo.get_ceo_user()
    pushes = Counter(p["coin"] for p in repo.list_recent_pushes(owner["id"], since)) if owner else Counter()
    print(f"Laatste {a.dagen} dagen, {len(coins)} coins. Pushes van gebruiker {owner['username'] if owner else '-'}.\n")
    print(f"{'coin':<8}{'zone-kaarten':>13}{'met melding':>13}{'structuur':>11}{'signalen':>10}{'pushes':>8}")
    for c in sorted(coins, key=lambda c: (pushes[c], zr_all[c] + st[c])):
        print(f"{c:<8}{zr_all[c]:>13}{zr_alert[c]:>13}{st[c]:>11}{sig[c]:>10}{pushes[c]:>8}")
    print(f"\nZonder enige kaart of plan: {', '.join(c for c in coins if not zr_all[c] and not st[c]) or 'geen'}")
    print(f"Met kaarten maar zonder push: {', '.join(c for c in coins if (zr_all[c] or st[c]) and not pushes[c]) or 'geen'}")


if __name__ == "__main__":
    main()
