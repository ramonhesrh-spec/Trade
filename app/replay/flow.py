"""Taker-volume per minuut van Binance futures (USDT-M): hoeveel van het volume kwam van agressieve kopers. Candles zeggen wat de koers
deed, dit zegt wie er duwde. Gratis, een jaar geschiedenis, en de kolom zit in de klines die het meetraam tot nu toe wegliet.
Delta = (kopers min verkopers) gedeeld door volume: +1 is alleen agressief kopen, -1 alleen agressief verkopen."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from app import config

KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
PAGE = 1500
ONE_MINUTE_MS = 60_000
CACHE_DIR = Path(config.BASE_DIR) / "data" / "candles"


def flow_path(coin: str) -> Path:
    return CACHE_DIR / f"{coin.upper()}_1m_flow.csv"


THROTTLE_SECONDS = 0.3       # een pagina van 1500 minuten kost 10 gewicht van de 2400 per minuut
RETRIES = 4


def _http_get(params: dict) -> list:
    """Met een pauze tussen de aanroepen en een nieuwe poging bij 429 of 418 (te snel): de grens verloopt na een halve minuut."""
    for attempt in range(RETRIES):
        time.sleep(THROTTLE_SECONDS)
        try:
            with urllib.request.urlopen(f"{KLINES_URL}?{urllib.parse.urlencode(params)}", timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 418) or attempt == RETRIES - 1:
                raise
            time.sleep(30)
    return []


def download_flow(coin: str, start: pd.Timestamp, end: pd.Timestamp, get: Optional[Callable] = None) -> pd.DataFrame:
    """Kolommen: timestamp (begin van de minuut, UTC), volume, buy_volume (taker-kopers) en trades. Alleen gesloten minuten."""
    get = get or _http_get
    since, until = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    rows = []
    while since < until:
        page = get({"symbol": f"{coin.upper()}USDT", "interval": "1m", "limit": PAGE, "startTime": since, "endTime": until})
        if not page:
            break
        rows += [(int(k[0]), float(k[5]), float(k[9]), int(k[8])) for k in page if int(k[6]) < until]
        since = int(page[-1][0]) + ONE_MINUTE_MS
        if len(page) < PAGE:
            break
    df = pd.DataFrame(rows, columns=["ms", "volume", "buy_volume", "trades"])
    df["timestamp"] = pd.to_datetime(df.pop("ms"), unit="ms", utc=True)
    return df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)[["timestamp", "volume", "buy_volume", "trades"]]


def ensure_flow(coin: str, start: pd.Timestamp, end: pd.Timestamp, get: Optional[Callable] = None) -> pd.DataFrame:
    """Cache per coin; een tweede run haalt alleen de minuten na de laatste opgeslagen minuut op."""
    path = flow_path(coin)
    old = pd.read_csv(path, parse_dates=["timestamp"]) if path.exists() else None
    if old is not None and len(old):
        old["timestamp"] = pd.to_datetime(old["timestamp"], utc=True)
        start = max(start, old["timestamp"].iloc[-1] + pd.Timedelta(minutes=1))
    new = download_flow(coin, start, end, get) if start < end else pd.DataFrame(columns=["timestamp", "volume", "buy_volume", "trades"])
    df = pd.concat([old, new]) if old is not None else new
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def load_flow(coin: str) -> pd.DataFrame:
    df = pd.read_csv(flow_path(coin))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def flow_5m(flow_1m: pd.DataFrame, bar_starts: pd.Series) -> pd.DataFrame:
    """Per 5m-candle (zelfde indeling als lab.make_bars) volume, buy_volume en trades, op de volgorde van `bar_starts`."""
    f = flow_1m.set_index("timestamp").resample("5min", origin="epoch", label="left", closed="left").sum()
    return f.reindex(pd.DatetimeIndex(bar_starts)).reset_index(drop=True)


def delta(buy_volume, volume):
    """(kopers min verkopers) gedeeld door volume, tussen -1 en +1. Nul als er geen volume was."""
    volume = np.asarray(volume, dtype=float)
    return np.where(volume > 0, (2 * np.asarray(buy_volume, dtype=float) - volume) / np.where(volume > 0, volume, 1), 0.0)
