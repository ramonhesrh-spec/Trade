"""Schaduwvarianten beheren (app/shadow.py). Elke variant ligt vooraf vast in het register, met reden; hoogstens één actieve schaduw per soort.

  .venv/bin/python3 scripts/schaduw.py --lijst
  .venv/bin/python3 scripts/schaduw.py --nieuw zr-stop-040 --soort zone_radar --param stop_atr=0.4 \\
        --beschrijving "Stop 0,4 ATR voorbij de zone" --reden "lek 30d: 9 van 21 stops haalden binnen 24 uur toch het doel"
  .venv/bin/python3 scripts/schaduw.py --promoveer zr-stop-040     (zet de waarde in de overlay die de motor leest, push naar de CEO)
  .venv/bin/python3 scripts/schaduw.py --terug zr-stop-040         (haalt de overlay weg)
  .venv/bin/python3 scripts/schaduw.py --auto                      (voert alle verdicts uit volgens de vaste regel; de nachtelijke timer)

Promoveren met de hand slaat de regel niet over: --promoveer weigert zolang het verdict geen 'promoveren' is, tenzij --toch."""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, focus, push_notify, repo, shadow  # noqa: E402


def _push_ceo(title: str, body: str) -> None:
    for uid in repo.list_ceo_user_ids():
        try:
            asyncio.run(push_notify.send_push(uid, title, body, "/bewijs#tab-soort", tag="schaduw"))
        except Exception as exc:                  # de overlay staat; een mislukte push mag dat niet terugdraaien
            print(f"Push naar de CEO mislukt: {exc}")


def promote(variant_id: str, now: datetime, force: bool = False) -> dict:
    variant = repo.get_shadow_variant(variant_id)
    if variant is None or variant["status"] != "schaduw":
        raise SystemExit(f"{variant_id}: geen actieve schaduw")
    v = shadow.verdict(repo.list_shadow_results(variant_id))
    if v["verdict"] != "promoveren" and not force:
        raise SystemExit(f"{variant_id}: verdict is {v['verdict']} ({v['reden']}); promoveren alleen volgens de regel (of --toch)")
    base = shadow.live_params(variant["trade_type"])
    text = shadow.promote_text(variant, v, base)
    repo.promote_shadow(variant_id, variant["trade_type"], json.loads(variant["params"]), now.isoformat(), text)
    _push_ceo(f"{focus.label(variant['trade_type'])}: schaduw gepromoveerd", text)
    print(text)
    return v


def revert(variant_id: str, now: datetime) -> None:
    variant = repo.get_shadow_variant(variant_id)
    if variant is None or variant["status"] != "gepromoveerd":
        raise SystemExit(f"{variant_id}: niet gepromoveerd, niets terug te draaien")
    n = repo.revert_shadow(variant_id, now.isoformat(), f"teruggedraaid op {now:%Y-%m-%d %H:%M} UTC")
    text = f"{focus.label(variant['trade_type'])}: {variant['description']} teruggedraaid, de motor gebruikt weer de vorige waarde."
    _push_ceo(f"{focus.label(variant['trade_type'])}: schaduw teruggedraaid", text)
    print(f"{text} ({n} parameter{'s' if n != 1 else ''})")


def auto(now: datetime) -> dict:
    """Eerst de nieuwe varianten uit shadow.SEEDS vastleggen, dan elk actief verdict uitvoeren: promoveren of afvallen; wachten laat de schaduw
    staan. Geeft {id: verdict}."""
    done = {}
    for variant_id in shadow.seed(now):
        print(f"{variant_id}: vastgelegd uit shadow.SEEDS")
    for variant in repo.list_shadow_variants(("schaduw",)):
        v = shadow.verdict(repo.list_shadow_results(variant["id"]))
        done[variant["id"]] = v["verdict"]
        if v["verdict"] == "promoveren":
            promote(variant["id"], now)
        elif v["verdict"] == "afvallen":
            repo.set_shadow_status(variant["id"], "afgevallen", now.isoformat(), v["reden"])
            print(f"{variant['id']}: afgevallen ({v['reden']})")
        else:
            print(f"{variant['id']}: wachten ({v['reden']}; variant {v['n_variant']}, hoofd {v['n_hoofd']} afgerond)")
    return done


def _param(raw: str) -> tuple[str, float]:
    name, _, value = raw.partition("=")
    return name.strip(), float(value.replace(",", "."))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--lijst", action="store_true")
    g.add_argument("--nieuw", metavar="ID")
    g.add_argument("--promoveer", metavar="ID")
    g.add_argument("--terug", metavar="ID")
    g.add_argument("--auto", action="store_true")
    ap.add_argument("--soort", choices=shadow.TRADE_TYPES)
    ap.add_argument("--param", action="append", default=[], help="naam=waarde, bijvoorbeeld stop_atr=0.4 (mag vaker)")
    ap.add_argument("--beschrijving", default="")
    ap.add_argument("--reden", default="")
    ap.add_argument("--toch", action="store_true", help="met --promoveer: ook zonder verdict 'promoveren' (alleen op uitdrukkelijk verzoek)")
    a = ap.parse_args()
    db.init_db()
    now = datetime.now(timezone.utc)
    if a.nieuw:
        if not a.soort:
            ap.error("--nieuw vraagt --soort")
        try:
            shadow.register(a.nieuw, a.soort, a.beschrijving, a.reden, dict(_param(p) for p in a.param), now)
        except ValueError as exc:
            sys.exit(str(exc))
        print(f"{a.nieuw} vastgelegd voor {a.soort}: {a.param}")
    elif a.promoveer:
        promote(a.promoveer, now, force=a.toch)
    elif a.terug:
        revert(a.terug, now)
    elif a.auto:
        auto(now)
    else:
        for variant in repo.list_shadow_variants(shadow.STATUSES):
            v = shadow.verdict(repo.list_shadow_results(variant["id"]))
            print(f"{variant['id']} [{variant['status']}] {variant['trade_type']} {variant['params']}: {v['verdict']} "
                  f"(variant {v['n_variant']}, hoofd {v['n_hoofd']}; {v['reden']})")
        for t in shadow.TRADE_TYPES:
            print(f"{t}: {shadow.live_params(t)}")


if __name__ == "__main__":
    main()
