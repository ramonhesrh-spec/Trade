"""Periodieke samenvatting (wekelijks of maandelijks) van iemands eigen
activiteit: aantal signalen, winrate, resultaat, beste en zwakste trade.

Rustige melding (zie Task 7 van het push-meldingen-plan): geen Telegram-
bericht meer, gewoon een platte-tekst rij in de notifications-tabel, die
op /meldingen staat te wachten ongeacht of iemand Telegram heeft
gekoppeld.

Wordt aangeroepen via twee aparte systemd timers met dezelfde service,
één argument verschil: --period week (zondagavond) of --period month
(de 1e van de maand), zie deploy/crypto-weekly-summary.service/.timer en
deploy/crypto-monthly-summary.service/.timer.
"""
import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import repo

logger = logging.getLogger("periodic_summary")

PERIOD_DAYS = {"week": 7, "month": 30}
PERIOD_LABELS = {"week": "afgelopen week", "month": "afgelopen maand"}


def _period_summary_text(stats: dict, auto_scan_stats: Optional[dict]) -> str:
    """Platte-tekst samenvatting voor de notifications-tabel: dezelfde
    cijfers als de oude Telegram-samenvatting, zonder de markdown,
    emoji-koppen of dividers die niet passen in een korte lijst-rij op
    /meldingen."""
    parts = [f"{stats['signal_count']} signalen, waarvan {stats['hoog_count']} hoog vertrouwen."]
    if stats["closed_count"]:
        winrate = stats["wins"] / stats["closed_count"] * 100
        sign = "+" if stats["total_result_eur"] >= 0 else ""
        parts.append(
            f"{stats['closed_count']} trades gesloten, {stats['wins']} gewonnen ({winrate:.0f}%), "
            f"resultaat {sign}€{stats['total_result_eur']:.2f}."
        )
        if stats["best"]:
            b = stats["best"]
            b_sign = "+" if b["result_eur"] >= 0 else ""
            parts.append(f"Beste trade: {b['coin']} {b_sign}€{b['result_eur']:.2f}.")
        if stats["worst"]:
            w = stats["worst"]
            w_sign = "+" if w["result_eur"] >= 0 else ""
            parts.append(f"Zwakste trade: {w['coin']} {w_sign}€{w['result_eur']:.2f}.")
    else:
        parts.append("Geen trades gesloten in deze periode.")
    if auto_scan_stats and auto_scan_stats["signal_count"] > 0:
        winrate_txt = (
            f", winrate {auto_scan_stats['winrate_pct']:.0f}%"
            if auto_scan_stats["winrate_pct"] is not None else ""
        )
        parts.append(
            f"HesPulse vond zelf {auto_scan_stats['signal_count']} kansen "
            f"({auto_scan_stats['closed_count']} afgesloten{winrate_txt})."
        )
    return " ".join(parts)


async def run(period: str) -> None:
    since = datetime.now(timezone.utc) - timedelta(days=PERIOD_DAYS[period])
    since_iso = since.isoformat()
    label = PERIOD_LABELS[period]

    for user in repo.list_users():
        stats = repo.period_stats(user["id"], since_iso)
        if stats["signal_count"] == 0 and stats["closed_count"] == 0:
            # Niks gebeurd deze periode, geen bericht sturen om niet te
            # gaan spammen met een lege samenvatting.
            continue
        auto_scan_stats = repo.period_stats_auto_scan(user["id"], since_iso) if period == "week" else None
        try:
            repo.create_notification(
                user["id"], "period_summary", f"Samenvatting {label}",
                _period_summary_text(stats, auto_scan_stats), "/dashboard",
            )
        except Exception:
            logger.exception("Periodieke samenvatting voor %s is mislukt", user["username"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["week", "month"], default="week")
    args = parser.parse_args()
    asyncio.run(run(args.period))
