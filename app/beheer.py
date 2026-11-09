"""Beheer voor de eigenaar (fase 2, R6): pure functies voor volg-sets, uitnodigingscodes en de leerlingenlijst. Geen database."""
import random
import re
from datetime import datetime
from typing import Optional

from app import logbook

COIN = re.compile(r"^[A-Z0-9]{2,12}$")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"      # zonder O, 0, I, 1 en L: een code wordt overgetypt
CODE_PREFIX = "HES-"


def parse_coins(text: str) -> list[str]:
    out = []
    for raw in re.split(r"[\s,;]+", (text or "").upper()):
        if COIN.match(raw) and raw not in out:
            out.append(raw)
    return out


def new_code(rnd: Optional[random.Random] = None) -> str:
    rnd = rnd or random.SystemRandom()
    return CODE_PREFIX + "".join(rnd.choice(CODE_ALPHABET) for _ in range(4))


def normalize_code(text: str) -> str:
    return (text or "").strip().upper()


def invite_usable(invite: dict, now: datetime) -> bool:
    return invite["uses"] < invite["max_uses"] and logbook._parse(invite["expires_at"]) > now


def _left(expires_at: str, now: datetime) -> str:
    seconds = (logbook._parse(expires_at) - now).total_seconds()
    if seconds >= 86400:
        return f"{int(seconds // 86400)} d"
    if seconds >= 3600:
        return f"{int(seconds // 3600)} u"
    return f"{max(1, int(seconds // 60))} min"


def invite_line(invite: dict, now: datetime) -> str:
    used = f"{invite['uses']} van {invite['max_uses']} gebruikt"
    if invite["uses"] >= invite["max_uses"]:
        state = "op"
    elif logbook._parse(invite["expires_at"]) <= now:
        state = "verlopen"
    else:
        state = f"verloopt over {_left(invite['expires_at'], now)}"
    return f"{invite.get('set_name') or 'Geen set'} · {used} · {state}"


def seen_text(last_at: Optional[str], now: datetime) -> Optional[str]:
    """Laatst gekeken uit user_visits.last_at; zonder bezoek bestaat het getal niet."""
    if not last_at:
        return None
    seconds = (now - logbook._parse(last_at)).total_seconds()
    if seconds < 60:
        return "net"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{int(seconds // 3600)} u"
    if seconds < 2 * 86400:
        return "gisteren"
    return f"{int(seconds // 86400)} d"


def initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s._-]+", name or "") if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (name or "?")[:2].upper()
