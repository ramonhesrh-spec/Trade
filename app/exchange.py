"""Live koersdata via ccxt. Alleen publieke marktgegevens, geen API sleutel."""
import logging
import time

import ccxt
import pandas as pd

from app import candle_source, config

logger = logging.getLogger("exchange")

# Eén ccxt-client per markt (perp: binanceusdm, spot: config.EXCHANGE_ID) en per coin de gekozen bron (app/candle_source.py).
_clients: dict = {}
_resolved: dict = {}

FETCH_ATTEMPTS = 3
FETCH_BACKOFF_SECONDS = 2


def _ccxt_class(ident: str):
    return getattr(ccxt, ident)


def reset() -> None:
    _clients.clear()
    _resolved.clear()
    candle_source.reset()


def _client(market: str) -> ccxt.Exchange:
    if market not in _clients:
        client = _ccxt_class(candle_source.ccxt_id(market))({"enableRateLimit": True})
        client.load_markets()
        _clients[market] = client
    return _clients[market]


def get_exchange() -> ccxt.Exchange:
    """De spotclient van EXCHANGE_ID, zoals vóór CANDLE_MARKET: alleen voor de onderzoeksscripts die zelf met spotsymbolen (BTC/USDT)
    werken. Live candles en koersen gaan via fetch_ohlcv en fetch_last_price, die per coin de markt kiezen (resolve)."""
    return _client(candle_source.SPOT)


def resolve(coin: str) -> candle_source.Source:
    """Perpcontract als dat bestaat (en CANDLE_MARKET perp is), anders spot. Eén keer per coin per proces; de marktenlijst komt uit
    load_markets, dat ccxt één keer per client ophaalt."""
    base = candle_source.base_of(coin)
    if base not in _resolved:
        src = candle_source.pick_perp(base, _client(candle_source.PERP).markets) if candle_source.configured() == candle_source.PERP else None
        _resolved[base] = src or candle_source.spot_source(base)
    src = _resolved[base]
    candle_source.note(base, src.market)
    return src


def to_symbol(coin: str) -> str:
    """De paarnaam van een coin, bijvoorbeeld BTC -> BTC/USDT (voor de coins-tabel en weergave; de beurs-symbolen komen uit resolve)."""
    coin = coin.upper().strip()
    if "/" in coin:
        return coin
    return f"{coin}/{config.QUOTE_CURRENCY}"


def market_exists(coin: str) -> bool:
    src = resolve(coin)
    return src.symbol in _client(src.market).markets


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


def fetch_ohlcv(
    coin: str, timeframe: str = config.TIMEFRAME, limit: int = 200, since: int | None = None,
) -> pd.DataFrame:
    """Haalt candles op en geeft een DataFrame met open, high, low, close, volume.
    `since` (milliseconden sinds epoch) haalt candles vanaf een specifiek
    moment op in plaats van de laatste `limit` candles tot nu, gebruikt om
    terug te kijken vanaf het moment dat een bron niveau werd gedeeld.
    Een 1000-contract komt terug in de prijs per munt (candle_source)."""
    src = resolve(coin)
    raw = _with_retry(
        f"fetch_ohlcv {src.symbol}", _client(src.market).fetch_ohlcv, src.symbol, timeframe=timeframe, limit=limit, since=since,
    )
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).astype("datetime64[ns, UTC]")
    if src.scale != 1:
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float) / src.scale
        df["volume"] = df["volume"].astype(float) * src.scale
    return df


def _ticker(coin: str) -> tuple[dict, candle_source.Source]:
    src = resolve(coin)
    return _with_retry(f"fetch_ticker {src.symbol}", _client(src.market).fetch_ticker, src.symbol), src


def fetch_last_price(coin: str) -> float:
    ticker, src = _ticker(coin)
    return float(ticker["last"]) / src.scale


def fetch_24h_quote_volume(coin: str) -> float:
    """Handelsvolume van de laatste 24 uur in quote-valuta (meestal USDT),
    voor de liquiditeitscheck: een technisch perfecte setup op een dun
    verhandelde coin is in de praktijk niet fatsoenlijk uit te voeren.
    In USDT, dus zonder de schaal van een 1000-contract."""
    ticker, _ = _ticker(coin)
    return float(ticker["quoteVolume"])
