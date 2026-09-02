"""Live koersdata via ccxt. Alleen publieke marktgegevens, geen API sleutel."""
import ccxt
import pandas as pd

from app import config

_exchange = None


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


def fetch_ohlcv(coin: str, timeframe: str = config.TIMEFRAME, limit: int = 200) -> pd.DataFrame:
    """Haalt candles op en geeft een DataFrame met open, high, low, close, volume."""
    exchange = get_exchange()
    symbol = to_symbol(coin)
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def fetch_last_price(coin: str) -> float:
    exchange = get_exchange()
    ticker = exchange.fetch_ticker(to_symbol(coin))
    return float(ticker["last"])
