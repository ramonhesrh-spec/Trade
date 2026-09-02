"""Dynamische coinlijst: coins genoemd in verwerkte berichten worden
automatisch toegevoegd, na controle dat het paar bestaat op de exchange."""
import logging

from app import exchange, repo

logger = logging.getLogger("coinlist")


def ensure_coin_tracked(coin: str) -> bool:
    """Controleert of het paar bestaat op de exchange en voegt de coin toe
    aan de dynamische lijst. Geeft True terug als de coin geldig is."""
    if not exchange.market_exists(coin):
        logger.info("Coin %s bestaat niet als paar op de exchange, niet toegevoegd", coin)
        return False

    symbol = exchange.to_symbol(coin)
    added = repo.add_coin_if_new(coin.upper(), symbol)
    if added:
        logger.info("Nieuwe coin toegevoegd aan dashboard: %s (%s)", coin.upper(), symbol)
    return True
