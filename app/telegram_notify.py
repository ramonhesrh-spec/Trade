"""Telegram meldingen. Het systeem voert geen trades uit, dit is puur een
melding, de beslissing blijft aan de gebruiker."""
import asyncio
import logging

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app import config

logger = logging.getLogger("telegram_notify")

DIVIDER = "━" * 14

# Alleen de meest herkende symbolen, geen volledigheid nagestreefd: dit is
# een leuk extra herkenningspunt in een chat met meerdere coins door
# elkaar, geen vervanging van de tickernaam zelf.
COIN_SYMBOLS = {"BTC": "₿", "ETH": "Ξ"}


def _direction_label(direction: str) -> str:
    return "LONG" if direction == "long" else "SHORT"


def _direction_emoji(direction: str) -> str:
    return "📈" if direction == "long" else "📉"


def _coin_label(coin: str) -> str:
    symbol = COIN_SYMBOLS.get(coin.upper(), "")
    return f"{symbol}{coin}" if symbol else coin


def _factor_link(coin: str) -> str:
    """Link naar de coin-pagina, waar alle factoren van de toetsing
    (4 of 10, afhankelijk van ENABLE_ADVANCED_FACTORS) te zien zijn, niet
    alleen de samenvattende tekstregel die in het bericht zelf past."""
    factor_count = 10 if config.ENABLE_ADVANCED_FACTORS else 4
    url = f"{config.DASHBOARD_URL}/coins/{coin}"
    return f"🔎 Bekijk alle {factor_count} factoren: {url}"


def format_signal_message(signal: dict) -> str:
    """Volledige melding voor een bevestigde kans, met stop loss en take
    profit: dit is een echte, uitvoerbare trade opzet. Risicobedrag en
    positiegrootte staan bewust niet in het bericht, dat is aan de trader
    zelf om op het dashboard te bepalen."""
    lines = [
        f"{_direction_emoji(signal['direction'])} {_coin_label(signal['coin'])} · {_direction_label(signal['direction'])}",
        DIVIDER,
        f"🟢 {signal['confidence'].upper()}",
        "",
        f"💰 Prijs nu: {signal['price']:.4f}",
        f"🎯 Take profit: {signal['take_profit']:.4f}",
        f"🛑 Stop loss: {signal['stop_loss']:.4f}",
        DIVIDER,
    ]
    if signal.get("plain_explanation"):
        lines += [signal["plain_explanation"], ""]
    lines.append(signal["reason"])
    if signal.get("context_note"):
        lines += ["", signal["context_note"]]
    lines += ["", _factor_link(signal["coin"])]
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)


def format_rejected_message(signal: dict) -> str:
    """Melding voor een gedeelde tip die de technische toetsing niet
    haalt: geen stop loss/take profit, want dit is geen uitvoerbare trade
    opzet. Wel altijd een bericht, met de reden in gewone taal, zodat
    stilte nooit als "geen reactie" aanvoelt. Het systeem blijft deze coin
    volgen via de periodieke niveau-check, dat wordt hier expliciet
    benoemd."""
    lines = [
        f"{_direction_emoji(signal['direction'])} {_coin_label(signal['coin'])} · {_direction_label(signal['direction'])}",
        DIVIDER,
        "🟡 NOG GEEN STERKE KANS",
        "",
        f"💰 Prijs nu: {signal['price']:.4f}",
        DIVIDER,
    ]
    if signal.get("plain_explanation"):
        lines += [signal["plain_explanation"], ""]
    lines.append(signal["reason"])
    if signal.get("context_note"):
        lines += ["", signal["context_note"]]
    lines += ["", f"👀 Ik blijf {signal['coin']} volgen en stuur een seintje als het beter wordt."]
    lines += ["", _factor_link(signal["coin"])]
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)


def format_update_message(signal: dict) -> str:
    confirmed = signal["technical_confirmed"]
    status = "🟢 BEVESTIGD" if confirmed else "🟡 NOG GEEN STERKE KANS"
    lines = [
        f"🔄 UPDATE · {_coin_label(signal['coin'])} · {_direction_label(signal['direction'])}",
        DIVIDER,
        f"{status} ({signal['confidence'].upper()})",
        "",
        f"💰 Nieuwe prijs: {signal['price']:.4f}",
    ]
    if confirmed:
        lines += [
            f"🎯 Nieuw take profit: {signal['take_profit']:.4f}",
            f"🛑 Nieuwe stop loss: {signal['stop_loss']:.4f}",
        ]
    lines.append(DIVIDER)
    if signal.get("plain_explanation"):
        lines += [signal["plain_explanation"], ""]
    lines.append(signal["reason"])
    if signal.get("context_note"):
        lines += ["", signal["context_note"]]
    lines += ["", _factor_link(signal["coin"])]
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)


async def send_signal_update(signal: dict, chat_id: str) -> None:
    """Kort bericht als een bestaand, nog openstaand signaal is bijgewerkt
    door een nieuw bericht over dezelfde coin en richting."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, update niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_update_message(signal)
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=not signal["technical_confirmed"])
    logger.info("Telegram update verstuurd voor %s %s naar chat %s",
                signal["coin"], signal["direction"], chat_id)


async def send_signal(signal: dict, chat_id: str) -> None:
    """Verstuurt de melding naar één specifieke chat ID. Elke gebruiker heeft
    zijn eigen chat ID en dus zijn eigen risicobedrag in het bericht. Ook een
    afgewezen tip krijgt een bericht (format_rejected_message), stilte voelt
    voor de gebruiker aan als "er is niks gebeurd" in plaats van "getoetst en
    afgekeurd, met reden"."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, melding niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    confirmed = signal["technical_confirmed"]
    text = format_signal_message(signal) if confirmed else format_rejected_message(signal)
    # Een bevestigde kans mag geluid maken, een afwijzing niet: sinds elke
    # tip een bericht krijgt (ook een "geen kans"), zou anders elke deling
    # in de bron-community de telefoon laten afgaan, ook als er niks te
    # doen valt.
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=not confirmed)
    logger.info("Telegram melding verstuurd voor %s %s naar chat %s",
                signal["coin"], signal["direction"], chat_id)


async def send_new_coin_message(coin: str, chat_id: str) -> None:
    """Kort, stil bericht zodra een coin voor het eerst ooit gevolgd wordt.
    Geen actie van de gebruiker nodig, dus geen geluid."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        return
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = f"🆕 HesPulse volgt vanaf nu ook {_coin_label(coin)}."
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=True)
    logger.info("Nieuwe-coin melding verstuurd voor %s naar chat %s", coin, chat_id)


async def send_expired_pending_message(coin: str, new_direction: str, chat_id: str) -> None:
    """Bericht zodra een nog niet genomen kans automatisch is genegeerd
    omdat er een nieuwe melding voor de tegenovergestelde richting van
    dezelfde coin binnenkwam (zie repo.auto_ignore_opposite_pending). Stil,
    want dit is geen nieuwe kans, alleen het intrekken van een oude."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        return
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = (
        f"❌ {_coin_label(coin)}\n"
        f"{DIVIDER}\n"
        f"Je eerdere kans op deze coin is niet meer actueel.\n\n"
        f"Er kwam een nieuwe melding voor de tegenovergestelde richting "
        f"({_direction_label(new_direction)}) binnen, die maakt dit signaal achterhaald."
    )
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=True)
    logger.info("Vervallen-kans melding verstuurd voor %s naar chat %s", coin, chat_id)


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
        # drop_pending_updates=True: bij elke herstart van deze service (en
        # dat gebeurt vaak tijdens actief ontwikkelen) anders alle /start
        # commando's die binnenkwamen terwijl de bot niet luisterde in één
        # keer alsnog afvuurt, inclusief oude van dagen geleden. Zonder dit
        # kreeg één gebruiker bij de eerste herstart 15 welkomstberichten
        # achter elkaar.
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram /start listener gestart")
        try:
            await asyncio.Event().wait()
        finally:
            await application.updater.stop()
            await application.stop()
