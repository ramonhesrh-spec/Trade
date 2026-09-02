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
    ]
    if signal.get("position_size"):
        lines.append(f"Voorgestelde grootte: {signal['position_size']:.6f} {signal['coin']}")
    lines += [
        "",
        f"Technisch bevestigd: {'ja' if signal['technical_confirmed'] else 'nee'}",
    ]
    if not signal["technical_confirmed"]:
        lines.append(f"Reden: {signal['reason']}")

    if signal.get("context_note"):
        lines += ["", signal["context_note"]]

    lines += ["", config.DISCLAIMER]

    return "\n".join(lines)


async def send_signal(signal: dict, chat_id: str) -> None:
    """Verstuurt de melding naar één specifieke chat ID. Elke gebruiker heeft
    zijn eigen chat ID en dus zijn eigen risicobedrag in het bericht."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, melding niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_signal_message(signal)
    await bot.send_message(chat_id=chat_id, text=text)
    logger.info("Telegram melding verstuurd voor %s %s naar chat %s",
                signal["coin"], signal["direction"], chat_id)
