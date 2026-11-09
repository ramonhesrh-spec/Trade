"""Schaduwvarianten live: de aansluiting in de motoren (observe) en het volgen op 5m-candles (track), elke cyclus in scan_smc_fast.

observe draait in de motor waar die zijn plannen maakt, met dezelfde invoer: één keer met de parameters van de hoofdversie (live_params) en één keer
met die van de variant. Beide plannen komen alleen in shadow_results; er gaat geen melding uit, er komt geen journaal- of signals-rij, en de
dagcap, de wachtende kaart per coin en de rest van de motor merken er niets van. Een fout hier kost alleen de schaduwmeting, nooit de motor."""
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from app import repo, shadow

logger = logging.getLogger("shadow_live")
FETCH_LIMIT = 1000                      # 5m-candles per keer: ruim drie dagen; wat erna komt volgt de volgende cyclus


def observe(trade_type: str, coin: str, make_plans: Callable[[dict], list[dict]], now) -> int:
    """make_plans(params) geeft de plannen van de motor met die parameters, als dicts met key, direction, limit, stop, take en expires_at.
    Geeft het aantal nieuwe schaduwrijen."""
    try:
        variant = repo.active_shadow(trade_type)
        if variant is None:
            return 0
        created = pd.Timestamp(now).isoformat()
        added = 0
        for arm, params in (("hoofd", shadow.live_params(trade_type)), ("variant", shadow.variant_params(variant))):
            for plan in make_plans(params):
                added += repo.insert_shadow_result(variant["id"], arm, {**plan, "coin": coin}, created)
        return added
    except Exception:
        logger.exception("Schaduw voor %s %s is mislukt; de motor zelf loopt door", trade_type, coin)
        return 0


def _default_fetch(coin: str, since: int):
    from app import exchange
    return exchange.fetch_ohlcv(coin, timeframe="5m", limit=FETCH_LIMIT, since=since)


def track(now: Optional[datetime] = None, fetch: Optional[Callable] = None) -> None:
    """Volgt alle open schaduwplannen (ook van een variant die net besloten is: de meting wordt afgemaakt)."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or (lambda coin, since: _default_fetch(coin, since))
    rows = repo.list_open_shadow_results()
    for coin in sorted({r["coin"] for r in rows}):
        mine = [r for r in rows if r["coin"] == coin]
        start = min(shadow._ts(r["checked_until"] or r["created_at"]) for r in mine)
        try:
            candles = fetch(coin, since=int(start.timestamp() * 1000))
        except Exception:
            logger.exception("5m-candles voor de schaduw van %s niet op te halen", coin)
            continue
        for r in mine:
            try:
                upd = shadow.step(r, candles, now)
                if upd["state"] != r["state"] or upd["checked_until"] != r["checked_until"]:
                    repo.update_shadow_result(r["id"], upd)
            except Exception:
                logger.exception("Schaduwplan %s is niet verwerkt", r["id"])
