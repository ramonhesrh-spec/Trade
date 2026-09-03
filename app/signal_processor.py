"""Verwerkingspijplijn: interpretatie via Anthropic, technische toetsing
voor day trading berichten, risicomanagement en Telegram melding.

Dit systeem voert geen trades uit. Het geeft een melding op basis van
regels. Elke trade blijft een handmatige beslissing.
"""
import asyncio
import logging
import time

from app import coinlist, config, exchange, indicators, repo, risk, telegram_notify
from app.anthropic_interpret import Interpretation, interpret_message

logger = logging.getLogger("signal_processor")

INTERPRET_ATTEMPTS = 3
INTERPRET_BACKOFF_SECONDS = 3


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

    try:
        interp = await asyncio.to_thread(_interpret_with_retry, raw_text, image_paths)
    except Exception as exc:
        logger.exception("Interpretatie van bericht %s definitief mislukt na %s pogingen",
                          message_id, INTERPRET_ATTEMPTS)
        repo.mark_message_processed(
            message_id, None, None, None, True,
            note=f"API fout, kon niet verwerkt worden: {exc}",
        )
        return

    repo.mark_message_processed(message_id, interp.coin, interp.direction, interp.category,
                                 interp.unclear, note=interp.reason)

    if interp.unclear:
        logger.info("Bericht %s is onduidelijk (%s), overgeslagen voor verdere verwerking",
                    message_id, interp.reason)
        return

    # Bron niveaus uit afbeeldingen worden altijd bewaard, ongeacht categorie.
    if interp.source_levels:
        tracked = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
        if tracked:
            for level in interp.source_levels:
                repo.insert_source_level(message_id, interp.coin, level.price_level, level.pattern_name)
        else:
            logger.info("Coin %s uit bron niveaus bestaat niet op de exchange, niveaus niet bewaard",
                        interp.coin)

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


async def process_day_trading_signal(message_id: int, interp: Interpretation) -> None:
    tracked = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
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
    }
    existing = repo.find_open_signal(interp.coin, interp.direction)

    if existing:
        signal_id = existing["id"]
        repo.update_signal(signal_id, signal_data)
        logger.info("Signaal %s bijgewerkt (was al open voor %s %s), bevestigd=%s",
                    signal_id, interp.coin, interp.direction, confirmed)
        if confirmed:
            await _notify_signal_update(signal_id, signal_data, ind.price, stop_take.stop_loss)
        else:
            logger.info("Signaal %s is laag vertrouwen, geen Telegram update verstuurd", signal_id)
        return

    signal_id = repo.insert_signal(signal_data)
    logger.info("Signaal %s opgeslagen: %s %s, bevestigd=%s", signal_id, interp.coin,
                interp.direction, confirmed)

    # Elke gebruiker krijgt zijn eigen logboekregel, ongeacht vertrouwen, zo
    # blijft de trackrecord per vertrouwen-niveau compleet. Telegram is
    # alleen voor hoog vertrouwen, dat zijn de enige "perfecte setups".
    for user in repo.list_users():
        risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)

        if not confirmed:
            continue
        if not user["telegram_chat_id"]:
            logger.info("Gebruiker %s heeft geen telegram_chat_id, geen melding verstuurd",
                        user["username"])
            continue

        position_size = risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss)
        try:
            await telegram_notify.send_signal(
                {**signal_data, "risk_eur": risk_eur, "position_size": position_size},
                chat_id=user["telegram_chat_id"],
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Telegram melding voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
    if not confirmed:
        logger.info("Signaal %s is laag vertrouwen, geen Telegram melding verstuurd", signal_id)


async def _notify_signal_update(signal_id: int, signal_data: dict, price: float, stop_loss: float) -> None:
    """Stuurt een korte update-melding naar gebruikers die dit signaal nog
    open hebben staan. Maakt geen nieuwe logboekregel aan, die bestaat al."""
    entries = {e["user_id"]: e for e in repo.list_journal_entries_for_signal(signal_id)}
    for user in repo.list_users():
        entry = entries.get(user["id"])
        if not entry or entry["exit_price"] is not None or not user["telegram_chat_id"]:
            continue
        try:
            await telegram_notify.send_signal_update(signal_data, chat_id=user["telegram_chat_id"])
        except Exception:
            logger.exception("Telegram update voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
