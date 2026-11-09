"""Welke markt de candles en koersen levert: Binance USDⓈ-M perpetuals (standaard) of spot. Zuiver: de symboolkaart, de schaal van een
1000-contract en welke markt een coin in dit proces echt gebruikte. app/exchange.py doet het ophalen.

Een 1000-contract (1000PEPEUSDT) noteert de prijs van 1000 munten. exchange.py rekent die om naar de prijs per munt (prijs / schaal,
volume * schaal), niet andersom: alle opgeslagen kaarten, POC-niveaus en open trades van vóór de overstap staan in de prijs per munt, en
level_check vergelijkt die met nieuwe candles. Met de contractprijs zou een open PEPE-trade meteen een vals doel of een valse stop raken.
De kaart toont dus de prijs per munt; wie op de beurs het 1000-contract ziet, deelt door 1000 (de kaart zegt welke markt de bron is)."""
from typing import NamedTuple, Optional

from app import config

PERP, SPOT = "perp", "spot"
LABELS = {PERP: "Binance perps", SPOT: "Binance spot"}

# Coins waarvan het perpcontract een andere naam heeft. De schaal staat in het voorvoegsel. Alleen PEPE zit in config.FIXED_COINS
# (2026-11-01); de rest staat er zodat een coin die erbij komt niet stil op de verkeerde prijs loopt. pick_perp herkent een onbekend
# 1000-contract ook aan de marktenlijst van de beurs.
PERP_ALIASES = {"PEPE": "1000PEPE", "SHIB": "1000SHIB", "BONK": "1000BONK", "FLOKI": "1000FLOKI", "LUNC": "1000LUNC", "XEC": "1000XEC",
                "SATS": "1000SATS", "RATS": "1000RATS", "CAT": "1000CAT", "CHEEMS": "1000CHEEMS", "MOG": "1000000MOG"}
_PREFIXES = (1_000_000, 1000)


class Source(NamedTuple):
    market: str
    symbol: str     # ccxt-symbool, bv. BTC/USDT:USDT of BTC/USDT
    scale: int      # munten per contracteenheid: 1000 bij 1000PEPE


_used: dict[str, str] = {}


def configured() -> str:
    """De gekozen markt. Perps alleen via Binance (binanceusdm); een andere EXCHANGE_ID houdt zijn spotmarkt."""
    if config.EXCHANGE_ID != "binance":
        return SPOT
    return SPOT if str(getattr(config, "CANDLE_MARKET", PERP)).strip().lower() == SPOT else PERP


def ccxt_id(market: str) -> str:
    return "binanceusdm" if market == PERP else config.EXCHANGE_ID


def base_of(coin: str) -> str:
    """BTC, btc/usdt en BTC/USDT:USDT zijn allemaal BTC."""
    return coin.upper().strip().split("/")[0].split(":")[0]


def _scale_of(contract_base: str, base: str) -> int:
    for n in _PREFIXES:
        if contract_base == f"{n}{base}":
            return n
    return 1


def pick_perp(base: str, markets) -> Optional[Source]:
    """Het perpcontract van een munt in de marktenlijst van binanceusdm, of None als er geen is."""
    quote = config.QUOTE_CURRENCY
    candidates = [PERP_ALIASES[base]] if base in PERP_ALIASES else []
    candidates += [base] + [f"{n}{base}" for n in _PREFIXES]
    for name in dict.fromkeys(candidates):
        symbol = f"{name}/{quote}:{quote}"
        if symbol in markets:
            return Source(PERP, symbol, _scale_of(name, base))
    return None


def spot_source(base: str) -> Source:
    return Source(SPOT, f"{base}/{config.QUOTE_CURRENCY}", 1)


def note(coin: str, market: str) -> None:
    _used[base_of(coin)] = market


def reset() -> None:
    _used.clear()


def market_of(coin: str) -> str:
    """De markt waarvan dit proces de candles van deze coin haalde; nog niets gehaald (of een test die het ophalen nabootst): de gekozen markt.
    De motoren halen hun candles altijd vóór ze een kaart of signaal opslaan, dus de repo leest hier de echte bron."""
    return _used.get(base_of(coin)) or configured()


def label(market: Optional[str]) -> Optional[str]:
    return LABELS.get(market) if market else None


def stream_map() -> dict[str, list]:
    """Voor live.js: coins die afwijken van de standaardstroom, {coin: [streamsymbool, schaal, markt]}. Een terugval naar spot is pas bekend
    nadat dit proces de coin ophaalde; tot dan krijgt hij de perpstroom en houdt de gewone poll de koers bij."""
    quote = config.QUOTE_CURRENCY
    out = {}
    if configured() == PERP:
        for coin, name in PERP_ALIASES.items():
            out[coin] = [f"{name}{quote}", _scale_of(name, coin), PERP]
    for coin, market in _used.items():
        if market != configured():
            out[coin] = [f"{coin}{quote}", 1, market]
    return out
