"""Periodieke check, in twee delen:

1. Heeft een open trade (eigen entry al ingevuld) zijn stop loss of take
   profit al geraakt, terwijl die nog niet gesloten is in het logboek.
2. Is de prijs weer dicht bij het niveau van een nog niet genomen signaal
   gekomen, of bij een bron niveau (support/weerstand uit een gedeelde
   screenshot) van diezelfde coin, zodat een gebruiker die een melding zag
   maar nog niet instapte een seintje krijgt als het weer interessant
   wordt, in plaats van dat alleen een nieuw binnenkomend Discord bericht
   tot een melding leidt.

Zonder dit moet je zelf continu de koers in de gaten houden. Stuurt één
seintje per logboekregel, geen herhaalde meldingen. Sluit of opent niets
automatisch, dat blijft een handmatige stap in het dashboard. Wordt
aangeroepen via een systemd timer, zie deploy/crypto-level-check.service
en .timer.
"""
import asyncio
import logging
from typing import Optional

from telegram import Bot

from app import config, exchange, repo
from app.telegram_notify import DIVIDER, _factor_link

logger = logging.getLogger("level_check")

# Hoe dicht de prijs bij het oorspronkelijke signaalniveau moet komen voordat
# een nog niet genomen signaal een "weer interessant" seintje krijgt. In ATR,
# dezelfde maatstaf als de stop-afstand, zodat het meebeweegt met hoe
# volatiel de coin is in plaats van een vast percentage voor elke coin.
PENDING_LEVEL_ATR_MULTIPLIER = 0.5


def _level_hit(direction: str, current_price: float, stop_loss: float, take_profit: float) -> str:
    """Geeft "stop loss", "take profit" of "" terug."""
    if direction == "long":
        if stop_loss is not None and current_price <= stop_loss:
            return "stop loss"
        if take_profit is not None and current_price >= take_profit:
            return "take profit"
    else:
        if stop_loss is not None and current_price >= stop_loss:
            return "stop loss"
        if take_profit is not None and current_price <= take_profit:
            return "take profit"
    return ""


async def check_open_trades() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen seintjes verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    entries = repo.list_open_entries_with_levels()
    logger.info("%d open logboekregels om te checken", len(entries))

    coin_prices: dict[str, float] = {}

    for entry in entries:
        coin = entry["coin"]
        if coin not in coin_prices:
            try:
                coin_prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
            except Exception:
                logger.exception("Kon geen live prijs ophalen voor %s, sla over", coin)
                coin_prices[coin] = None
        current_price = coin_prices[coin]
        if current_price is None:
            continue

        hit = _level_hit(entry["direction"], current_price, entry["stop_loss"], entry["take_profit"])
        if not hit:
            continue

        if not entry["telegram_chat_id"]:
            repo.mark_level_alert_sent(entry["id"])
            continue

        hit_emoji = "🎯" if hit == "take profit" else "🛑"
        text = (
            f"{hit_emoji} {coin} · {entry['direction'].upper()}\n"
            f"{DIVIDER}\n"
            f"{hit.capitalize()} geraakt\n\n"
            f"Entry: {entry['entry_price']:.4f}\n"
            f"Nu: {current_price:.4f}\n"
            f"{DIVIDER}\n"
            f"Sluit je hem? Vul de exit in op het dashboard.\n\n"
            f"{_factor_link(coin)}\n"
            f"{DIVIDER}\n"
            f"⚠️ {config.DISCLAIMER}"
        )
        try:
            await bot.send_message(chat_id=entry["telegram_chat_id"], text=text)
            logger.info("Seintje verstuurd naar %s voor %s (%s)", entry["username"], coin, hit)
        except Exception:
            logger.exception("Seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])


def _nearest_level(current_price: float, atr: float, levels: list[dict]) -> Optional[dict]:
    """Bron niveau (support/weerstand uit een gedeelde screenshot) binnen
    dezelfde ATR-marge als het signaalniveau zelf. Geeft het dichtstbijzijnde
    niveau terug, of None als er geen enkele binnen bereik is."""
    within_range = [
        lvl for lvl in levels
        if abs(current_price - lvl["price_level"]) <= atr * PENDING_LEVEL_ATR_MULTIPLIER
    ]
    if not within_range:
        return None
    return min(within_range, key=lambda lvl: abs(current_price - lvl["price_level"]))


async def check_pending_signals() -> None:
    """Signalen die nog niet genomen zijn: als de prijs weer terugkomt naar
    het niveau waarop het signaal binnenkwam, óf naar een bron niveau uit
    een gedeelde screenshot (support, weerstand, retest), is dat voor day
    trading vaak het beste instapmoment, niet het moment van de eerste
    melding zelf. Dit is de proactieve kant, naast de reactieve verwerking
    van een nieuw Discord bericht."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen seintjes verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    entries = repo.list_pending_entries_with_price()
    logger.info("%d nog niet genomen signalen om te checken", len(entries))

    coin_prices: dict[str, float] = {}
    coin_levels: dict[str, list[dict]] = {}

    for entry in entries:
        coin = entry["coin"]
        if not entry["atr"]:
            continue
        if coin not in coin_prices:
            try:
                coin_prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
            except Exception:
                logger.exception("Kon geen live prijs ophalen voor %s, sla over", coin)
                coin_prices[coin] = None
        current_price = coin_prices[coin]
        if current_price is None:
            continue

        at_signal_level = (
            entry["signal_price"] is not None
            and abs(current_price - entry["signal_price"]) <= entry["atr"] * PENDING_LEVEL_ATR_MULTIPLIER
        )

        matched_level = None
        if not at_signal_level:
            if coin not in coin_levels:
                coin_levels[coin] = repo.list_source_levels(coin)
            matched_level = _nearest_level(current_price, entry["atr"], coin_levels[coin])

        if not at_signal_level and not matched_level:
            continue

        if not entry["telegram_chat_id"]:
            repo.mark_level_alert_sent(entry["id"])
            continue

        if matched_level:
            level_desc = f"{matched_level['price_level']}"
            if matched_level["pattern_name"]:
                level_desc += f" ({matched_level['pattern_name']})"
            level_line = f"Bron niveau: {level_desc}"
        else:
            level_line = f"Signaalniveau: {entry['signal_price']:.4f}"

        text = (
            f"🔔 {coin} · {entry['direction'].upper()}\n"
            f"{DIVIDER}\n"
            f"Terug bij een interessant niveau ({entry['confidence']})\n\n"
            f"{level_line}\n"
            f"Nu: {current_price:.4f}\n"
            f"{DIVIDER}\n"
            f"Nog steeds interessant? Check de actuele toetsing.\n\n"
            f"{_factor_link(coin)}\n"
            f"{DIVIDER}\n"
            f"⚠️ {config.DISCLAIMER}"
        )
        try:
            await bot.send_message(chat_id=entry["telegram_chat_id"], text=text)
            logger.info("Niveau-seintje verstuurd naar %s voor %s", entry["username"], coin)
        except Exception:
            logger.exception("Niveau-seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])


async def run_all_checks() -> None:
    await check_open_trades()
    await check_pending_signals()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_all_checks())
