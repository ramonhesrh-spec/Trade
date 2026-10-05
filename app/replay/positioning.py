"""Historische positioneringsdata van Binance (gratis, data.binance.vision, USDT-perpetuals): open interest,
long/short-verhouding van de top-traders en van alle accounts, taker-koop/verkoop-volume per 5 minuten, en de
funding rate per 8 uur. Dit is informatie die niet in een candle zit. Alleen voor het meetraam; het live systeem
gebruikt het niet."""
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from app import config

BASE_URL = "https://data.binance.vision/data/futures/um"
CACHE_DIR = Path(config.BASE_DIR) / "data" / "candles"
METRIC_COLUMNS = {
    "sum_open_interest": "oi",
    "count_toptrader_long_short_ratio": "top_ratio",
    "count_long_short_ratio": "global_ratio",
    "sum_taker_long_short_vol_ratio": "taker_ratio",
}


def _csv_from_zip(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f)


def parse_metrics_zip(content: bytes) -> pd.DataFrame:
    raw = _csv_from_zip(content)
    out = pd.DataFrame({"timestamp": pd.to_datetime(raw["create_time"], utc=True)})
    for src, dst in METRIC_COLUMNS.items():
        out[dst] = pd.to_numeric(raw[src], errors="coerce") if src in raw else float("nan")
    return out


def parse_funding_zip(content: bytes) -> pd.DataFrame:
    raw = _csv_from_zip(content)
    ts = raw.iloc[:, 0]
    ts = pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts) else pd.to_datetime(ts, utc=True)
    return pd.DataFrame({"timestamp": ts, "funding": pd.to_numeric(raw["last_funding_rate"], errors="coerce")})


def _http_get(url: str) -> Optional[bytes]:
    import requests
    for _ in range(3):
        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            return r.content
    return None


def download_metrics(coin: str, start: pd.Timestamp, end: pd.Timestamp, get: Callable = _http_get, workers: int = 8) -> pd.DataFrame:
    symbol = f"{coin.upper()}USDT"
    days = pd.date_range(start.normalize(), end.normalize(), freq="D")
    urls = [f"{BASE_URL}/daily/metrics/{symbol}/{symbol}-metrics-{d:%Y-%m-%d}.zip" for d in days]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        contents = list(pool.map(get, urls))
    frames = [parse_metrics_zip(c) for c in contents if c]
    if not frames:
        return pd.DataFrame(columns=["timestamp", *METRIC_COLUMNS.values()])
    return pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def download_funding(coin: str, start: pd.Timestamp, end: pd.Timestamp, get: Callable = _http_get) -> pd.DataFrame:
    symbol = f"{coin.upper()}USDT"
    months = pd.period_range(start.tz_localize(None).to_period("M"), end.tz_localize(None).to_period("M"), freq="M")
    contents = [get(f"{BASE_URL}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m:%Y-%m}.zip") for m in months]
    frames = [parse_funding_zip(c) for c in contents if c]
    if not frames:
        return pd.DataFrame(columns=["timestamp", "funding"])
    return pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def ensure_positioning(coin: str, start: pd.Timestamp, end: pd.Timestamp, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(metrics, funding), uit de cache of gedownload. Bij een cache die vroeger eindigt dan `end` wordt
    opnieuw gedownload (refresh=True forceert dat ook)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    m_path, f_path = CACHE_DIR / f"{coin.upper()}_metrics.csv", CACHE_DIR / f"{coin.upper()}_funding.csv"
    if not refresh and m_path.exists() and f_path.exists():
        metrics = pd.read_csv(m_path)
        metrics["timestamp"] = pd.to_datetime(metrics["timestamp"], utc=True)
        funding = pd.read_csv(f_path)
        funding["timestamp"] = pd.to_datetime(funding["timestamp"], utc=True)
        if len(metrics) and metrics["timestamp"].iloc[-1] >= end - pd.Timedelta(days=2):
            return metrics, funding
    metrics = download_metrics(coin, start, end)
    funding = download_funding(coin, start, end)
    metrics.to_csv(m_path, index=False)
    funding.to_csv(f_path, index=False)
    return metrics, funding
