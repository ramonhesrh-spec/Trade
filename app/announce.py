"""De aankondiging van een update: aftelklok op /nieuw, het eenmalige "Wat is nieuw"-verhaal in de app en één pushmelding. Zuiver: geen
database, geen klok; de tijd komt binnen als argument. Het moment staat in de database (repo.get_announcement_at), zodat het zonder herstart
te zetten is met scripts/aankondiging.py.

Alles wat hier staat beschrijft wat er echt is. Geen getal dat niet klopt (35 = len(config.FIXED_COINS), tests/test_announce.py en
test_web_announce.py houden dat bij), geen winst of "bewezen"; nieuwe soorten heten ongetest."""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Amsterdam")

# Het verhaal en de push horen bij deze versie van de inhoud, niet bij de gekozen tijd: een tijd verzetten laat niemand het verhaal of de
# push twee keer krijgen. Een volgende update met een nieuw verhaal krijgt een nieuwe versie.
STORY_VERSION = "v4"
# Zo lang na het moment staat de link naar /nieuw op de loginpagina en in het menu; daarna is het geen nieuws meer.
RUN_DAYS = 7
# Een push die een dag te laat zou komen (proces lag stil, of de tijd werd in het verleden gezet) blijft weg: dan is hij geen aankondiging meer.
PUSH_WINDOW = timedelta(days=1)

HEADLINE_WORD = "Kansen."
HEADLINE_BEFORE = "Kansen. HesPulse wordt vernieuwd."
LEAD_BEFORE = "Nog even, dan staan alle kansen op één plek: een tab per soort, met de grafiek erbij."
HEADLINE_LIVE = "Het is live."
LEAD_LIVE = "Dit is er nieuw in HesPulse."

PROMISES = [
    "Alle kansen op één plek, per soort.",
    "35 coins, elke gespotte kans gedeeld.",
    "De order, stap voor stap.",
    "Licht en donker, naar keuze.",
]

CARDS = [
    {"key": "tabs", "title": "Alle kansen op één plek",
     "text": "Een tab per soort met de grafiek bij elke kans, en een tik toont stop, instap en doel."},
    {"key": "kansen", "title": "Zones en Structuur",
     "text": "35 coins, en elke kans die HesPulse spot zie jij ook, waarbij nieuwe soorten ongetest heten."},
    {"key": "checklist", "title": "De order, stap voor stap",
     "text": "De checklist volgt het orderformulier van je beurs en zet elk getal met een tik op je klembord."},
    {"key": "logboek", "title": "Logboek en Replay",
     "text": "Kijk je dag terug, ook de plannen die je oversloeg, en speel een trade opnieuw af."},
    {"key": "thema", "title": "Licht en donker",
     "text": "Kies in Account voor Systeem, Donker of Licht."},
    {"key": "installeer", "title": "Op je beginscherm",
     "text": "Zet HesPulse op je beginscherm, dan komen meldingen ook op je iPhone binnen."},
]

PUSH_TITLE = "HesPulse is vernieuwd"
PUSH_BODY = "Alle kansen op één plek, per soort met de grafiek: tik om te zien wat er nieuw is."
PUSH_URL = "/nieuw"

_DAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
_MONTHS = ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december")


def parse_moment(raw: Optional[str]) -> Optional[datetime]:
    """Een tijd zonder zone is Amsterdamse tijd (zo typt de eigenaar hem), een tijd met offset blijft dat moment. Altijd terug in UTC."""
    if not raw or not raw.strip():
        return None
    try:
        moment = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    return moment.astimezone(timezone.utc)


_RELATIVE = re.compile(r"^\+(?:(\d+)d)?(?:(\d+)[uh])?(?:(\d+)m)?$")


def parse_when(raw: Optional[str], now: datetime) -> Optional[datetime]:
    """Zoals parse_moment, en daarnaast een moment vanaf nu: "+30m", "+2u", "+1u30m" of "+1d". Zo kan de aankondiging direct na een update
    afgaan zonder een klok te hoeven lezen."""
    text = (raw or "").strip()
    if not text.startswith("+"):
        return parse_moment(text)
    m = _RELATIVE.match(text)
    if not m or not any(m.groups()):
        return None
    days, hours, minutes = (int(g or 0) for g in m.groups())
    return now + timedelta(days=days, hours=hours, minutes=minutes)


def remaining_text(at: datetime, now: datetime) -> str:
    """"nog 2 u 5 min 3 s" tot het moment; leeg als het voorbij is."""
    left = remaining(at, now)
    if not left["total"]:
        return ""
    if left["days"]:
        return f"nog {left['days']} d {left['hours']} u {left['minutes']} min {left['seconds']} s"
    if left["hours"]:
        return f"nog {left['hours']} u {left['minutes']} min {left['seconds']} s"
    if left["minutes"]:
        return f"nog {left['minutes']} min {left['seconds']} s"
    return f"nog {left['seconds']} s"


def fmt_local(at: datetime) -> str:
    local = at.astimezone(TZ)
    return f"{_DAYS[local.weekday()]} {local.day} {_MONTHS[local.month - 1]}, {local:%H:%M}"


def remaining(at: datetime, now: datetime) -> dict:
    """Naar boven afgerond op hele seconden: er staat nooit 0 terwijl het moment nog niet bereikt is."""
    seconds = max(0.0, (at - now).total_seconds())
    total = int(seconds) + (1 if seconds % 1 else 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    return {"days": days, "hours": hours, "minutes": minutes, "seconds": secs, "total": total}


def phase(at: Optional[datetime], now: datetime) -> str:
    """'before' tot het moment, daarna 'live'. Zonder tijd is er niets om naar af te tellen: dan de live-versie."""
    return "before" if at is not None and now < at else "live"


def story_due(at: Optional[datetime], now: datetime, seen: bool) -> bool:
    """Het verhaal opent vanzelf alleen na een gezet en bereikt moment, en één keer per gebruiker."""
    return at is not None and now >= at and not seen


def link_visible(at: Optional[datetime], now: datetime) -> bool:
    return at is not None and now < at + timedelta(days=RUN_DAYS)


def push_due(at: Optional[datetime], now: datetime) -> bool:
    return at is not None and at <= now < at + PUSH_WINDOW
