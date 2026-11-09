"""De eenmalige pushmelding van de aankondiging, in de 5-minutencyclus (market_scanner.scan_smc_fast). Geen kans, dus niet via
send_kans_push en niet in het dagbudget; wel via send_push, die een pauze respecteert, en stil binnen iemands stille uren, zoals de dagbrief."""
import logging
from datetime import datetime, timezone
from typing import Optional

from app import announce, push_notify, repo

logger = logging.getLogger("announce_live")


async def run(now: Optional[datetime] = None) -> int:
    """Geeft het aantal gebruikers terug dat aan de beurt was. De claim staat vóór het versturen: twee processen of een herstart midden in
    de lus sturen hem nooit twee keer; wie bij een crash gemist wordt, krijgt hem niet alsnog (/nieuw en het verhaal blijven wel staan)."""
    now = now or datetime.now(timezone.utc)
    if not announce.push_due(repo.get_announcement_at(), now):
        return 0
    if not repo.claim_flag(f"announce_push:{announce.STORY_VERSION}"):
        return 0
    users = repo.list_users()
    for user in users:
        try:
            await push_notify.send_push(user["id"], announce.PUSH_TITLE, announce.PUSH_BODY, announce.PUSH_URL,
                                        silent=push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end")),
                                        tag="aankondiging")
        except Exception:
            logger.exception("Aankondigingspush naar gebruiker %s mislukt", user["id"])
    logger.info("Aankondiging gepusht naar %d gebruiker(s)", len(users))
    return len(users)
