"""Vaste coinlijst (zie config.FIXED_COINS): coins genoemd in verwerkte
berichten worden alleen nog getoetst, nooit meer automatisch toegevoegd
buiten de vaste lijst (zie repo.add_coin_if_new)."""
import logging

from app import config, exchange, repo

logger = logging.getLogger("coinlist")

# Symbool + volledige naam per vaste coin, voor het goedkope tekstfilter in
# signal_processor.handle_message: een Discord-bericht zonder afbeelding
# dat geen van deze aliassen bevat, wordt nooit aan Anthropic voorgelegd
# (scheelt de duurste API-call per bericht). Bewust een losse, statische
# mapping in plaats van afgeleid uit FIXED_COINS: de sleutels moeten
# exact FIXED_COINS zijn, zie de assert hieronder die dat bij elke import
# bevestigt in plaats van pas bij een gemiste melding te ontdekken.
COIN_NAME_ALIASES = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum"],
    "SOL": ["sol", "solana"],
    "BNB": ["bnb", "binance coin"],
    "AVAX": ["avax", "avalanche"],
    "DOGE": ["doge", "dogecoin"],
    "SUI": ["sui"],
}
assert set(COIN_NAME_ALIASES) == set(config.FIXED_COINS), (
    "COIN_NAME_ALIASES moet exact dezelfde coins als config.FIXED_COINS bevatten"
)


def message_mentions_tracked_coin(text: str) -> bool:
    """True zodra de tekst (case-insensitive) een symbool of volledige naam
    van een vaste coin bevat. Puur tekstueel, geen exchange-aanroep — dit
    moet goedkoop zijn, het draait op ELK inkomend Discord-bericht, vóór de
    Anthropic-interpretatie."""
    lowered = text.lower()
    return any(
        alias in lowered
        for aliases in COIN_NAME_ALIASES.values()
        for alias in aliases
    )


def ensure_coin_tracked(coin: str) -> tuple[bool, bool]:
    """Controleert of het paar bestaat op de exchange en voegt de coin toe
    aan de dynamische lijst. Geeft (geldig, nieuw_toegevoegd) terug: geldig
    is True als de coin op de exchange bestaat, nieuw_toegevoegd is True
    de eerste keer dat deze coin ooit gezien wordt, zodat de aanroeper
    gebruikers daarover kan informeren zonder dit hier zelf te doen (deze
    functie draait sync in een aparte thread, kan dus niet zelf een
    Telegram bericht versturen)."""
    if not exchange.market_exists(coin):
        logger.info("Coin %s bestaat niet als paar op de exchange, niet toegevoegd", coin)
        return False, False

    symbol = exchange.to_symbol(coin)
    added = repo.add_coin_if_new(coin.upper(), symbol)
    if added:
        logger.info("Nieuwe coin toegevoegd aan dashboard: %s (%s)", coin.upper(), symbol)
    return True, added
