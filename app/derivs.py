"""Verzamelt derivatendata per coin (funding, open interest, taker-verhouding,
long/short) uit de publieke Binance futures-API en bewaart die als CSV, naast de
candle-cache. Waarom: de candle-kenmerken zijn uitgeput (geen enkel kenmerk
haalt train en test tegelijk), dus nieuwe informatie moet van elders komen.
De history-endpoints geven maar ~30 dagen terug; elke dag zonder verzamelaar
is dus voorgoed kwijt. Draai uurlijks (deploy/crypto-derivs.timer)."""
import json
import logging
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from app import config

log = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"
DERIVS_DIR = Path(config.BASE_DIR) / "data" / "derivs"
PERIOD = "5m"
PAGE = 500
BACKFILL_DAYS = 29
COLUMNS = ["ts", "oi_usd", "taker_ratio", "global_ls", "top_ls", "funding"]

# kolomnaam -> (pad, waardeveld, tijdveld)
_SERIES = {
    "oi_usd": ("/futures/data/openInterestHist", "sumOpenInterestValue", "timestamp"),
    "taker_ratio": ("/futures/data/takerlongshortRatio", "buySellRatio", "timestamp"),
    "global_ls": ("/futures/data/globalLongShortAccountRatio", "longShortRatio", "timestamp"),
    "top_ls": ("/futures/data/topLongShortPositionRatio", "longShortRatio", "timestamp"),
}


def cache_path(coin: str) -> Path:
    return DERIVS_DIR / f"{coin.upper()}.csv"


def _http_get(path: str, params: dict) -> list:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read())


def _fetch_series(coin: str, column: str, since_ms: int, get: Callable) -> pd.Series:
    path, value_key, time_key = _SERIES[column]
    rows, start = [], since_ms
    while True:
        page = get(path, {"symbol": f"{coin}USDT", "period": PERIOD, "limit": PAGE, "startTime": start})
        if not page:
            break
        rows += [(int(r[time_key]), float(r[value_key])) for r in page]
        last = int(page[-1][time_key])
        if len(page) < PAGE or last < start:
            break
        start = last + 1
    if not rows:
        return pd.Series(dtype=float, name=column)
    s = pd.Series({pd.Timestamp(t, unit="ms", tz="UTC"): v for t, v in rows}, name=column)
    return s[~s.index.duplicated()]


def _fetch_funding(coin: str, since_ms: int, get: Callable) -> pd.Series:
    page = get("/fapi/v1/fundingRate", {"symbol": f"{coin}USDT", "limit": 1000, "startTime": since_ms})
    s = pd.Series({pd.Timestamp(int(r["fundingTime"]), unit="ms", tz="UTC"): float(r["fundingRate"]) for r in page},
                  name="funding", dtype=float)
    return s


def collect(coin: str, now: Optional[pd.Timestamp] = None, get: Optional[Callable] = None) -> pd.DataFrame:
    """Haalt alles op sinds de laatste opgeslagen rij (of 29 dagen terug bij de eerste keer)
    en voegt het toe aan de CSV. Funding wordt vooruit ingevuld: de laatste bekende
    waarde blijft gelden tot de volgende, net als op de beurs."""
    get = get or _http_get
    now = now or pd.Timestamp.now(tz="UTC")
    path = cache_path(coin)
    old = pd.read_csv(path, index_col="ts", parse_dates=["ts"]) if path.exists() else pd.DataFrame(columns=COLUMNS[1:])
    if len(old):
        since = old.index.max() - pd.Timedelta(hours=1)
    else:
        since = now - pd.Timedelta(days=BACKFILL_DAYS)
    since_ms = int(since.timestamp() * 1000)
    parts = [_fetch_series(coin, c, since_ms, get) for c in _SERIES]
    new = pd.concat(parts, axis=1)
    if new.empty:
        return old
    funding = _fetch_funding(coin, since_ms - 9 * 3600 * 1000, get)
    new["funding"] = funding.reindex(new.index.union(funding.index)).ffill().reindex(new.index)
    out = pd.concat([old, new])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.index.name = "ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    failed = 0
    for coin in config.FIXED_COINS:
        try:
            df = collect(coin)
            log.info("%s: %d rijen, laatste %s", coin, len(df), df.index.max() if len(df) else "-")
        except Exception:
            failed += 1
            log.exception("%s: ophalen mislukt", coin)
    return 1 if failed == len(config.FIXED_COINS) else 0


if __name__ == "__main__":
    sys.exit(main())
