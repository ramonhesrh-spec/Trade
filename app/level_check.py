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

from datetime import datetime, timedelta, timezone

from app import db, exchange, indicators, push_notify, repo
from app.signal_processor import (
    SWING_WATCH_MAX_AGE_DAYS, _price_broke_through, _price_near_level, run_swing_check,
)

logger = logging.getLogger("level_check")

# Hoe lang een day-trading signaal zonder vastgestelde uitkomst blijft
# meedraaien in de automatische trackrecord-check voor het als "vervallen"
# telt in plaats van "nog open". Day trading draait hier op 4-uurs candles
# en is bedoeld om zich binnen uren tot een paar dagen te ontwikkelen, dus
# 14 dagen is al ruim: genoeg marge voor een trage markt of een meerdaagse
# positie, maar nog altijd ver onder de maanden waarin een oud, allang niet
# meer relevant signaal anders alsnog willekeurig een win of loss zou
# scoren zodra de prijs er per toeval doorheen zwabbert. Bewust veel korter
# dan SWING_WATCH_MAX_AGE_DAYS (84): swing-niveaus bewaken een structureel
# support/weerstand-niveau over weken tot maanden, day trading niet.
SIGNAL_MAX_AGE_DAYS = 14

# Hoe dicht de prijs bij het oorspronkelijke signaalniveau moet komen voordat
# een nog niet genomen signaal een "weer interessant" seintje krijgt. In ATR,
# dezelfde maatstaf als de stop-afstand, zodat het meebeweegt met hoe
# volatiel de coin is in plaats van een vast percentage voor elke coin.
PENDING_LEVEL_ATR_MULTIPLIER = 0.5

# Een vers signaal staat per definitie op de prijs waarop het net ontstond,
# dus zonder ondergrens vuurt "terug bij signaalniveau" bijna meteen na de
# eerste melding zelf, elke 15 minuten opnieuw zolang de prijs niet wegloopt
# — geen "terug", gewoon nog niet weg geweest. Pas na deze minimumleeftijd
# telt dichtbij-zijn als een echte terugkeer. Ruim boven de 15 minuten
# cyclus van deze check en de 60 minuten van de marktscan, zodat een signaal
# altijd minstens één volle marktscan-cyclus de kans heeft gehad om weg te
# bewegen voor dit seintje kan afgaan.
PENDING_LEVEL_MIN_AGE_MINUTES = 90


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

        # Geen telegram_chat_id-gate meer hier (Taak 11): push_notify.send_push
        # slaat een gebruiker zonder push-abonnement zelf al stilzwijgend over,
        # en telegram_chat_id wordt sinds de overstap naar push nooit meer
        # ingevuld voor nieuwe gebruikers, dus zou hier iedereen overslaan.
        hit_emoji = "🎯" if hit == "take profit" else "🛑"
        title = f"{hit_emoji} {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
        body = f"{hit.capitalize()} geraakt · Entry {entry['entry_price']:.4f} · Nu {current_price:.4f}"
        silent = push_notify.is_quiet_now(entry["quiet_hours_start"], entry["quiet_hours_end"])
        try:
            await push_notify.send_push(entry["user_id"], title, body, f"/coins/{coin}", silent=silent)
            logger.info("Seintje verstuurd naar %s voor %s (%s)", entry["username"], coin, hit)
        except Exception:
            logger.exception("Seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])


async def check_signal_outcomes() -> None:
    """Volledig automatisch trackrecord: voor elk signaal waarvan de
    uitkomst nog niet vaststaat, checkt dit of de live prijs inmiddels de
    take-profit of de stop-loss geraakt heeft. Onafhankelijk van of een
    gebruiker het signaal ooit als "genomen" markeerde — dit is precies
    waarom het trackrecord niet meer van een handmatige actie afhangt."""
    signals = repo.list_unresolved_signals_with_levels()
    logger.info("%d signalen zonder vastgestelde uitkomst om te checken", len(signals))

    coin_prices: dict[str, float] = {}
    for signal in signals:
        coin = signal["coin"]
        if coin not in coin_prices:
            try:
                coin_prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
            except Exception:
                logger.exception("Kon geen live prijs ophalen voor %s, sla over", coin)
                coin_prices[coin] = None
        current_price = coin_prices[coin]
        if current_price is None:
            continue

        hit = _level_hit(signal["direction"], current_price, signal["stop_loss"], signal["take_profit"])
        if hit:
            outcome = "take_profit" if hit == "take profit" else "stop_loss"
            occurred_at = db.now_iso()
            repo.mark_signal_auto_outcome(signal["id"], outcome, occurred_at)
            # Een zelf-gedetecteerde zone die net een stop loss veroorzaakte
            # gaat op cooldown (zie repo.recent_sr_zone_failure) zodat een
            # volgend signaal vlakbij dezelfde rand niet meteen dezelfde fout
            # herhaalt. Bron-niveaus uit een gedeeld screenshot tellen hier
            # niet mee: die komen niet uit onze eigen zone-detectie.
            if outcome == "stop_loss" and signal["nearest_sr_zone_price"] is not None:
                repo.record_sr_zone_failure(
                    signal["coin"], signal["direction"], signal["nearest_sr_zone_price"], occurred_at,
                )
            logger.info("Signaal %s (%s) automatisch afgesloten: %s", signal["id"], coin, outcome)
            continue

        created_at = datetime.fromisoformat(signal["created_at"])
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days > SIGNAL_MAX_AGE_DAYS:
            repo.mark_signal_auto_outcome(signal["id"], "vervallen", db.now_iso())
            logger.info("Signaal %s (%s) vervallen na %s dagen zonder uitkomst", signal["id"], coin, age_days)


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

        signal_age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["signal_created_at"])
        at_signal_level = (
            signal_age >= timedelta(minutes=PENDING_LEVEL_MIN_AGE_MINUTES)
            and entry["signal_price"] is not None
            and abs(current_price - entry["signal_price"]) <= entry["atr"] * PENDING_LEVEL_ATR_MULTIPLIER
        )

        matched_level = None
        if not at_signal_level:
            if coin not in coin_levels:
                coin_levels[coin] = repo.list_source_levels(coin)
            matched_level = _nearest_level(current_price, entry["atr"], coin_levels[coin])

        if not at_signal_level and not matched_level:
            continue

        # Zie de gelijknamige why-comment in check_open_trades hierboven:
        # geen telegram_chat_id-gate meer, push_notify.send_push handelt een
        # gebruiker zonder push-abonnement zelf al af.
        if matched_level:
            level_desc = f"{matched_level['price_level']}"
            if matched_level["pattern_name"]:
                level_desc += f" ({matched_level['pattern_name']})"
            level_line = f"Bron niveau: {level_desc}"
        else:
            level_line = f"Signaalniveau: {entry['signal_price']:.4f}"

        title = f"🔔 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
        body = f"Terug bij een interessant niveau ({entry['confidence']}) · {level_line} · Nu {current_price:.4f}"
        silent = push_notify.is_quiet_now(entry["quiet_hours_start"], entry["quiet_hours_end"])
        try:
            await push_notify.send_push(entry["user_id"], title, body, f"/coins/{coin}", silent=silent)
            logger.info("Niveau-seintje verstuurd naar %s voor %s", entry["username"], coin)
        except Exception:
            logger.exception("Niveau-seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])


async def check_swing_watches() -> None:
    """Elke "wachtende" bewaakte niveau-watch: is de prijs nu dichtbij
    genoeg om de volledige swing-toets te draaien (run_swing_check), is de
    prijs juist met een duidelijke marge in de verkeerde richting door het
    niveau heen gegaan (ongeldig), of is de watch te lang zonder resultaat
    blijven wachten (vervallen)."""
    watches = repo.list_watches_by_status("wachtend")
    logger.info("%d wachtende swing-watches om te checken", len(watches))

    for watch in watches:
        coin = watch["coin"]
        try:
            daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
            daily_ind = indicators.compute_indicators(daily_df)
        except Exception:
            logger.exception("Kon daily data voor %s niet ophalen, watch %s blijft wachtend", coin, watch["id"])
            continue

        if _price_near_level(daily_ind.price, watch["price_level"], daily_ind.atr):
            # Eén watch waarvan de volledige toets faalt mag de rest van de
            # ronde niet meenemen in zijn val: die zouden dan elke 15 minuten
            # opnieuw overgeslagen worden.
            try:
                await run_swing_check(watch["id"])
            except Exception:
                logger.exception(
                    "Swing-toets voor watch %s (%s) is mislukt, watch blijft wachtend voor de volgende ronde",
                    watch["id"], coin,
                )
            continue

        if _price_broke_through(
            watch["direction"], daily_ind.price, watch["price_level"], daily_ind.atr, watch["reference_price"],
        ):
            repo.update_swing_watch_status(watch["id"], "ongeldig")
            logger.info("Swing-watch %s (%s) ongeldig: prijs krachtig door het niveau heen", watch["id"], coin)
            continue

        created_at = datetime.fromisoformat(watch["created_at"])
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days > SWING_WATCH_MAX_AGE_DAYS:
            repo.update_swing_watch_status(watch["id"], "vervallen")
            logger.info("Swing-watch %s (%s) vervallen na %s dagen zonder resultaat", watch["id"], coin, age_days)


async def check_narratives() -> None:
    """Een narrative zonder nieuwe update in SWING_WATCH_MAX_AGE_DAYS dagen
    verloopt vanzelf. Geen prijs-afhankelijkheid zoals bij swing-watches,
    dus geen candle-fetch nodig: puur een leeftijdscheck."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SWING_WATCH_MAX_AGE_DAYS)).isoformat()
    narratives = repo.list_active_narratives()
    expired = [n for n in narratives if n["last_update_at"] < cutoff]
    for n in expired:
        repo.close_narrative(n["id"], "verlopen", f"geen nieuwe update binnen {SWING_WATCH_MAX_AGE_DAYS} dagen")
    if expired:
        logger.info("%d narrative(s) verlopen wegens inactiviteit", len(expired))


async def run_all_checks() -> None:
    await check_open_trades()
    await check_signal_outcomes()
    await check_pending_signals()
    await check_swing_watches()
    await check_narratives()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_all_checks())
