"""Vaste coinlijst (zie config.FIXED_COINS): coins genoemd in verwerkte
berichten worden alleen nog getoetst, nooit meer automatisch toegevoegd
buiten de vaste lijst (zie repo.add_coin_if_new)."""
import logging
import re

from app import config, exchange, repo

logger = logging.getLogger("coinlist")

# Toegestane vervolgletters ná een coin-alias die nog steeds als match
# tellen (in plaats van als "midden in een ander woord"): een ticker wordt
# vaak met de quote-valuta of contracttype geschreven, bv. "BTCUSDT" of
# "ETHPERP" — dat moet nog steeds matchen, in tegenstelling tot "ethanol".
_TICKER_SUFFIXES = ("usdt", "usd", "perp", "eur")

# Symbool + volledige naam per vaste coin, voor het goedkope tekstfilter in
# signal_processor.handle_message: een Discord-bericht zonder afbeelding
# dat geen van deze aliassen bevat, wordt nooit aan Anthropic voorgelegd
# (scheelt de duurste API-call per bericht). Bewust een losse, statische
# mapping in plaats van afgeleid uit FIXED_COINS: de sleutels moeten
# exact FIXED_COINS zijn, zie de assert hieronder die dat bij elke import
# bevestigt in plaats van pas bij een gemiste melding te ontdekken.
_KNOWN_ALIASES = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum"],
    "SOL": ["sol", "solana"],
    "BNB": ["bnb", "binance coin"],
    "AVAX": ["avax", "avalanche"],
    "DOGE": ["doge", "dogecoin"],
    "SUI": ["sui"],
    "XRP": ["xrp", "ripple"],
    "HBAR": ["hbar", "hedera"],
    "WLD": ["wld", "worldcoin"],
    "ONDO": ["ondo"],
    "LINK": ["link", "chainlink"],
    "ADA": ["ada", "cardano"],
    "LTC": ["ltc", "litecoin"],
    "NEAR": ["near"],
    "APT": ["apt", "aptos"],
    "ARB": ["arb", "arbitrum"],
    "INJ": ["inj", "injective"],
}
COIN_NAME_ALIASES = {coin: _KNOWN_ALIASES.get(coin, [coin.lower()]) for coin in config.FIXED_COINS}
assert set(COIN_NAME_ALIASES) == set(config.FIXED_COINS), (
    "COIN_NAME_ALIASES moet exact dezelfde coins als config.FIXED_COINS bevatten"
)


def message_mentions_tracked_coin(text: str) -> bool:
    """True zodra de tekst (case-insensitive) een symbool of volledige naam
    van een vaste coin bevat, op een echte woordgrens — niet als toevallig
    woorddeel ("solid"/"absolutely" bevatten "sol", "suicidal" bevat "sui").
    Een cijfer/letter ervoor telt niet als grens (voorkomt een valse match
    middenin een ander woord); een letter erna telt wel als grens BEHALVE
    als die letter een bekend ticker-achtervoegsel start (usdt/usd/perp/eur,
    zodat "BTCUSDT" en "$BTC" nog steeds matchen). Puur tekstueel, geen
    exchange-aanroep — dit moet goedkoop zijn, het draait op ELK inkomend
    Discord-bericht, vóór de Anthropic-interpretatie."""
    lowered = text.lower()
    for aliases in COIN_NAME_ALIASES.values():
        for alias in aliases:
            for match in re.finditer(re.escape(alias), lowered):
                start, end = match.span()
                if start > 0 and lowered[start - 1].isalnum():
                    continue
                after = lowered[end:]
                if after and after[0].isalpha() and not after.startswith(_TICKER_SUFFIXES):
                    continue
                return True
    return False


def ensure_coin_tracked(coin: str) -> tuple[bool, bool]:
    """Controleert of het paar bestaat op de exchange, en voegt de coin toe
    als die op config.FIXED_COINS staat maar nog niet in de coins-tabel zit
    (zie repo.add_coin_if_new — een coin buiten de vaste lijst wordt daar
    altijd geweigerd). Geeft (geldig, nieuw_toegevoegd) terug: geldig is
    True als de coin op de exchange bestaat, nieuw_toegevoegd is True de
    eerste keer dat deze coin wordt vastgelegd. Sinds de vaste coinlijst
    (HesPulse-verkleinen, 2026-09-30) gebeurt dat laatste normaal al bij de
    migratie in db.py — nieuw_toegevoegd is hier dus zelden nog True,
    behalve als een vaste coin handmatig uit de coins-tabel verwijderd
    werd."""
    if not exchange.market_exists(coin):
        logger.info("Coin %s bestaat niet als paar op de exchange, niet toegevoegd", coin)
        return False, False

    symbol = exchange.to_symbol(coin)
    added = repo.add_coin_if_new(coin.upper(), symbol)
    if added:
        logger.info("Nieuwe coin toegevoegd aan dashboard: %s (%s)", coin.upper(), symbol)
    return True, added
