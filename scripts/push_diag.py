"""Waarom kreeg ik geen melding? Alleen-lezen controle van het pushpad, in gewoon Nederlands.
Draai op de server: python3 scripts/push_diag.py
Toont per gebruiker abonnementen, pauze, stille uren, dagbudget en de laatste pushes en meldingen, daarna de open kansen met het oordeel van
push_policy.decide, de VAPID-instelling (nooit de sleutel zelf) en de laatste hartslagen van de motoren. Elke query staat apart in een try/except,
zodat een fout niet de rest verbergt. Er wordt niets geschreven en niets verstuurd."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, focus, push_policy, repo

NOW = datetime.now(timezone.utc)


def age_text(iso: Optional[str], now: datetime) -> str:
    if not iso:
        return "onbekend"
    try:
        at = datetime.fromisoformat(iso)
    except ValueError:
        return "onbekend"
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    minutes = int((now - at).total_seconds() // 60)
    if minutes < 0:
        return "in de toekomst"
    if minutes < 90:
        return f"{minutes} min geleden"
    if minutes < 48 * 60:
        return f"{minutes // 60} uur geleden"
    return f"{minutes // 1440} dagen geleden"


def verdict(user: dict, subs: int, recent: list[dict], coin: str, direction: str, vapid: bool, now: datetime) -> tuple[bool, str]:
    """Zelfde volgorde als push_notify.send_kans_push, plus de dingen die send_push daarna nog kan tegenhouden (VAPID, geen abonnement)."""
    left = push_policy.pause_minutes_left(user.get("push_paused_until"), now)
    if left:
        return False, f"pauze staat aan, nog {left} min (komt alleen als melding op de pagina)"
    ok, reason = push_policy.decide(recent, coin, direction, user.get("push_budget"), now)
    if not ok:
        return False, reason
    if not vapid:
        return False, "VAPID_PRIVATE_KEY ontbreekt op de server, send_push stuurt niets"
    if not subs:
        return False, "geen push-abonnement: de app is niet als melding-apparaat aangemeld"
    return True, "mag als push (bij stille uren stil, zonder geluid)"


def had_push(body: str) -> str:
    """Een geweerde kans krijgt een rustige melding met de reden erin (send_kans_push); zonder zo'n zin ging er een push uit."""
    return "nee (geen push)" if "geen push" in (body or "") else "ja of niet van toepassing"


def safe(label: str, fn, default=None):
    try:
        return fn()
    except Exception as exc:
        print(f"  [fout bij {label}: {type(exc).__name__}: {str(exc)[:120]}]")
        return default


def quiet_text(user: dict) -> str:
    from app import push_notify
    start, end = user.get("quiet_hours_start"), user.get("quiet_hours_end")
    if not start or not end:
        return "niet ingesteld"
    state = "NU stil" if push_notify.is_quiet_now(start, end) else "nu niet stil"
    return f"{start} tot {end} (Amsterdam), {state} (stil = wel push, zonder geluid)"


def focus_line(on: bool) -> str:
    if not on:
        return "ENGINE_FOCUS: uit (alle motoren volgen hun eigen vlag)"
    return (f"ENGINE_FOCUS: aan, nieuwe kansen alleen van {', '.join(focus.FOCUS_TYPES)}; de andere motoren staan {focus.OFF_DETAIL} "
            "(hartslag hieronder), hun open trades lopen door")


def open_chances(now: datetime) -> list[dict]:
    """Open kansen rechtstreeks uit de tabellen, zonder koers: genoeg om te zien wat er klaarstaat en of er al gemeld is."""
    out = []
    for s in safe("structuurplannen", lambda: repo.list_structure_setups(("waiting",), 50), []):
        expired = s.get("expires_at") and datetime.fromisoformat(s["expires_at"]) <= now
        out.append({"soort": "Structuur", "coin": s["coin"], "direction": s["direction"], "state": "verlopen" if expired else f"wacht, oordeel {s['grade'] or 'geen'}",
                    "at": s["created_at"], "flag": "aanmaak-push bij elk oordeel (A luid, B, C 'Zwak' en geen oordeel stil); bij het bereiken van de limiet volgt 'Structuur gevuld'",
                    "skip": bool(expired)})
    smc_off, script_off = not focus.engine_on("smc"), not focus.engine_on("script")
    for s in safe("smc-setups", repo.list_forming_smc_setups, []):
        out.append({"soort": "SMC-zone", "coin": s["coin"], "direction": s["direction"], "state": focus.OFF_DETAIL if smc_off else "bouwend", "at": s["created_at"],
                    "flag": f"zone gezet-push verstuurd: {'ja' if s['alert_sent'] else 'nee'}; in-de-zone-push verstuurd: {'ja' if s['zone_alert_sent'] else 'nee'}", "skip": smc_off})
    for sc in safe("scripts", repo.list_waiting_scenarios, []):
        out.append({"soort": "Markt-script", "coin": sc["coin"], "direction": sc["direction"], "state": focus.OFF_DETAIL if script_off else "wacht op voorwaarde",
                    "at": sc.get("created_at"), "flag": "push pas bij het afgaan van de voorwaarde", "skip": script_off})
    return out


def per_user(now: datetime, vapid: bool, chances: list[dict]) -> None:
    users = safe("gebruikers", repo.list_users, [])
    since = (now - timedelta(hours=24)).isoformat()
    for u in users:
        print(f"\n== Gebruiker {u['username']} (id {u['id']}) ==")
        subs = safe("abonnementen", lambda: repo.list_push_subscriptions(u["id"]), [])
        newest = max((s["created_at"] for s in subs), default=None)
        print(f"Push-abonnementen: {len(subs)}" + (f", nieuwste {age_text(newest, now)}" if subs else " (GEEN: dan komt er nooit een push aan)"))
        left = push_policy.pause_minutes_left(u.get("push_paused_until"), now)
        print(f"Pauze: {'AAN, nog ' + str(left) + ' min' if left else 'uit'} (push_paused_until={u.get('push_paused_until')})")
        print(f"Stille uren: {quiet_text(u)}")
        recent = safe("push_log", lambda: repo.list_recent_pushes(u["id"], since), [])
        limit = push_policy.DEFAULT_BUDGET if u.get("push_budget") is None else u["push_budget"]
        print(f"Dagbudget laatste 24 uur: {push_policy.used(recent)} van {limit if limit else 'onbeperkt'}" + ("  <-- OP, nieuwe kansen komen alleen als melding" if limit and push_policy.used(recent) >= limit else ""))
        for r in list(reversed(recent))[:10]:
            print(f"   push {r['at'][:16]}  {r['coin']} {r['direction']}  ({age_text(r['at'], now)})")
        notes = safe("meldingen", lambda: repo.list_notifications(u["id"], 10), [])
        print("Laatste 10 meldingen:")
        for n in notes:
            print(f"   {n['created_at'][:16]}  [{n['type']}] {n['title']}  -> push: {had_push(n['body'])}")
        if chances:
            print("Oordeel per open kans voor deze gebruiker:")
            for c in chances:
                ok, why = verdict(u, len(subs), recent, c["coin"], c["direction"], vapid, now)
                print(f"   {c['soort']} {c['coin']} {c['direction']}: {'JA' if ok else 'NEE'}, {why}")


def main() -> None:
    now = datetime.now(timezone.utc)
    print(f"HesPulse push-diagnose, {now.strftime('%Y-%m-%d %H:%M')} UTC, database {config.DATABASE_PATH}")
    vapid = bool(config.VAPID_PRIVATE_KEY)
    print(f"\nVAPID: privésleutel {'ingesteld' if vapid else 'ONTBREEKT (dan gaat er helemaal geen push uit)'}, publieke sleutel {'ingesteld' if config.VAPID_PUBLIC_KEY else 'ONTBREEKT'}")
    info = sorted(config.SIGNAL_TYPE_INFO_ONLY)
    print(f"SIGNAL_TYPE_INFO_ONLY: {', '.join(info) if info else 'leeg (niets alleen-informatie)'}")
    print(focus_line(config.ENGINE_FOCUS))
    chances = open_chances(now)
    print(f"\nOpen kansen: {len(chances)}")
    for c in chances:
        print(f" - {c['soort']} {c['coin']} {c['direction']}: {c['state']}, {age_text(c['at'], now)}; {c['flag']}")
    per_user(now, vapid, [c for c in chances if not c["skip"]])
    print("\n== Hartslagen van de motoren ==")
    def beats():
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT name, at, detail FROM engine_heartbeat ORDER BY name").fetchall()]
    for b in safe("hartslagen", beats, []):
        print(f"   {b['name']}: {age_text(b['at'], now)} ({b['detail']})")
    print("\nKijk ook in de logs:\n  journalctl -u crypto-bot -n 80 --no-pager\n  journalctl -u crypto-web -n 40 --no-pager")


if __name__ == "__main__":
    main()
