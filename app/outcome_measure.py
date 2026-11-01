"""Metingen bij de uitkomst die de beurs nodig hebben: de funding van een afgeronde focus-trade (app/funding.py) en MAE/MFE van een trade zonder
doel op 5m-candles (app/excursion.py). Aangeroepen door level_check.check_signal_outcomes, range_sweep_live.follow_trade en de scripts
funding_check en mae_check. Alleen meting: geen motor leest het. Lukt het ophalen niet, dan staat er 'onbekend', nooit een nul of een
andere meting alsof dit gemeten was; een fout hier houdt de uitkomst nooit tegen."""
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app import derivs, excursion, exchange, focus, funding, repo

logger = logging.getLogger("outcome_measure")

TIMEOUT_S = 5
TIMEFRAME = "5m"
STEP = pd.Timedelta(minutes=5)
PAGE = 1000
KNOWN, UNKNOWN = "gemeten", "onbekend"

# Naden naar de beurs; tests vervangen ze. Candles alleen via app/exchange (de candlebron), funding via app/derivs.
_candles_fetch = exchange.fetch_ohlcv
_funding_get = derivs._http_get

# Per contract de opgehaalde momenten en het venster dat ze dekken: funding_check rekent veel trades per coin na met één aanroep.
_cache: dict[str, tuple[int, int, list]] = {}


def clear_cache() -> None:
    _cache.clear()


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _ms(value) -> int:
    return int(_ts(value).timestamp() * 1000)


def funding_events(coin: str, start, end) -> list:
    """Funding-momenten tussen start en end. Het gedekte venster eindigt hoogstens bij nu: een moment dat nog moet komen, staat er later wel."""
    sym = funding.symbol(coin)
    lo, hi = _ms(start), min(_ms(end), _ms(datetime.now(timezone.utc)))
    hit = _cache.get(sym)
    if hit and hit[0] <= lo and hi <= hit[1]:
        return hit[2]
    events = derivs.funding_between(sym, lo, hi, _funding_get, TIMEOUT_S)
    _cache[sym] = (lo, hi, events)
    return events


def exit_end(row: dict, ref_closed_at: Optional[str] = None) -> pd.Timestamp:
    """Het einde van de uitgangscandle van een al afgeronde trade, voor het narekenen achteraf. Zonder doel (de motor zette de uitkomst): de
    15m-candle van de referentie-uitgang. Anders de candle die level_check vond (auto_outcome_at is zijn openmoment), 5m tenzij de bewaarde
    MAE-meting een ander timeframe zegt."""
    if ref_closed_at:
        return _ts(ref_closed_at) + pd.Timedelta(minutes=15)
    tf = row.get("mae_timeframe")
    step = pd.Timedelta(tf) if tf in ("5m", "15m") else STEP
    return _ts(row["auto_outcome_at"]) + step


def measure_funding(signal: dict, start, end) -> Optional[dict]:
    """De meting zonder opslaan (funding_check zonder --opslaan); None als het ophalen mislukte."""
    try:
        return funding.measure(signal["direction"], signal["price"], signal["stop_loss"], funding_events(signal["coin"], start, end), start, end)
    except Exception as exc:
        logger.warning("Funding van signaal %s (%s) niet op te halen: %s", signal["id"], signal["coin"], exc)
        return None


def record_funding(signal: dict, start, end) -> Optional[dict]:
    """Funding van vulling (start) tot het einde van de uitgangscandle (end), opgeslagen in trade_funding. Alleen de focus-soorten."""
    if not focus.is_focus(signal.get("trade_type")):
        return None
    start_iso, end_iso = _ts(start).isoformat(), _ts(end).isoformat()
    m = measure_funding(signal, start, end)
    try:
        if m is None:
            repo.set_trade_funding(signal["id"], None, None, None, UNKNOWN, start_iso, end_iso)
        else:
            repo.set_trade_funding(signal["id"], m["funding_r"], m["funding_pct"], m["events"], KNOWN, start_iso, end_iso)
    except Exception:
        logger.exception("Funding van signaal %s niet vastgelegd", signal["id"])
    return m


def candles_between(coin: str, start, end) -> pd.DataFrame:
    """5m-candles die op of na start openden en vóór end. Een week is meer dan één pagina; elke pagina gaat verder na de vorige."""
    lo, hi = _ts(start), _ts(end)
    parts, since = [], _ms(lo)
    while True:
        df = _candles_fetch(coin, timeframe=TIMEFRAME, limit=PAGE, since=since)
        if df is None or not len(df):
            break
        parts.append(df)
        last = df["timestamp"].iloc[-1]
        if last + STEP >= hi or len(df) < PAGE:
            break
        since = int((last + STEP).timestamp() * 1000)
    if not parts:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    out = pd.concat(parts).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return out[(out["timestamp"] >= lo) & (out["timestamp"] < hi)].reset_index(drop=True)


def record_excursion(signal_id: int, coin: str, direction: str, entry: float, stop: float, start, end) -> Optional[dict]:
    """MAE/MFE van een trade zonder doel, zoals level_check met doel meet: candles die op of na de vulling openden, tot de uitgang. Halen de
    candles de uitgang niet (of faalt het ophalen), dan 'onbekend' in plaats van de lopende meting van de motor."""
    try:
        candles = candles_between(coin, start, end)
        covered = len(candles) and candles["timestamp"].iloc[-1] >= _ts(end) - STEP
        m = excursion.measure(direction, entry, stop, None, candles) if covered else None
    except Exception as exc:
        logger.warning("Candles voor MAE/MFE van trade %s (%s) niet op te halen: %s", signal_id, coin, exc)
        m = None
    try:
        if m is None:
            repo.set_trade_excursion(signal_id, None, None, UNKNOWN)
        else:
            repo.set_trade_excursion(signal_id, m["mae_r"], m["mfe_r"], TIMEFRAME)
    except Exception:
        logger.exception("MAE/MFE van trade %s niet vastgelegd", signal_id)
    return m
