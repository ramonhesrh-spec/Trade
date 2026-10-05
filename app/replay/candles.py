"""Lokale cache van basis-candles voor het meetraam (15m voor day_trading, 1m
voor smc). Alle andere timeframes worden hieruit afgeleid (zie view.py), zodat
een afgeleide candle nooit ongemerkt later gesloten kan zijn dan het moment
waarop hij wordt gebruikt."""
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from app import config, exchange

BASE_TIMEFRAME = "15m"
BASE_DELTA = pd.Timedelta(minutes=15)
BASE_DELTAS = {"1m": pd.Timedelta(minutes=1), "15m": BASE_DELTA}
PAGE_LIMIT = 1000
CACHE_DIR = Path(config.BASE_DIR) / "data" / "candles"


def cache_path(coin: str, timeframe: str = BASE_TIMEFRAME) -> Path:
    return CACHE_DIR / f"{coin.upper()}_{timeframe}.csv"


def download_candles(
    coin: str, years: float, fetch: Optional[Callable] = None, now: Optional[pd.Timestamp] = None,
    timeframe: str = BASE_TIMEFRAME, since_ts: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Haalt `years` jaar candles op (of vanaf `since_ts` als die gezet is), pagina voor pagina. Een nog vormende
    candle (nu nog niet gesloten) blijft er bewust uit: het raam bepaalt zelf
    per tijdstip welke candle nog in wording is."""
    fetch = fetch or exchange.fetch_ohlcv
    delta = BASE_DELTAS[timeframe]
    now = now or pd.Timestamp.now(tz="UTC")
    start = since_ts if since_ts is not None else now - pd.Timedelta(days=365 * years)
    since = int(start.timestamp() * 1000)
    pages = []
    while True:
        page = fetch(coin, timeframe=timeframe, limit=PAGE_LIMIT, since=since)
        if page.empty:
            break
        pages.append(page)
        last_ts = page["timestamp"].iloc[-1]
        next_since = int(last_ts.timestamp() * 1000) + int(delta.total_seconds() * 1000)
        if next_since <= since or last_ts + delta >= now:
            break
        since = next_since
    if not pages:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.concat(pages).drop_duplicates("timestamp").sort_values("timestamp")
    df = df[df["timestamp"] + delta <= now]
    return df.reset_index(drop=True)


def save_candles(coin: str, df: pd.DataFrame, timeframe: str = BASE_TIMEFRAME) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(coin, timeframe), index=False)


def load_candles(coin: str, timeframe: str = BASE_TIMEFRAME) -> pd.DataFrame:
    df = pd.read_csv(cache_path(coin, timeframe))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def ensure_candles(coin: str, years: float, refresh: bool = False, timeframe: str = BASE_TIMEFRAME) -> pd.DataFrame:
    """Geeft de gecachete candles terug, of downloadt ze als er nog geen
    cache is (of `refresh` gezet is)."""
    if not refresh and cache_path(coin, timeframe).exists():
        return load_candles(coin, timeframe)
    df = download_candles(coin, years, timeframe=timeframe)
    save_candles(coin, df, timeframe)
    return df


def update_candles(coin: str, first_needed: pd.Timestamp, timeframe: str = "1m") -> pd.DataFrame:
    """Houdt een cache klein en actueel: bestaat er nog geen cache, dan vanaf `first_needed` (min twee dagen
    voor de ATR); anders worden alleen de candles na de laatste opgeslagen candle toegevoegd. Een cache die
    later begint dan first_needed wordt niet aangevuld naar achteren."""
    path = cache_path(coin, timeframe)
    delta = BASE_DELTAS[timeframe]
    if not path.exists():
        df = download_candles(coin, 0, timeframe=timeframe, since_ts=first_needed - pd.Timedelta(days=2))
        save_candles(coin, df, timeframe)
        return df
    df = load_candles(coin, timeframe)
    new = download_candles(coin, 0, timeframe=timeframe, since_ts=df["timestamp"].iloc[-1] + delta)
    if not new.empty:
        df = pd.concat([df, new]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
        save_candles(coin, df, timeframe)
    return df
