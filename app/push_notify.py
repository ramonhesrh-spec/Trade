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
from zoneinfo import ZoneInfo

from pywebpush import WebPushException, webpush

from app import config, repo

logger = logging.getLogger("push_notify")

# De server draait op UTC, maar het "van/tot"-veld in het dashboard is een
# kaal <input type="time"> dat de gebruiker in zijn eigen (Nederlandse)
# klok invult. Zonder deze tijdzone zou de vergelijking hieronder tegen de
# kale server-tijd lopen, en zomertijd/wintertijd zou de stille uren dan
# ieder half jaar 1-2 uur laten opschuiven.
QUIET_HOURS_TIMEZONE = ZoneInfo("Europe/Amsterdam")


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
    now = datetime.now(QUIET_HOURS_TIMEZONE).time()
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


async def send_push(user_id: int, title: str, body: str, url: str, silent: bool = False, tag: Optional[str] = None) -> None:
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

    payload = {"title": title, "body": body, "url": url, "icon": "/static/icon-192.png", "silent": silent, "tag": tag}
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


async def send_kans_push(user_id: int, coin: str, direction: str, title: str, body: str, url: str, silent: bool = False, tag: Optional[str] = None) -> bool:
    """Push voor een nieuwe kans, met de regels van app/push_policy.py: geen tegenstrijdige richting kort na elkaar op dezelfde coin en een dagbudget per
    gebruiker. Een geweerde kans wordt een rustige melding op de meldingenpagina, dus niets verdwijnt. Geeft True als er een push is gestuurd.
    Updates van een lopende trade, stop en doel en de agenda gaan rechtstreeks via send_push en komen altijd."""
    from datetime import timedelta, timezone
    from app import push_policy
    now = datetime.now(timezone.utc)
    user = repo.get_user(user_id) or {}
    allowed, reason = push_policy.decide(repo.list_recent_pushes(user_id, (now - timedelta(hours=24)).isoformat()), coin, direction, user.get("push_budget"), now)
    if not allowed:
        repo.create_notification(user_id, "kans", title, f"{body}\n{reason}", url)
        return False
    repo.record_push(user_id, coin, direction, now.isoformat())
    await send_push(user_id, title, body, url, silent=silent, **({"tag": tag} if tag else {}))
    return True


_COIN_SYMBOLS = {"BTC": "₿", "ETH": "Ξ"}


def coin_symbol(coin: str) -> str:
    return _COIN_SYMBOLS.get(coin.upper(), "")


def fmt_price(value: float) -> str:
    """Vier decimalen onder de 100, twee erboven: 0,1632 en 67350,00 blijven allebei leesbaar op een vergrendeld scherm."""
    return f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}"


def alert_title(coin: str, direction: str, label: str) -> str:
    """Eén vorm voor elke melding, kort genoeg voor één regel: pijl, coin, kant en soort. Bijvoorbeeld '▲ BTC long · SMC'."""
    return f"{'▲' if direction == 'long' else '▼'} {coin} {direction} · {label}"


OPEN_PLAN_LINE = "Tik voor de grafiek en het plan."


def signal_url(coin: str, signal_id: int) -> str:
    """Link van een melding naar zijn kans: een eigen scherm per kans (/kans/<id>) met grafiek, feiten en tijdlijn. De coinpagina toont maar
    de laatste paar signalen, dus een anker daar bleef soms leeg."""
    return f"/kans/{signal_id}"


def trade_body(entry_label: str, entry: float, stop: float, take: float, rr: Optional[float] = None, *extra: str) -> str:
    """Eerste regel de order, tweede regel stop en take, daarna toelichting en als laatste een uitnodiging om te openen. Zo staat het
    belangrijkste altijd bovenaan en weet je wat een tik oplevert: de grafiek met het plan, niet alleen dezelfde cijfers."""
    first = f"{entry_label} {fmt_price(entry)}" + (f" · R:R {rr:.1f}" if rr else "")
    return "\n".join([first, f"Stop {fmt_price(stop)} · Take {fmt_price(take)}", *[line for line in extra if line], OPEN_PLAN_LINE])
