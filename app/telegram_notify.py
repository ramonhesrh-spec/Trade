"""Telegram meldingen. Het systeem voert geen trades uit, dit is puur een
melding, de beslissing blijft aan de gebruiker."""
import logging

from telegram import Bot

from app import config

logger = logging.getLogger("telegram_notify")


def format_signal_message(signal: dict) -> str:
    direction_label = "LONG" if signal["direction"] == "long" else "SHORT"
    confidence_label = signal["confidence"].upper()

    lines = [
        f"{confidence_label} — {signal['coin']} {direction_label}",
        "",
        f"Prijs: {signal['price']:.4f}",
        f"Stop loss: {signal['stop_loss']:.4f}",
        f"Take profit: {signal['take_profit']:.4f}",
        f"Risicobedrag: €{signal['risk_eur']:.2f}",
        "",
        f"Technisch bevestigd: {'ja' if signal['technical_confirmed'] else 'nee'}",
    ]
    if not signal["technical_confirmed"]:
        lines.append(f"Reden: {signal['reason']}")

    return "\n".join(lines)


async def send_signal(signal: dict) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram token of chat ID ontbreekt, melding niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_signal_message(signal)
    await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text)
    logger.info("Telegram melding verstuurd voor %s %s", signal["coin"], signal["direction"])
