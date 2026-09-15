"""Web Push-meldingen naar de HesPulse-app, vervangt de oude Telegram-bot
als meldingenkanaal. Eigen VAPID-sleutelpaar (app/config.py), geen
externe pushdienst: het abonnement zelf loopt via Apple/Google's eigen
infrastructuur (dat is hoe Web Push werkt), maar wij bouwen en versturen
de payload zelf."""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from pywebpush import WebPushException, webpush

from app import config, repo

logger = logging.getLogger("push_notify")


def is_quiet_now(quiet_hours_start: Optional[str], quiet_hours_end: Optional[str]) -> bool:
    """Verplaatst uit de oude Telegram-notificatiemodule (Task 11): puur
    een tijdvenster-check, niets Telegram-specifieks, dus hoort hier net
    zo goed thuis. Ongewijzigde logica, inclusief het dag-overschrijdende
    venster (bijvoorbeeld "23:00" tot "07:00"). Beide velden leeg (None)
    betekent geen stille uren ingesteld, dan altijd False."""
    if not quiet_hours_start or not quiet_hours_end:
        return False
    try:
        start = datetime.strptime(quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(quiet_hours_end, "%H:%M").time()
    except ValueError:
        return False
    now = datetime.now().time()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def _send_one(subscription: dict, payload: dict) -> None:
    webpush(
        subscription_info={
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        },
        data=json.dumps(payload),
        vapid_private_key=config.VAPID_PRIVATE_KEY,
        vapid_claims={"sub": config.VAPID_CLAIM_EMAIL},
    )


async def send_push(user_id: int, title: str, body: str, url: str, silent: bool = False) -> None:
    """Stuurt naar elk geregistreerd apparaat van deze gebruiker. Een
    apparaat dat de browser/OS niet meer kent (404/410 terug) wordt
    meteen verwijderd, anders blijft push_subscriptions vervuild raken
    met dode abonnementen. Eén mislukt apparaat blokkeert de andere
    apparaten van dezelfde gebruiker niet (zelfde patroon als de oude
    Telegram-verstuurfunctie al per gebruiker in zijn eigen try/except
    draaide)."""
    if not config.VAPID_PRIVATE_KEY:
        logger.warning("VAPID_PRIVATE_KEY ontbreekt, pushmelding niet verstuurd")
        return

    subscriptions = repo.list_push_subscriptions(user_id)
    if not subscriptions:
        return

    payload = {"title": title, "body": body, "url": url, "icon": "/static/icon-192.png", "silent": silent}
    for sub in subscriptions:
        try:
            await asyncio.to_thread(_send_one, sub, payload)
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                repo.delete_push_subscription(sub["endpoint"])
                logger.info("Dood push-abonnement verwijderd (status %s): %s", status, sub["endpoint"])
            else:
                logger.exception("Pushmelding naar abonnement %s mislukt (status %s)", sub["id"], status)
        except Exception:
            logger.exception("Pushmelding naar abonnement %s mislukt", sub["id"])


_COIN_SYMBOLS = {"BTC": "₿", "ETH": "Ξ"}


def coin_symbol(coin: str) -> str:
    return _COIN_SYMBOLS.get(coin.upper(), "")
