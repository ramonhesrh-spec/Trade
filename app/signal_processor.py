"""Verwerkingspijplijn: interpretatie via Anthropic, technische toetsing
voor day trading berichten, risicomanagement en Telegram melding.

Dit systeem voert geen trades uit. Het geeft een melding op basis van
regels. Elke trade blijft een handmatige beslissing.
"""
import asyncio
import logging

from app import coinlist, exchange, indicators, repo, risk, telegram_notify
from app.anthropic_interpret import Interpretation, interpret_message

logger = logging.getLogger("signal_processor")


async def handle_message(message_id: int, raw_text: str, image_paths: list[str]) -> None:
    interp = await asyncio.to_thread(interpret_message, raw_text, image_paths)

    repo.mark_message_processed(message_id, interp.coin, interp.direction, interp.category, interp.unclear)

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


async def process_day_trading_signal(message_id: int, interp: Interpretation) -> None:
    tracked = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
    if not tracked:
        logger.info("Coin %s bestaat niet als paar op de exchange, geen technische toetsing mogelijk",
                    interp.coin)
        return

    df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin)
    ind = indicators.compute_indicators(df)
    confirmed, reason = indicators.confirms_direction(ind, interp.direction)
    stop_take = risk.compute_stop_take(interp.direction, ind.price, ind.atr)

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
        "technical_confirmed": int(confirmed),
        "confidence": confidence,
        "reason": reason,
        "stop_loss": stop_take.stop_loss,
        "take_profit": stop_take.take_profit,
    }
    signal_id = repo.insert_signal(signal_data)
    logger.info("Signaal %s opgeslagen: %s %s, bevestigd=%s", signal_id, interp.coin,
                interp.direction, confirmed)

    # Elke gebruiker krijgt zijn eigen logboekregel en zijn eigen Telegram
    # melding, met een risicobedrag op basis van zijn eigen portfolio.
    for user in repo.list_users():
        risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)

        if not user["telegram_chat_id"]:
            logger.info("Gebruiker %s heeft geen telegram_chat_id, geen melding verstuurd",
                        user["username"])
            continue

        try:
            await telegram_notify.send_signal({**signal_data, "risk_eur": risk_eur},
                                               chat_id=user["telegram_chat_id"])
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Telegram melding voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
