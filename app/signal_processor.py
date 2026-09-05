"""Verwerkingspijplijn: interpretatie via Anthropic, technische toetsing
voor day trading berichten, risicomanagement en Telegram melding.

Dit systeem voert geen trades uit. Het geeft een melding op basis van
regels. Elke trade blijft een handmatige beslissing.
"""
import asyncio
import logging
import time

from app import chart_image, coinlist, config, exchange, explain, indicators, repo, risk, telegram_notify
from app.anthropic_interpret import Interpretation, interpret_message

logger = logging.getLogger("signal_processor")

INTERPRET_ATTEMPTS = 3
INTERPRET_BACKOFF_SECONDS = 3

# Hoeveel een afgelezen niveau uit een screenshot maximaal van de live prijs
# mag afwijken (als fractie van de live prijs) om nog als aannemelijk te
# gelden. Een decimale leesfout of een niveau van een heel ander tijdvak
# levert al snel een niveau tientallen procenten van de huidige prijs af,
# een echt support/weerstand niveau ligt daar in de praktijk altijd binnen.
SOURCE_LEVEL_MAX_DISTANCE_RATIO = 0.5

# Hoeveel opeenvolgende afwijzingen op dezelfde coin nodig zijn voor de
# "dit valt steeds op dezelfde factor" leeruitleg. 3 is geen toeval meer,
# 2 kan nog puur toeval zijn.
REPEATED_REJECTION_COUNT = 3

# Hoeveel opeenvolgende, definitief mislukte Anthropic-interpretaties (elk
# al 3x geprobeerd, zie INTERPRET_ATTEMPTS) nodig zijn voor een alert naar
# de beheerder. Eén hapering kan de API zelf zijn, meerdere berichten op
# rij wijst op iets structureels (API-sleutel, quotum, een storing).
# In-memory, dus reset bij een herstart van het proces, dat is prima: een
# herstart is zelf al een schone start.
INTERPRET_FAILURE_ALERT_THRESHOLD = 3
_consecutive_interpret_failures = 0


def _extract_failing_factors(reason: str) -> set[str]:
    """Haalt de factornamen met een ✗ uit een reason-breakdown zoals
    indicators.confirms_direction die opbouwt ("✓ Trend: ... | ✗ Volume: ...")."""
    factors = set()
    for part in reason.split(" | "):
        part = part.strip()
        if part.startswith("✗"):
            factors.add(part[1:].split(":", 1)[0].strip())
    return factors


def _repeated_failing_factor(coin: str) -> str | None:
    """Als de laatste REPEATED_REJECTION_COUNT afwijzingen voor deze coin
    allemaal op dezelfde factor vallen, geeft die factornaam terug, anders
    None. Minder dan dat aantal afwijzingen in de geschiedenis is nog geen
    patroon, gewoon te weinig data."""
    reasons = repo.recent_rejected_reasons(coin, limit=REPEATED_REJECTION_COUNT)
    if len(reasons) < REPEATED_REJECTION_COUNT:
        return None
    failing_sets = [_extract_failing_factors(r) for r in reasons]
    common = set.intersection(*failing_sets)
    return next(iter(common)) if common else None


def _interpret_with_retry(raw_text: str, image_paths: list[str]) -> Interpretation:
    """Probeert de Anthropic interpretatie een paar keer bij een tijdelijke
    fout (timeout, overbelasting), voordat het bericht als mislukt wordt
    gelogd in plaats van stil onverwerkt te blijven."""
    last_exc: Exception | None = None
    for attempt in range(1, INTERPRET_ATTEMPTS + 1):
        try:
            return interpret_message(raw_text, image_paths)
        except Exception as exc:
            last_exc = exc
            logger.warning("Anthropic interpretatie poging %s/%s mislukt: %s",
                            attempt, INTERPRET_ATTEMPTS, exc)
            if attempt < INTERPRET_ATTEMPTS:
                time.sleep(INTERPRET_BACKOFF_SECONDS * attempt)
    raise last_exc


async def handle_message(message_id: int, raw_text: str, image_paths: list[str]) -> None:
    duplicate = repo.find_recent_duplicate(raw_text, exclude_id=message_id) if raw_text.strip() else None
    if duplicate:
        logger.info("Bericht %s is een duplicaat van bericht %s, niet opnieuw verwerkt",
                    message_id, duplicate["id"])
        repo.mark_message_processed(
            message_id, duplicate["coin"], duplicate["direction"], duplicate["category"],
            bool(duplicate["unclear"]), note=f"duplicaat van bericht #{duplicate['id']}, niet opnieuw verwerkt",
        )
        return

    global _consecutive_interpret_failures
    try:
        interp = await asyncio.to_thread(_interpret_with_retry, raw_text, image_paths)
    except Exception as exc:
        logger.exception("Interpretatie van bericht %s definitief mislukt na %s pogingen",
                          message_id, INTERPRET_ATTEMPTS)
        repo.mark_message_processed(
            message_id, None, None, None, True,
            note=f"API fout, kon niet verwerkt worden: {exc}",
        )
        _consecutive_interpret_failures += 1
        if _consecutive_interpret_failures >= INTERPRET_FAILURE_ALERT_THRESHOLD:
            try:
                await telegram_notify.send_admin_alert(
                    f"🚨 Anthropic interpretatie is nu {_consecutive_interpret_failures} berichten op rij "
                    f"mislukt. Check de serverlog en de API-status.\n\nLaatste fout: {exc}"
                )
            except Exception:
                logger.exception("Kon admin-alert voor herhaalde API-fouten niet versturen")
        return

    _consecutive_interpret_failures = 0
    repo.mark_message_processed(message_id, interp.coin, interp.direction, interp.category,
                                 interp.unclear, note=interp.reason)

    if interp.unclear:
        logger.info("Bericht %s is onduidelijk (%s), overgeslagen voor verdere verwerking",
                    message_id, interp.reason)
        return

    # Bron niveaus uit afbeeldingen worden altijd bewaard, ongeacht categorie.
    if interp.source_levels:
        tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
        if is_new_coin:
            await _notify_new_coin(interp.coin)
        if not tracked:
            logger.info("Coin %s uit bron niveaus bestaat niet op de exchange, niveaus niet bewaard",
                        interp.coin)
        else:
            live_price = None
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
            except Exception:
                logger.exception("Live prijs voor %s kon niet opgehaald worden, niveaus zonder aannemelijkheidscheck bewaard",
                                  interp.coin)
            for level in interp.source_levels:
                if live_price and abs(level.price_level - live_price) / live_price > SOURCE_LEVEL_MAX_DISTANCE_RATIO:
                    logger.warning(
                        "Niveau %.4f voor %s ligt te ver van de live prijs %.4f, waarschijnlijk verkeerd afgelezen, niet bewaard",
                        level.price_level, interp.coin, live_price,
                    )
                    continue
                repo.insert_source_level(message_id, interp.coin, level.price_level, level.pattern_name)

    if interp.category != "day_trading":
        logger.info("Bericht %s valt in categorie %s, alleen gelogd, geen melding",
                    message_id, interp.category)
        return

    await process_day_trading_signal(message_id, interp)


def _build_context_note(coin: str, direction: str) -> str:
    """Zet dit signaal af tegen het meest recente lange termijn bericht over
    dezelfde coin. Verandert niets aan het hoog/laag vertrouwen label, dat
    blijft puur op de vier technische factoren gebaseerd, dit is extra
    achtergrond die meegaat in de melding."""
    latest = repo.latest_long_term_direction(coin)
    if not latest:
        return ""

    when = latest["received_at"][:10]
    if latest["direction"] == "neutraal":
        return (f"Let op: recente lange termijn analyse is verdeeld over deze coin, "
                f"geen duidelijke richting ({when}). Dit signaal staat op zichzelf.")
    if latest["direction"] == direction.lower():
        return f"Sluit aan bij recente lange termijn analyse ({direction}, {when})."
    return (f"Let op: recente lange termijn analyse wijst op "
            f"{latest['direction']}, dit signaal wijkt daarvan af ({when}).")


async def compute_advanced_extra_factors(coin: str, direction: str, df) -> list[tuple[str, bool, str]]:
    """Berekent de losse checks voor de uitgebreide factorenset (BTC-trend,
    1u bevestiging, divergentie, liquiditeit). Elke check faalt individueel
    en "fail-closed" als de data ervoor niet op te halen is: beter een
    factor die ten onrechte op ✗ staat door een netwerkhapering, dan een
    hoog-vertrouwen melding die stilzwijgend op onvolledige data steunt."""
    factors: list[tuple[str, bool, str]] = []

    if coin.upper() != "BTC":
        try:
            btc_df = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC")
            btc_ind = indicators.compute_indicators(btc_df)
            factors.append(indicators.check_btc_trend(direction, btc_ind))
        except Exception:
            logger.exception("BTC-trend kon niet berekend worden")
            factors.append(("BTC-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        df_1h = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1h")
        ind_1h = indicators.compute_indicators(df_1h)
        factors.append(indicators.check_1h_trend(direction, ind_1h))
    except Exception:
        logger.exception("1u bevestiging voor %s kon niet berekend worden", coin)
        factors.append(("1u bevestiging", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_divergence(df, direction))
    except Exception:
        logger.exception("Divergentiecheck voor %s kon niet berekend worden", coin)
        factors.append(("Divergentie", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        quote_volume = await asyncio.to_thread(exchange.fetch_24h_quote_volume, coin)
        factors.append(indicators.check_liquidity(quote_volume))
    except Exception:
        logger.exception("Liquiditeitscheck voor %s kon niet berekend worden", coin)
        factors.append(("Liquiditeit", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    return factors


async def _notify_new_coin(coin: str) -> None:
    """Kort bericht naar elke gebruiker met een gekoppelde Telegram chat
    zodra een coin voor het eerst ooit gezien wordt. Groei van de
    dynamische coinlijst was tot nu toe volledig stil, alleen in de log."""
    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        try:
            await telegram_notify.send_new_coin_message(coin, chat_id=user["telegram_chat_id"])
        except Exception:
            logger.exception("Nieuwe-coin melding voor %s naar gebruiker %s is mislukt",
                              coin, user["username"])


async def process_day_trading_signal(message_id: int, interp: Interpretation) -> None:
    tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
    if is_new_coin:
        await _notify_new_coin(interp.coin)
    if not tracked:
        logger.info("Coin %s bestaat niet als paar op de exchange, geen technische toetsing mogelijk",
                    interp.coin)
        return

    df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(interp.coin, interp.direction, df)

    confirmed, reason = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
    stop_take = risk.compute_stop_take(
        interp.direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high,
    )
    context_note = _build_context_note(interp.coin, interp.direction)

    confidence = "hoog vertrouwen" if confirmed else "laag vertrouwen"

    plain_explanation = await asyncio.to_thread(
        explain.explain_signal, interp.coin, interp.direction, confidence, reason,
        ind.price, stop_take.stop_loss, stop_take.take_profit,
    )

    # Alleen zinvol bij een afwijzing: hetzelfde patroon melden bij een
    # bevestigde kans zou de indruk wekken dat er iets mis is terwijl het
    # juist goed uitpakte.
    repeated_factor = None if confirmed else await asyncio.to_thread(_repeated_failing_factor, interp.coin)

    # Eén keer gegenereerd voor iedereen, niet per gebruiker: de grafiek
    # zelf verschilt niet per ontvanger. Alleen bij een bevestigde kans,
    # een afwijzing heeft geen stop loss/take profit om te tekenen. Een
    # mislukte generatie mag de al verstuurde tekstmelding nooit blokkeren.
    chart_bytes = None
    if confirmed:
        try:
            chart_bytes = await asyncio.to_thread(
                chart_image.render_signal_chart, df, interp.direction, stop_take.stop_loss, stop_take.take_profit,
            )
        except Exception:
            logger.exception("Kon geen chart genereren voor %s", interp.coin)

    signal_data = {
        "message_id": message_id,
        "coin": interp.coin,
        "direction": interp.direction,
        "category": interp.category,
        "price": ind.price,
        "rsi": ind.rsi,
        "macd": ind.macd,
        "macd_signal": ind.macd_signal,
        "volume_ratio": ind.volume_ratio,
        "ema9": ind.ema9,
        "ema21": ind.ema21,
        "atr": ind.atr,
        "atr_avg20": ind.atr_avg20,
        "adx": ind.adx,
        "technical_confirmed": int(confirmed),
        "confidence": confidence,
        "reason": reason,
        "stop_loss": stop_take.stop_loss,
        "take_profit": stop_take.take_profit,
        "context_note": context_note or None,
        "plain_explanation": plain_explanation or None,
        "repeated_factor": repeated_factor,
    }
    # Een nog niet genomen melding voor de tegenovergestelde richting van
    # dezelfde coin is achterhaald zodra hier een nieuwe melding binnenkomt:
    # je kan niet serieus tegelijk long en short op dezelfde coin overwegen.
    # Een al genomen trade (eigen entry al ingevuld) is een echte positie en
    # blijft hier altijd buiten schot.
    ignored = repo.auto_ignore_opposite_pending(interp.coin, interp.direction)
    if ignored:
        logger.info("%s nog niet genomen tegenovergestelde melding(en) voor %s automatisch genegeerd",
                     len(ignored), interp.coin)
        for user in ignored:
            if not user["telegram_chat_id"]:
                continue
            try:
                await telegram_notify.send_expired_pending_message(
                    interp.coin, interp.direction, chat_id=user["telegram_chat_id"],
                )
            except Exception:
                logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt",
                                  interp.coin, user["username"])

    existing = repo.find_open_signal(interp.coin, interp.direction)

    if existing:
        signal_id = existing["id"]
        repo.update_signal(signal_id, signal_data)
        logger.info("Signaal %s bijgewerkt (was al open voor %s %s), bevestigd=%s",
                    signal_id, interp.coin, interp.direction, confirmed)
        await _notify_signal_update(signal_id, signal_data)
        return

    signal_id = repo.insert_signal(signal_data)
    logger.info("Signaal %s opgeslagen: %s %s, bevestigd=%s", signal_id, interp.coin,
                interp.direction, confirmed)

    # Elke gebruiker krijgt zijn eigen logboekregel, ongeacht vertrouwen, zo
    # blijft de trackrecord per vertrouwen-niveau compleet. Ook een afgewezen
    # tip krijgt een Telegram bericht (zonder stop loss/take profit/grootte,
    # dat is geen uitvoerbare trade opzet), anders voelt stilte aan als "er
    # is niks gebeurd" in plaats van "getoetst, met deze reden afgekeurd".
    for user in repo.list_users():
        risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)

        if not user["telegram_chat_id"]:
            logger.info("Gebruiker %s heeft geen telegram_chat_id, geen melding verstuurd",
                        user["username"])
            continue

        position_size = risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss) if confirmed else None

        # Alleen bij een bevestigde kans zinvol: een afwijzing is toch geen
        # trade die risico toevoegt. Toont waar het TOTALE open risico
        # zou uitkomen als deze kans ook genomen wordt, niet alleen het
        # risicobedrag van deze ene trade op zich.
        open_risk_pct = None
        if confirmed and user["portfolio_eur"]:
            current_open_risk = repo.total_open_risk_eur(user["id"])
            open_risk_pct = (current_open_risk + risk_eur) / user["portfolio_eur"] * 100

        # Inclusief deze nieuwe kans zelf (net aangemaakt met status 'nieuw').
        # Bij precies 1 is dit de enige, geen samenvattingsregel nodig.
        pending_count = repo.count_pending_signals(user["id"])

        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_signal(
                {
                    **signal_data, "risk_eur": risk_eur, "position_size": position_size,
                    "open_risk_pct": open_risk_pct, "pending_count": pending_count,
                },
                chat_id=user["telegram_chat_id"], force_silent=force_silent, entry_id=entry_id,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Telegram melding voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
            continue

        if chart_bytes:
            try:
                await telegram_notify.send_signal_chart(
                    chart_bytes, interp.coin, interp.direction, chat_id=user["telegram_chat_id"],
                )
            except Exception:
                logger.exception("Chart versturen voor gebruiker %s, signaal %s is mislukt",
                                  user["username"], signal_id)


async def _notify_signal_update(signal_id: int, signal_data: dict) -> None:
    """Stuurt een update-melding naar gebruikers die dit signaal nog open
    hebben staan, bevestigd of niet: een gewijzigde toetsing op een nieuw
    bericht over dezelfde coin is altijd het melden waard. Maakt geen nieuwe
    logboekregel aan, die bestaat al."""
    entries = {e["user_id"]: e for e in repo.list_journal_entries_for_signal(signal_id)}
    for user in repo.list_users():
        entry = entries.get(user["id"])
        if not entry or entry["exit_price"] is not None or not user["telegram_chat_id"]:
            continue
        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_signal_update(
                signal_data, chat_id=user["telegram_chat_id"], force_silent=force_silent,
            )
        except Exception:
            logger.exception("Telegram update voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
