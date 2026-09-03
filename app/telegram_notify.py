"""Telegram meldingen. Het systeem voert geen trades uit, dit is puur een
melding, de beslissing blijft aan de gebruiker."""
import asyncio
import logging

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

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
        signal["reason"],
    ]

    if signal.get("context_note"):
        lines += ["", signal["context_note"]]

    lines += ["", config.DISCLAIMER]

    return "\n".join(lines)


def format_update_message(signal: dict) -> str:
    confidence_label = signal["confidence"].upper()
    lines = [
        f"UPDATE, {confidence_label} — {signal['coin']} "
        f"{'LONG' if signal['direction'] == 'long' else 'SHORT'}",
        "",
        f"Nieuwe prijs: {signal['price']:.4f}",
        f"Nieuwe stop loss: {signal['stop_loss']:.4f}",
        f"Nieuw take profit: {signal['take_profit']:.4f}",
        "",
        f"Technisch bevestigd: {'ja' if signal['technical_confirmed'] else 'nee'}",
        signal["reason"],
    ]
    if signal.get("context_note"):
        lines += ["", signal["context_note"]]
    lines += ["", config.DISCLAIMER]
    return "\n".join(lines)


async def send_signal_update(signal: dict, chat_id: str) -> None:
    """Kort bericht als een bestaand, nog openstaand signaal is bijgewerkt
    door een nieuw bericht over dezelfde coin en richting."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, update niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_update_message(signal)
    await bot.send_message(chat_id=chat_id, text=text)
    logger.info("Telegram update verstuurd voor %s %s naar chat %s",
                signal["coin"], signal["direction"], chat_id)


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


# ---------------------------------------------------------------------------
# /start: welkomstbericht zodra iemand voor het eerst met de bot begint te
# praten, met daarin meteen zijn eigen chat ID, zodat @userinfobot niet meer
# nodig is om die te achterhalen.
# ---------------------------------------------------------------------------

async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    text = (
        "Welkom bij HesPulse.\n\n"
        "Deze bot stuurt je een melding zodra een doorgestuurde analyse "
        "hoog vertrouwen scoort op de technische toetsing, met stop loss, "
        "take profit en je eigen positiegrootte.\n\n"
        f"Jouw Telegram chat ID: {chat_id}\n\n"
        "Vul dat in op het dashboard, onder Portfolio, om deze chat aan je "
        f"account te koppelen. Nog geen account? Maak er gratis een op "
        f"{config.DASHBOARD_URL}/registreer.\n\n"
        f"{config.DISCLAIMER}"
    )
    await update.message.reply_text(text)
    logger.info("Welkomstbericht verstuurd naar Telegram chat %s", chat_id)


async def run_telegram_listener() -> None:
    """Luistert continu naar /start in de gedeelde Telegram bot, naast het
    versturen van meldingen. Loopt tot het proces stopt, bedoeld om samen
    met de Discord bot in hetzelfde achtergrondproces te draaien."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN ontbreekt, geen /start listener gestart")
        return

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", _handle_start))

    async with application:
        await application.start()
        await application.updater.start_polling()
        logger.info("Telegram /start listener gestart")
        try:
            await asyncio.Event().wait()
        finally:
            await application.updater.stop()
            await application.stop()
