"""Samenval: een SMC-signaal en een community-call (day_trading) op dezelfde coin en dezelfde kant binnen een
tijdvenster. Het is een hypothese, geen bewezen voordeel: de melding zegt 'ongetest', Bewijs toont de uitkomst
apart, en de detector gaat vanzelf uit als de eerste SAMENVAL_MAX_NEGATIVE afgeronde samenvallen netto negatief
zijn. Draait in dezelfde 5-minutencyclus als de SMC-check (market_scanner.scan_smc_fast), dus een call die na het
SMC-signaal binnenkomt wordt ook gezien."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config, push_notify, repo
from app.track_record import signal_r

logger = logging.getLogger(__name__)


def _t(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def find_matches(smc_signals: list[dict], calls: list[dict], already: set[int], window_hours: float) -> list[dict]:
    """Per SMC-signaal zonder samenval de dichtstbijzijnde community-call (day_trading, zelfde coin en kant)
    binnen het venster, voor of na het signaal."""
    window = timedelta(hours=window_hours)
    out = []
    for s in smc_signals:
        if s["id"] in already:
            continue
        at = _t(s["created_at"])
        candidates = [
            c for c in calls
            if c["category"] == "day_trading" and (c["coin"] or "").upper() == s["coin"].upper()
            and c["direction"] == s["direction"] and abs(_t(c["at"]) - at) <= window
        ]
        if candidates:
            best = min(candidates, key=lambda c: abs(_t(c["at"]) - at))
            out.append({"signal": s, "message_id": best["message_id"]})
    return out


def should_disable(results: list[dict], max_negative: int) -> bool:
    """Uit zodra er genoeg afgeronde samenvallen zijn en de som in R (bruto) negatief is."""
    rs = [signal_r(r) for r in results]
    rs = [r for r in rs if r is not None]
    return len(rs) >= max_negative and sum(rs) < 0


async def run(now: Optional[datetime] = None) -> int:
    """Geeft het aantal nieuwe samenvallen dat gemeld is."""
    if not config.SAMENVAL_ENABLED:
        return 0
    if should_disable(repo.list_samenval_results(config.SAMENVAL_MAX_NEGATIVE), config.SAMENVAL_MAX_NEGATIVE):
        logger.info("Samenval staat uit: de laatste %s afgeronde samenvallen zijn netto negatief", config.SAMENVAL_MAX_NEGATIVE)
        return 0
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=config.SAMENVAL_WINDOW_HOURS * 2)).isoformat()
    matches = find_matches(repo.list_smc_signals_since(since), repo.list_community_calls(),
                           repo.samenval_signal_ids(), config.SAMENVAL_WINDOW_HOURS)
    sent = 0
    for m in matches:
        s = m["signal"]
        if not repo.create_samenval(s["coin"], s["direction"], s["id"], m["message_id"]):
            continue
        sent += 1
        title = push_notify.alert_title(s["coin"], s["direction"], "Samenval (ongetest)")
        body = push_notify.trade_body("Entry", s["price"], s["stop_loss"], s["take_profit"], None,
                                      "SMC en community wijzen dezelfde kant op.", "Ongetest, zie Bewijs.")
        for user in repo.list_users():
            quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
            try:
                await push_notify.send_push(user["id"], title, body, f"/coins/{s['coin']}", silent=quiet)
            except Exception:
                logger.exception("Samenval-melding voor %s naar gebruiker %s is mislukt", s["coin"], user["username"])
    return sent
