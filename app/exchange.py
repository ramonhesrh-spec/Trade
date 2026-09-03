"""Live koersdata via ccxt. Alleen publieke marktgegevens, geen API sleutel."""
import logging
import time

import ccxt
import pandas as pd

from app import config

logger = logging.getLogger("exchange")

_exchange = None

FETCH_ATTEMPTS = 3
FETCH_BACKOFF_SECONDS = 2


def get_exchange() -> ccxt.Exchange:
    global _exchange
    if _exchange is None:
        exchange_class = getattr(ccxt, config.EXCHANGE_ID)
        _exchange = exchange_class({"enableRateLimit": True})
        _exchange.load_markets()
    return _exchange


def to_symbol(coin: str) -> str:
    """Zet een coin ticker om naar het exchange paar, bijvoorbeeld BTC -> BTC/USDT."""
    coin = coin.upper().strip()
    if "/" in coin:
        return coin
    return f"{coin}/{config.QUOTE_CURRENCY}"


def market_exists(coin: str) -> bool:
    exchange = get_exchange()
    symbol = to_symbol(coin)
    return symbol in exchange.markets


def _with_retry(label: str, func, *args, **kwargs):
    """Probeert een exchange call een paar keer bij een tijdelijke netwerk-
    of exchange-fout, voordat de fout doorgegeven wordt. Een enkele
    hapering bij Binance mag geen hele verwerking laten mislukken."""
    last_exc: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            return func(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            last_exc = exc
            logger.warning("%s poging %s/%s mislukt: %s", label, attempt, FETCH_ATTEMPTS, exc)
            if attempt < FETCH_ATTEMPTS:
                time.sleep(FETCH_BACKOFF_SECONDS * attempt)
    raise last_exc


def fetch_ohlcv(coin: str, timeframe: str = config.TIMEFRAME, limit: int = 200) -> pd.DataFrame:
    """Haalt candles op en geeft een DataFrame met open, high, low, close, volume."""
    exchange = get_exchange()
    symbol = to_symbol(coin)
    raw = _with_retry(f"fetch_ohlcv {symbol}", exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def fetch_last_price(coin: str) -> float:
    exchange = get_exchange()
    symbol = to_symbol(coin)
    ticker = _with_retry(f"fetch_ticker {symbol}", exchange.fetch_ticker, symbol)
    return float(ticker["last"])


def fetch_24h_quote_volume(coin: str) -> float:
    """Handelsvolume van de laatste 24 uur in quote-valuta (meestal USDT),
    voor de liquiditeitscheck: een technisch perfecte setup op een dun
    verhandelde coin is in de praktijk niet fatsoenlijk uit te voeren."""
    exchange = get_exchange()
    symbol = to_symbol(coin)
    ticker = _with_retry(f"fetch_ticker {symbol}", exchange.fetch_ticker, symbol)
    return float(ticker["quoteVolume"])
