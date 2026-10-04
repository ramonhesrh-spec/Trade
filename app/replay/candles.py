"""Lokale cache van 15m-candles voor het meetraam. Alle andere timeframes
worden hieruit afgeleid (zie view.py), zodat een afgeleide candle nooit
ongemerkt later gesloten kan zijn dan het moment waarop hij wordt gebruikt."""
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from app import config, exchange

BASE_TIMEFRAME = "15m"
BASE_DELTA = pd.Timedelta(minutes=15)
PAGE_LIMIT = 1000
CACHE_DIR = Path(config.BASE_DIR) / "data" / "candles"


def cache_path(coin: str) -> Path:
    return CACHE_DIR / f"{coin.upper()}_{BASE_TIMEFRAME}.csv"


def download_candles(
    coin: str, years: float, fetch: Optional[Callable] = None, now: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Haalt `years` jaar 15m-candles op, pagina voor pagina. Een nog
    vormende candle (nu nog niet gesloten) blijft er bewust uit: het raam
    bepaalt zelf per tijdstip welke candle nog in wording is."""
    fetch = fetch or exchange.fetch_ohlcv
    now = now or pd.Timestamp.now(tz="UTC")
    since = int((now - pd.Timedelta(days=365 * years)).timestamp() * 1000)
    pages = []
    while True:
        page = fetch(coin, timeframe=BASE_TIMEFRAME, limit=PAGE_LIMIT, since=since)
        if page.empty:
            break
        pages.append(page)
        last_ts = page["timestamp"].iloc[-1]
        next_since = int(last_ts.timestamp() * 1000) + int(BASE_DELTA.total_seconds() * 1000)
        if next_since <= since or last_ts + BASE_DELTA >= now:
            break
        since = next_since
    if not pages:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.concat(pages).drop_duplicates("timestamp").sort_values("timestamp")
    df = df[df["timestamp"] + BASE_DELTA <= now]
    return df.reset_index(drop=True)


def save_candles(coin: str, df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(coin), index=False)


def load_candles(coin: str) -> pd.DataFrame:
    df = pd.read_csv(cache_path(coin))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def ensure_candles(coin: str, years: float, refresh: bool = False) -> pd.DataFrame:
    """Geeft de gecachete candles terug, of downloadt ze als er nog geen
    cache is (of `refresh` gezet is)."""
    if not refresh and cache_path(coin).exists():
        return load_candles(coin)
    df = download_candles(coin, years)
    save_candles(coin, df)
    return df
