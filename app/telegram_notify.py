"""Telegram meldingen. Het systeem voert geen trades uit, dit is puur een
melding, de beslissing blijft aan de gebruiker."""
import asyncio
import logging
from datetime import datetime
from typing import Optional

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


PROGRESS_BAR_WIDTH = 10


def _progress_bar(price: float, stop_loss: float, take_profit: float, direction: str) -> str:
    """Blokjesbalk die toont waar de huidige prijs zit tussen stop loss (0%)
    en take profit (100%), puur op basis van velden die het bericht toch
    al meestuurt, geen aparte 'oorspronkelijke entry' hoeft hiervoor
    bijgehouden te worden. Bij het risk:reward-ontwerp van risk.py
    (1:2) staat een gloednieuwe kans al op ongeveer 33%, dat is geen fout,
    dat is de ingebouwde verhouding tussen de stop-afstand en de
    doelafstand."""
    if direction == "long":
        span = take_profit - stop_loss
        pos = (price - stop_loss) / span if span else 0.0
    else:
        span = stop_loss - take_profit
        pos = (stop_loss - price) / span if span else 0.0
    pos = max(0.0, min(1.0, pos))
    filled = round(pos * PROGRESS_BAR_WIDTH)
    bar = "▓" * filled + "░" * (PROGRESS_BAR_WIDTH - filled)
    return f"{bar} {pos * 100:.0f}% naar TP"


# Boven welk percentage van de portfolio het totale open risico (som van
# alle nog open trades, inclusief de kans in dit bericht) een waarschuwing
# waard is. Leerboek-vuistregel (niet meer dan 5 tot 10% van de
# portefeuille tegelijk op het spel), geen instelling per gebruiker, dat
# kan later nog toegevoegd worden.
OPEN_RISK_WARNING_PCT = 10.0


def _open_risk_line(open_risk_pct: float) -> str:
    marker = "⚠️" if open_risk_pct >= OPEN_RISK_WARNING_PCT else "📊"
    return f"{marker} Dit zou je totale open risico op {open_risk_pct:.1f}% van je portfolio brengen."


def is_quiet_now(quiet_hours_start: Optional[str], quiet_hours_end: Optional[str]) -> bool:
    """Bepaalt of het nu binnen de stille uren van de gebruiker valt
    (bijvoorbeeld "23:00" tot "07:00", ook een venster dat over middernacht
    heen loopt). Gebruikt de servertijd, er wordt geen tijdzone per
    gebruiker bijgehouden. Beide velden leeg (None) betekent geen stille
    uren ingesteld, dan altijd False."""
    if not quiet_hours_start or not quiet_hours_end:
        return False
    try:
        start = datetime.strptime(quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(quiet_hours_end, "%H:%M").time()
    except ValueError:
        return False
    now = datetime.now().time()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


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
        _progress_bar(signal["price"], signal["stop_loss"], signal["take_profit"], signal["direction"]),
        DIVIDER,
    ]
    if signal.get("plain_explanation"):
        lines += [signal["plain_explanation"], ""]
    lines.append(signal["reason"])
    if signal.get("context_note"):
        lines += ["", signal["context_note"]]
    if signal.get("open_risk_pct") is not None:
        lines += ["", _open_risk_line(signal["open_risk_pct"])]
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
            _progress_bar(signal["price"], signal["stop_loss"], signal["take_profit"], signal["direction"]),
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


async def send_signal_update(signal: dict, chat_id: str, force_silent: bool = False) -> None:
    """Kort bericht als een bestaand, nog openstaand signaal is bijgewerkt
    door een nieuw bericht over dezelfde coin en richting. force_silent
    (stille uren van de gebruiker) onderdrukt geluid ook bij een
    bevestigde kans."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, update niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_update_message(signal)
    silent = force_silent or not signal["technical_confirmed"]
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=silent)
    logger.info("Telegram update verstuurd voor %s %s naar chat %s",
                signal["coin"], signal["direction"], chat_id)


async def send_signal(signal: dict, chat_id: str, force_silent: bool = False) -> None:
    """Verstuurt de melding naar één specifieke chat ID. Elke gebruiker heeft
    zijn eigen chat ID en dus zijn eigen risicobedrag in het bericht. Ook een
    afgewezen tip krijgt een bericht (format_rejected_message), stilte voelt
    voor de gebruiker aan als "er is niks gebeurd" in plaats van "getoetst en
    afgekeurd, met reden". force_silent komt van de stille-uren instelling
    van de gebruiker (zie is_quiet_now): onderdrukt geluid ook bij een
    bevestigde kans, die blijft normaal wel geluid geven."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, melding niet verstuurd")
        return

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    confirmed = signal["technical_confirmed"]
    text = format_signal_message(signal) if confirmed else format_rejected_message(signal)
    # Een bevestigde kans mag geluid maken, een afwijzing niet: sinds elke
    # tip een bericht krijgt (ook een "geen kans"), zou anders elke deling
    # in de bron-community de telefoon laten afgaan, ook als er niks te
    # doen valt. Tenzij de gebruiker nu in zijn eigen stille uren zit, dan
    # blijft ook een bevestigde kans stil, hij ziet hem 's ochtends wel.
    silent = force_silent or not confirmed
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=silent)
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


async def send_demo_signal_message(chat_id: str) -> None:
    """Stuurt een voorbeeldmelding, in exact dezelfde opmaak als een echte
    bevestigde kans, zodat een nieuwe gebruiker meteen ziet hoe dat eruit
    ziet zonder op een echt signaal te hoeven wachten. Duidelijk gelabeld
    als voorbeeld, en maakt geen signaal of logboekregel aan: telt nergens
    mee in de echte statistieken (ook niet in de onboarding-checklist, die
    kijkt naar journal_entries.telegram_sent van een echt signaal)."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        return
    demo_signal = {
        "coin": "BTC", "direction": "long", "confidence": "hoog vertrouwen",
        "price": 61250.0, "take_profit": 63400.0, "stop_loss": 60100.0,
        "technical_confirmed": 1,
        "reason": "✓ Trend: EMA9 boven EMA21 | ✓ Momentum: MACD boven signaallijn | ✓ RSI 58 | ✓ Volume 1.34x gemiddeld",
        "context_note": None,
        "plain_explanation": (
            "De trend wijst omhoog en het momentum bevestigt dit: de prijs "
            "beweegt sterker dan de laatste 20 candles gebruikelijk was."
        ),
        "open_risk_pct": 3.2,
    }
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = f"📋 VOORBEELDMELDING, zo ziet een echte kans eruit\n{DIVIDER}\n\n{format_signal_message(demo_signal)}"
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=True)
    logger.info("Voorbeeldmelding verstuurd naar chat %s", chat_id)


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
