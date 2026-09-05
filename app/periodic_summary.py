"""Periodieke samenvatting (wekelijks of maandelijks) van iemands eigen
activiteit: aantal signalen, winrate, resultaat, beste en zwakste trade.

Geen afbeelding, gewoon tekst in dezelfde stijl als de andere Telegram
berichten: er bestaat in dit systeem geen beeld-generatie om op aan te
sluiten (de deel-knop op een gesloten trade deelt platte tekst, geen
plaatje), en een aparte afbeelding-stijl zou juist inconsistent aanvoelen
naast alle andere berichten.

Wordt aangeroepen via twee aparte systemd timers met dezelfde service,
één argument verschil: --period week (zondagavond) of --period month
(de 1e van de maand), zie deploy/crypto-weekly-summary.service/.timer en
deploy/crypto-monthly-summary.service/.timer.
"""
import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app import config, repo, telegram_notify

logger = logging.getLogger("periodic_summary")

PERIOD_DAYS = {"week": 7, "month": 30}
PERIOD_LABELS = {"week": "afgelopen week", "month": "afgelopen maand"}


async def run(period: str) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=PERIOD_DAYS[period])
    since_iso = since.isoformat()
    label = PERIOD_LABELS[period]

    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen samenvattingen verstuurd")
        return

    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        stats = repo.period_stats(user["id"], since_iso)
        if stats["signal_count"] == 0 and stats["closed_count"] == 0:
            # Niks gebeurd deze periode, geen bericht sturen om niet te
            # gaan spammen met een lege samenvatting.
            continue
        try:
            await telegram_notify.send_period_summary(stats, label, chat_id=user["telegram_chat_id"])
        except Exception:
            logger.exception("Periodieke samenvatting voor %s is mislukt", user["username"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["week", "month"], default="week")
    args = parser.parse_args()
    asyncio.run(run(args.period))
