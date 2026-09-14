"""Verwerkingspijplijn: interpretatie via Anthropic, technische toetsing
voor day trading berichten, risicomanagement en Telegram melding.

Dit systeem voert geen trades uit. Het geeft een melding op basis van
regels. Elke trade blijft een handmatige beslissing.
"""
import asyncio
import logging
import time
from typing import Optional

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

# Hoeveel meldingen voor dezelfde coin een gebruiker op rij genegeerd moet
# hebben (zie repo.consecutive_ignored_count) voor de vraag "wil je dit
# uitzetten?". Precies op deze grens gevraagd, niet elke keer erna: anders
# blijft de vraag terugkomen bij elke volgende melding zolang niemand hem
# beantwoordt.
REPEATED_IGNORE_MUTE_THRESHOLD = 5

# Hoe dicht de prijs bij een bewaakt bron-niveau moet komen voordat de
# swing-toets draait, in ATR van de DAILY candle (de structurele
# tijdshorizon van zo'n niveau, zie de spec). Zelfde soort marge als
# level_check.PENDING_LEVEL_ATR_MULTIPLIER gebruikt voor day-trading
# pending-signalen.
SWING_WATCH_ATR_MULTIPLIER = 0.5

# Hoe lang een "wachtende" swing watch actief blijft zonder dat de prijs
# ooit dichtbij kwam, voor hij automatisch vervalt (12 weken).
SWING_WATCH_MAX_AGE_DAYS = 84


def _price_near_level(current_price: float, level_price: float, atr: float) -> bool:
    """Zuivere functie: is de prijs dichtbij genoeg om de volledige
    swing-toets te draaien."""
    return abs(current_price - level_price) <= SWING_WATCH_ATR_MULTIPLIER * atr


def _price_broke_through(
    direction: str, current_price: float, level_price: float, atr: float,
    reference_price: float | None,
) -> bool:
    """Prijs is met een duidelijke marge (dezelfde ATR-marge) door het
    niveau heen gegaan in de verkeerde richting, MAAR alleen als het niveau
    oorspronkelijk aan de kant van de referentieprijs lag waar het als
    steun/weerstand kon "falen": bij long moet het niveau ONDER de
    referentieprijs hebben gelegen (dus functioneerde als support). Lag het
    niveau er juist BOVEN (een resistance die nog benaderd moest worden,
    bijvoorbeeld precies het Ray-scenario), dan is er geen "doorbraak"
    mogelijk in deze zin, dat is gewoon de normale wachtende toestand.
    Geen referentieprijs bekend: nooit invalideren via deze weg, alleen via
    het tijdgebonden verval."""
    margin = SWING_WATCH_ATR_MULTIPLIER * atr
    if direction.lower() == "long":
        if reference_price is None or level_price >= reference_price:
            return False
        return current_price < level_price - margin
    if reference_price is None or level_price <= reference_price:
        return False
    return current_price > level_price + margin


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


def _interpret_with_retry(raw_text: str, image_paths: list[str]) -> list[Interpretation]:
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
        repo.copy_message_coin_results(
            duplicate["id"], message_id,
            f"duplicaat van bericht #{duplicate['id']}, niet opnieuw verwerkt",
        )
        repo.mark_message_envelope_processed(message_id)
        return

    global _consecutive_interpret_failures
    try:
        interpretations = await asyncio.to_thread(_interpret_with_retry, raw_text, image_paths)
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
    for interp in interpretations:
        await _process_one_coin(message_id, raw_text, interp)
    repo.mark_message_envelope_processed(message_id)


async def _process_one_coin(message_id: int, raw_text: str, interp: Interpretation) -> None:
    """Verwerkt de interpretatie voor precies één coin uit een (mogelijk
    multi-coin) bericht: eigen samenvatting, eigen bron-niveaus, eigen
    day-trading-toets of lange-termijn/narrative-pad. Dit is exact de
    logica die vóór de multi-coin-wijziging rechtstreeks in handle_message
    stond, nu geparametriseerd per coin en schrijvend naar
    message_coin_results in plaats van naar messages (zie
    repo.insert_message_coin_result: message_id + coin identificeren samen
    deze rij, meerdere coins uit hetzelfde bericht krijgen elk hun eigen
    rij)."""
    result_id = repo.insert_message_coin_result(
        message_id, interp.coin, interp.direction, interp.category, interp.unclear, note=interp.reason,
    )

    if interp.unclear:
        logger.info("Bericht %s (coin %s) is onduidelijk (%s), overgeslagen voor verdere verwerking",
                    message_id, interp.coin, interp.reason)
        return

    # Het origineel doorgestuurde bericht herschreven in klare taal, los van
    # de technische plain_explanation die pas later (bij een day trading
    # signaal) berekend wordt. Geldt voor beide categorieën: een lange
    # termijn analyse is vaak juist de langste, meest jargon-rijke tekst.
    message_summary = await asyncio.to_thread(explain.summarize_message, interp.coin, raw_text)
    if message_summary:
        repo.set_message_coin_result_summary(result_id, message_summary)

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
                source_level_id = repo.insert_source_level(
                    message_id, interp.coin, level.price_level, level.pattern_name,
                )
                # Alleen voor niet-day_trading categorieën (lange_termijn,
                # aandelen): een day_trading bericht krijgt al volledige,
                # directe, niveau-bewuste behandeling via zijn eigen
                # pijplijn (process_day_trading_signal). Een parallelle
                # swing-watch voor exact hetzelfde bericht voegt niets toe
                # behalve een dubbele melding en dubbel risicobedrag voor
                # dezelfde kans.
                if interp.category != "day_trading":
                    try:
                        await evaluate_level_watch(
                            message_id, interp.coin, interp.direction, source_level_id, level.price_level,
                        )
                    except Exception:
                        logger.exception("Swing-watch evaluatie voor %s (bericht %s) is mislukt",
                                          interp.coin, message_id)

    if interp.category != "day_trading":
        logger.info("Bericht %s (coin %s) valt in categorie %s, alleen gelogd, geen melding",
                    message_id, interp.coin, interp.category)
        # Live koers vastleggen op het moment van deze analyse: zonder dit
        # referentiepunt kan achteraf nooit gemeten worden of de richting
        # klopte (zie repo.coin_long_term_track_record). Mislukt de
        # koersophaal, dan telt deze analyse straks gewoon niet mee in het
        # trackrecord, geen reden om de rest van de verwerking te blokkeren.
        if interp.direction in ("long", "short"):
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
                repo.set_message_coin_result_price_at_receipt(result_id, live_price)
            except Exception:
                logger.exception("Live prijs voor lange-termijn analyse %s kon niet vastgelegd worden",
                                  interp.coin)

        # Tot nu toe volledig stil: je zag een lange termijn analyse pas
        # terug zodra een latere day trading melding voor dezelfde coin
        # ernaar verwees (_build_context_note). Met de samenvatting hierboven
        # is een korte, stille melding hierover goedkoop, en voorkomt dat de
        # inhoud van een net doorgestuurde analyse in de tussentijd onzichtbaar is.
        if interp.category == "lange_termijn" and interp.direction in ("long", "short"):
            try:
                await evaluate_narrative(interp.coin, interp.direction, result_id)
            except Exception:
                logger.exception("Narrative-evaluatie voor %s (bericht %s) is mislukt",
                                  interp.coin, message_id)
        elif message_summary:
            for user in repo.list_users():
                if not user["telegram_chat_id"]:
                    continue
                try:
                    await telegram_notify.send_long_term_message(
                        interp.coin, interp.direction, message_summary,
                        chat_id=user["telegram_chat_id"],
                    )
                except Exception:
                    logger.exception("Lange-termijn melding voor %s naar gebruiker %s is mislukt",
                                      interp.coin, user["username"])
        return

    await process_day_trading_signal(message_id, interp)


async def evaluate_level_watch(
    message_id: int, coin: str, direction: str, source_level_id: int, level_price: float,
) -> None:
    """Aangeroepen voor elk opgeslagen bron-niveau van een bericht in een
    niet-day_trading categorie (lange_termijn, aandelen): maakt een
    swing_watches-regel aan en checkt meteen of de prijs nu al dichtbij
    genoeg is om door te gaan naar de volledige toets. Zo niet, blijft de
    watch "wachtend" en pakt level_check.check_swing_watches() hem later
    periodiek op. Wordt bewust NIET aangeroepen voor day_trading berichten:
    die krijgen hun eigen niveau al direct via process_day_trading_signal
    (zie de trade_type-filter in handle_message hierboven) — een aparte
    swing-watch voor exact hetzelfde bericht zou alleen een dubbele
    melding en dubbel risicobedrag opleveren."""
    if (direction or "").lower() not in ("long", "short"):
        return  # "neutraal" (of None, bv. een lange-termijn niveau zonder
        # duidelijke richting) heeft geen kant om een niveau tegen te toetsen
    existing = [w for w in repo.active_swing_watches_for_coin(coin) if w["direction"] == direction.lower()]
    if existing:
        logger.info(
            "Al een wachtende swing-watch voor %s %s (watch %s), geen nieuwe aangemaakt voor bericht %s",
            coin, direction, existing[0]["id"], message_id,
        )
        return
    watch_id = repo.create_swing_watch(message_id, source_level_id, coin, direction)
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
    except Exception:
        logger.exception("Kon daily data voor %s niet ophalen, watch %s blijft wachtend", coin, watch_id)
        return
    daily_ind = indicators.compute_indicators(daily_df)
    if _price_near_level(daily_ind.price, level_price, daily_ind.atr):
        await run_swing_check(watch_id)


async def evaluate_narrative(coin: str, direction: str, result_id: int) -> None:
    """Aangeroepen voor elk lange_termijn-bericht met een duidelijke
    richting (long/short — 'neutraal' en een ontbrekende richting doen
    hier niet aan mee, net als bij _build_context_note). Bepaalt of dit
    bericht een update is van het lopende verhaal over deze coin, een
    tegenspraak daarvan, of het begin van een nieuw verhaal. `result_id` is
    het id van de message_coin_results-rij voor DEZE coin (niet het
    message_id): met meerdere coins per bericht delen ze hetzelfde
    message_id, dus de narrative-koppeling moet coin-gescopet blijven (zie
    repo.create_narrative/update_narrative_progress).

    Tegenspraak sluit het oude narrative expliciet af (status
    'tegengesproken') vóór er een nieuwe wordt aangemaakt: er hoort op elk
    moment hoogstens één actief narrative per coin te zijn, ongeacht welke
    richting."""
    if direction not in ("long", "short"):
        return

    active = repo.get_active_narrative(coin)
    if active is None:
        narrative_id = repo.create_narrative(coin, direction, result_id)
        await _send_narrative_notifications(narrative_id, is_new=True, is_contradiction=False)
        return

    if active["direction"] == direction:
        repo.update_narrative_progress(active["id"], result_id)
        await _send_narrative_notifications(active["id"], is_new=False, is_contradiction=False)
        return

    repo.close_narrative(
        active["id"], "tegengesproken",
        f"tegengesproken door een nieuw {direction}-narrative voor {coin}",
    )
    new_narrative_id = repo.create_narrative(coin, direction, result_id)
    await _send_narrative_notifications(
        new_narrative_id, is_new=True, is_contradiction=True, contradicted=active,
    )


async def _send_narrative_notifications(
    narrative_id: int, is_new: bool, is_contradiction: bool, contradicted: Optional[dict] = None,
) -> None:
    """Stuurt of bewerkt de narrative-melding voor elke gebruiker met een
    gekoppelde Telegram-chat. Een tegenspraak of het allereerste bericht
    van een narrative heeft nooit een bestaand bericht om te bewerken; een
    update probeert altijd eerst het vorige bericht te bewerken (zie
    telegram_notify.send_narrative_update voor de edit/verse-melding-
    afweging zelf)."""
    narrative = repo.get_narrative(narrative_id)
    timeline = repo.list_narrative_messages(narrative_id)
    contradicted_since = contradicted["opened_at"][:10] if contradicted else None

    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        existing = None if is_new else repo.get_narrative_notification(narrative_id, user["id"])
        existing_message_id = existing["telegram_message_id"] if existing else None
        try:
            # Altijd stil, zoals de oude send_long_term_message ook altijd
            # deed: dit is community-analyse, geen actiegerichte melding
            # (SL/TP-hit, nieuw day-trading-signaal) die een geluidje
            # rechtvaardigt, ongeacht of het net stille uren zijn.
            telegram_message_id = await telegram_notify.send_narrative_update(
                narrative["coin"], narrative["direction"], timeline, user["telegram_chat_id"],
                existing_message_id, is_contradiction, contradicted_since, force_silent=True,
            )
            repo.upsert_narrative_notification(narrative_id, user["id"], telegram_message_id)
        except Exception:
            logger.exception("Narrative-melding voor %s naar gebruiker %s is mislukt",
                              narrative["coin"], user["username"])


def _resolve_signal_risk(
    user: dict, direction: str, entry_price: float, stop_loss: float, take_profit: float,
) -> tuple[float, Optional[int], float, float, float]:
    """Risicobedrag, evaluation_id (of None), cost_rate, en de effectieve
    (mogelijk ingeperkte) stop_loss/take_profit voor één signaal aan één
    gebruiker. Gebruikt de actieve evaluatie als sizing-basis zodra die er
    is en er nog voldoende budget is — inclusief het inperken van de stop
    loss op basis van het evaluatiesaldo (zie risk.apply_eval_stop_cap),
    zodat een klein evaluatiesaldo niet door één te brede
    marktstructuur-stop meteen een groot deel van het dagbudget/de
    drawdown-ruimte kan kosten. Valt anders terug op het bestaande
    portfolio_eur x risk_percent-gedrag met de ONGEWIJZIGDE, gedeelde
    stop_loss/take_profit — exact zoals vóór dit deelproject."""
    active_eval = repo.get_active_evaluation(user["id"])
    if active_eval:
        open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
        if not risk.eval_sizing_blocked(active_eval, open_risk_eur):
            max_pct = risk.eval_max_stop_pct(active_eval["tier_amount"])
            capped = risk.apply_eval_stop_cap(direction, entry_price, stop_loss, take_profit, max_pct)
            risk_eur = risk.compute_eval_risk_eur(
                active_eval, user["risk_percent"], open_risk_eur, entry_price, capped.stop_loss,
            )
            cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
            return risk_eur, active_eval["id"], cost_rate, capped.stop_loss, capped.take_profit
    return risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"]), None, 0.0, stop_loss, take_profit


async def run_swing_check(watch_id: int) -> None:
    """Draait de volledige swing-toets voor een bewaakte watch: daily en
    4-uur factoren apart (geen gecombineerd vertrouwenscijfer), stop loss/
    take profit op basis van het bron-niveau, journaalregel en niet-stille
    Telegram-melding per gebruiker. Zet de watch op "bevestigd": hij wordt
    daarna nooit opnieuw getoetst, ook niet als de prijs er later nogmaals
    overheen gaat."""
    watch = repo.get_swing_watch(watch_id)
    if not watch or watch["status"] != "wachtend":
        return  # al bevestigd/vervallen/ongeldig, of een dubbele aanroep

    coin, direction = watch["coin"], watch["direction"]
    tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, coin)
    if is_new_coin:
        await _notify_new_coin(coin)
    if not tracked:
        repo.update_swing_watch_status(watch_id, "ongeldig")
        return

    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        df_4h = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "4h")
    except Exception:
        logger.exception("Kon candles voor swing-toets van %s niet ophalen, watch %s blijft wachtend",
                          coin, watch_id)
        return

    if not repo.claim_swing_watch(watch_id):
        return  # een andere check (direct of periodiek) was net eerder

    daily_ind = indicators.compute_indicators(daily_df)
    ind_4h = indicators.compute_indicators(df_4h)
    swing_low, swing_high = indicators.swing_levels(df_4h)

    daily_factors = indicators.basic_factors(direction, daily_ind)
    factors_4h = indicators.basic_factors(direction, ind_4h)

    stop_take = risk.compute_stop_take_from_levels(
        direction, ind_4h.price, ind_4h.atr, [watch["price_level"]],
        swing_low=swing_low, swing_high=swing_high,
    )

    reason = (
        "Daily: " + " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in daily_factors)
        + "\n4 uur: " + " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors_4h)
    )
    context_note = f"Bewaakt niveau: {watch['price_level']}"
    if watch["pattern_name"]:
        context_note += f" ({watch['pattern_name']})"

    signal_data = {
        "message_id": watch["message_id"], "coin": coin, "direction": direction,
        "category": "swing", "trade_type": "swing",
        "price": ind_4h.price, "rsi": ind_4h.rsi, "macd": ind_4h.macd,
        "macd_signal": ind_4h.macd_signal, "volume_ratio": ind_4h.volume_ratio,
        "ema9": ind_4h.ema9, "ema21": ind_4h.ema21, "atr": ind_4h.atr,
        "atr_avg20": ind_4h.atr_avg20, "adx": ind_4h.adx,
        "technical_confirmed": 1,
        "confidence": "niveau bevestigd",
        "reason": reason,
        "stop_loss": stop_take.stop_loss, "take_profit": stop_take.take_profit,
        "context_note": context_note,
        "is_practice": 0,
        "plain_explanation": None,
    }
    signal_id = repo.insert_signal(signal_data)

    for user in repo.list_users():
        active_eval_for_display = repo.get_active_evaluation(user["id"])
        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, direction, ind_4h.price, stop_take.stop_loss, stop_take.take_profit,
        )
        max_pct_for_display = (
            risk.eval_max_stop_pct(active_eval_for_display["tier_amount"])
            if active_eval_for_display and evaluation_id is not None else None
        )
        # Een swing-stop staat expres net voorbij het bewaakte niveau: de
        # hele premisse van het signaal is dat het niveau standhoudt. Zou
        # de cap de stop tot voorbij dat niveau optrekken (long) of
        # terugtrekken (short), dan verdedigt de "gecapte" stop het niveau
        # niet meer en is hij zinlozer dan de bredere, ongecapte stop. Dan
        # liever geen cap voor deze ene trade dan een omgekeerde premisse.
        level = watch["price_level"]
        stop_was_capped = effective_stop_loss != stop_take.stop_loss
        if stop_was_capped and (
            (direction == "long" and effective_stop_loss >= level)
            or (direction == "short" and effective_stop_loss <= level)
        ):
            effective_stop_loss, effective_take_profit = stop_take.stop_loss, stop_take.take_profit
            stop_was_capped = False
        position_size = risk.compute_position_size(risk_eur, ind_4h.price, effective_stop_loss, cost_rate=cost_rate)
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        if stop_was_capped:
            repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, None)
        if not user["telegram_chat_id"]:
            continue
        # Geen is_coin_muted-check hier: mute geldt bewust alleen voor
        # day-trading meldingen (zie de spec), een swing-melding is
        # zeldzaam en juist bedoeld om een grote kans nooit te missen.
        quiet = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])

        eval_budget_pct = None
        eval_blocked_note = None
        if active_eval_for_display and evaluation_id is not None:
            open_risk_eur_display = repo.total_open_risk_eur_for_evaluation(evaluation_id)
            daily_remaining = risk.compute_eval_daily_budget_remaining(active_eval_for_display, open_risk_eur_display)
            eval_budget_pct = (risk_eur / daily_remaining * 100) if daily_remaining else 0.0
        elif active_eval_for_display and evaluation_id is None:
            eval_blocked_note = "Dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, deze trade telt niet mee voor je evaluatie."

        try:
            await telegram_notify.send_swing_signal(
                coin=coin, direction=direction, price=ind_4h.price,
                stop_loss=effective_stop_loss, take_profit=effective_take_profit,
                daily_factors=daily_factors, factors_4h=factors_4h,
                level_price=watch["price_level"], pattern_name=watch["pattern_name"],
                chat_id=user["telegram_chat_id"], entry_id=entry_id, force_silent=quiet,
                eval_budget_pct=eval_budget_pct, eval_blocked_note=eval_blocked_note,
                stop_capped_pct=(max_pct_for_display * 100) if stop_was_capped and max_pct_for_display is not None else None,
                risk_eur=risk_eur,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Swing-melding voor %s naar gebruiker %s is mislukt", coin, user["username"])


def _build_context_note(coin: str, direction: str) -> str:
    """Zet dit signaal af tegen het lopende lange-termijn narrative voor
    deze coin (zie evaluate_narrative). Verandert niets aan het hoog/laag
    vertrouwen label, dat blijft puur op de vier technische factoren
    gebaseerd, dit is extra achtergrond die meegaat in de melding.

    Alleen een narrative met status 'actief' telt mee: een tegengesproken
    of verlopen narrative is per definitie niet meer de actuele stand van
    zaken. Dit is bewust strenger dan de vorige versie (die simpelweg het
    allerlaatste lange-termijn bericht pakte, ongeacht of dat bericht zelf
    betrouwbaar was) — zie het TAO-incident in de spec.

    Eén enkel, mogelijk fout bericht kan een net begonnen narrative direct
    gezaghebbend maken over een steviger opgebouwd narrative dat het net
    tegensprak (zelfde soort situatie als het TAO-incident, maar dan op het
    day-trading-kruispunt in plaats van de Telegram-melding zelf). Weegt
    daarom mee hoeveel updates het actieve narrative zelf al heeft tegenover
    het narrative dat het als laatste tegensprak."""
    active = repo.get_active_narrative(coin)
    if not active:
        return ""

    when = active["opened_at"][:10]

    weight_note = ""
    predecessor = next(
        (n for n in repo.list_narratives_for_coin(coin)
         if n["id"] != active["id"] and n["status"] == "tegengesproken"),
        None,
    )
    if predecessor and active["message_count"] < predecessor["message_count"]:
        weight_note = (
            f" Dit narrative heeft pas {active['message_count']} "
            f"update{'s' if active['message_count'] != 1 else ''}, tegenover "
            f"{predecessor['message_count']} in het narrative dat het tegensprak."
        )

    if active["direction"] == direction.lower():
        return f"Sluit aan bij lopend lange termijn verhaal ({direction}, sinds {when})." + weight_note
    return (f"Let op: lopend lange termijn verhaal wijst op "
            f"{active['direction']}, dit signaal wijkt daarvan af (sinds {when})." + weight_note)


async def compute_advanced_extra_factors(
    coin: str, direction: str, df, entry_price: float, atr: float, zones: list[indicators.SRZone],
) -> list[tuple[str, bool, str]]:
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
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        factors.append(indicators.check_daily_trend(direction, daily_ind))
        factors.append(indicators.check_daily_rsi(direction, daily_ind))
    except Exception:
        logger.exception("Daily-trend/RSI voor %s kon niet berekend worden", coin)
        factors.append(("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("RSI daily", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        df_1h = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1h")
        ind_1h = indicators.compute_indicators(df_1h)
        factors.append(indicators.check_1h_trend(direction, ind_1h))
        factors.append(indicators.check_1h_rsi(direction, ind_1h))
    except Exception:
        logger.exception("1u bevestiging voor %s kon niet berekend worden", coin)
        factors.append(("1u bevestiging", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("RSI 1u", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_divergence(df, direction))
    except Exception:
        logger.exception("Divergentiecheck voor %s kon niet berekend worden", coin)
        factors.append(("Divergentie", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        ema9_series, ema21_series = indicators.ema_series(df)
        factors.append(indicators.check_candle_pattern_extended(df, direction, ema9_series, ema21_series))
    except Exception:
        logger.exception("Candlepatroon voor %s kon niet berekend worden", coin)
        factors.append(("Candlepatroon", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        quote_volume = await asyncio.to_thread(exchange.fetch_24h_quote_volume, coin)
        factors.append(indicators.check_liquidity(quote_volume))
    except Exception:
        logger.exception("Liquiditeitscheck voor %s kon niet berekend worden", coin)
        factors.append(("Liquiditeit", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_sr_zone(direction, entry_price, atr, zones))
    except Exception:
        logger.exception("Steun/weerstand voor %s kon niet berekend worden", coin)
        factors.append(("Steun/weerstand", False, "kon niet berekend worden, telt als niet bevestigd"))

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


async def process_day_trading_signal(
    message_id: int | None, interp: Interpretation,
    notify_on_update: bool = True, notify_on_reject: bool = True,
) -> None:
    tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
    if is_new_coin:
        await _notify_new_coin(interp.coin)
    if not tracked:
        logger.info("Coin %s bestaat niet als paar op de exchange, geen technische toetsing mogelijk",
                    interp.coin)
        # Zonder dit verdwijnt een bericht dat de AI wel prima kon lezen
        # (coin en richting zijn al bekend) hierna alsnog volledig stil: geen
        # Telegram, geen spoor voor de operator, alsof het nooit aankwam.
        repo.mark_message_untracked(message_id, interp.coin)
        for user in repo.list_users():
            if not user["telegram_chat_id"]:
                continue
            try:
                await telegram_notify.send_untracked_coin_message(interp.coin, chat_id=user["telegram_chat_id"])
            except Exception:
                logger.exception("Niet-ondersteunde-coin melding voor %s naar gebruiker %s is mislukt",
                                  interp.coin, user["username"])
        return

    df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)
    zones = indicators.detect_sr_zones(df)

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(
            interp.coin, interp.direction, df, ind.price, ind.atr, zones,
        )

    confirmed, reason = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
    # Geen bericht (autonoom marktscan-signaal, zie app/market_scanner.py)
    # betekent geen bron-niveaus om mee te wegen — die komen altijd uit een
    # gedeeld screenshot. De SR-zone-niveaus (zone_levels, hieronder)
    # blijven wel gewoon meetellen, die komen niet uit een bericht.
    message_levels = (
        [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id, interp.coin)]
        if message_id is not None else []
    )
    zone_levels = [
        edge for zone in zones for edge in (zone.price_low, zone.price_high)
        if abs(edge - ind.price) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
    ]
    combined_levels = message_levels + zone_levels
    if combined_levels:
        stop_take = risk.compute_stop_take_from_levels(
            interp.direction, ind.price, ind.atr, combined_levels, swing_low=swing_low, swing_high=swing_high,
        )
    else:
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

    # Alleen zinvol voor een AUTONOOM signaal (message_id is None): een
    # community-bericht heeft geen "herhaald patroon" in deze zin, dat is
    # een menselijke keuze elke keer opnieuw. Puur informatief, het signaal
    # wordt gewoon aangemaakt en gemeld zoals altijd — zie de spec, sectie 5.
    repeated_loss_note = None
    if message_id is None and confirmed:
        loss_streak = await asyncio.to_thread(
            repo.consecutive_autonomous_losses, interp.coin, interp.direction,
        )
        if loss_streak >= 3:
            repeated_loss_note = (
                f"📉 Dit zelf-gedetecteerde patroon verloor de laatste {loss_streak} keer op rij "
                f"bij {interp.coin}. Blijft een geldige kans, weeg dit wel mee."
            )

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
        "repeated_loss_note": repeated_loss_note,
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
        if notify_on_update:
            await _notify_signal_update(signal_id, signal_data)
        return

    signal_id = repo.insert_signal(signal_data)
    logger.info("Signaal %s opgeslagen: %s %s, bevestigd=%s", signal_id, interp.coin,
                interp.direction, confirmed)

    # find_open_signal hierboven kon het vorige signaal voor deze coin niet
    # meer als "open" beschouwen (bv. iedereen had die kans al afgesloten),
    # dus er is een apart, nieuw signaal aangemaakt in plaats van een update.
    # Een oude, nog niet opgevolgde kans voor dezelfde coin (andere richting
    # ving auto_ignore_opposite_pending hierboven al af) blijft dan zonder
    # dit los op het dashboard staan met verouderde niveaus, alsof hij nog
    # actueel is.
    stale = repo.auto_ignore_stale_pending_for_coin(interp.coin, exclude_signal_id=signal_id)
    if stale:
        logger.info("%s oude nog niet genomen melding(en) voor %s automatisch genegeerd (nieuw signaal)",
                     len(stale), interp.coin)
        for user in stale:
            if not user["telegram_chat_id"]:
                continue
            try:
                await telegram_notify.send_stale_pending_message(
                    interp.coin, chat_id=user["telegram_chat_id"],
                )
            except Exception:
                logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt",
                                  interp.coin, user["username"])

    # Elke gebruiker krijgt zijn eigen logboekregel, ongeacht vertrouwen, zo
    # blijft de trackrecord per vertrouwen-niveau compleet. Ook een afgewezen
    # tip krijgt een Telegram bericht (zonder stop loss/take profit/grootte,
    # dat is geen uitvoerbare trade opzet), anders voelt stilte aan als "er
    # is niks gebeurd" in plaats van "getoetst, met deze reden afgekeurd".
    for user in repo.list_users():
        # Vóór het aanmaken van de nieuwe regel gemeten: die staat zelf nog
        # op 'nieuw', niet 'genegeerd', en zou de telling anders altijd naar
        # 0 laten terugvallen.
        ignored_streak = repo.consecutive_ignored_count(user["id"], interp.coin)
        muted = repo.is_coin_muted(user["id"], interp.coin)

        # Vóór _resolve_signal_risk opgehaald (in plaats van pas bij de
        # eval_budget_pct/eval_blocked_note-berekening verderop), zodat
        # max_pct_for_display hieronder dezelfde, al opgehaalde evaluatie
        # kan hergebruiken zonder repo.get_active_evaluation een tweede
        # keer aan te roepen.
        active_eval_for_display = repo.get_active_evaluation(user["id"])

        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, interp.direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
        )
        max_pct_for_display = (
            risk.eval_max_stop_pct(active_eval_for_display["tier_amount"])
            if active_eval_for_display and evaluation_id is not None else None
        )
        position_size = (
            risk.compute_position_size(risk_eur, ind.price, effective_stop_loss, cost_rate=cost_rate)
            if confirmed else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        # Alleen zetten als de stop voor deze gebruiker daadwerkelijk is
        # ingeperkt: het gedeelde signaal blijft zo de bron van waarheid
        # voor elke gebruiker zonder (bruikbare) evaluatie, en
        # update_journal_levels's eigen COALESCE-gedrag (leeg = terugvallen
        # op het signaal) blijft voor hen intact.
        if effective_stop_loss != stop_take.stop_loss:
            repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, None)

        # Toont welk deel van het resterende dagbudget deze trade gebruikt,
        # of dat sizing juist geblokkeerd was (dan telt de trade niet mee
        # voor de evaluatie). _resolve_signal_risk geeft evaluation_id=None
        # zowel als er geen actieve evaluatie is (a) als wanneer sizing
        # geblokkeerd was (c) - door hier opnieuw de actieve evaluatie op te
        # halen kunnen die twee gevallen wél uit elkaar gehouden worden.
        eval_budget_pct = None
        eval_blocked_note = None
        if active_eval_for_display and evaluation_id is not None:
            open_risk_eur_display = repo.total_open_risk_eur_for_evaluation(evaluation_id)
            daily_remaining = risk.compute_eval_daily_budget_remaining(active_eval_for_display, open_risk_eur_display)
            # Percentage van het VOLLEDIGE resterende dagbudget, zoals het
            # Telegram-label ook zegt — niet van het per-trade aandeel
            # (dagbudget / EVAL_BUDGET_TRADE_RESERVE), want dan toont een
            # trade die precies zijn aandeel gebruikt alarmerend "100%".
            eval_budget_pct = (risk_eur / daily_remaining * 100) if daily_remaining else 0.0
        elif active_eval_for_display and evaluation_id is None:
            eval_blocked_note = "Dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, deze trade telt niet mee voor je evaluatie."

        if not user["telegram_chat_id"]:
            logger.info("Gebruiker %s heeft geen telegram_chat_id, geen melding verstuurd",
                        user["username"])
            continue

        if muted:
            # De logboekregel bestaat al (hierboven aangemaakt): trackrecord
            # en dashboard-cijfers blijven kloppen, alleen de Telegram-melding
            # zelf wordt overgeslagen, dat is precies wat "uitzetten" betekent.
            logger.info("Coin %s is gemute voor gebruiker %s, geen Telegram-melding verstuurd",
                        interp.coin, user["username"])
            continue

        if not confirmed and not notify_on_reject:
            # Autonome marktscan (app/market_scanner.py) geeft
            # notify_on_reject=False mee: een afgewezen ("nog geen sterke
            # kans") autonoom signaal hoeft geen Telegram-melding te
            # sturen, in tegenstelling tot een door de gebruiker gedeeld
            # bericht (die krijgt altijd een bericht, ook bij afwijzing).
            # De logboekregel hierboven blijft wel gewoon bestaan, het
            # trackrecord blijft compleet, alleen de melding zelf wordt
            # overgeslagen — zelfde patroon als de muted-continue hierboven.
            logger.info("Afwijzing voor %s niet gemeld aan gebruiker %s (notify_on_reject=False)",
                        interp.coin, user["username"])
            continue

        # Alleen bij een bevestigde kans zinvol: een afwijzing is toch geen
        # trade die risico toevoegt. Toont waar het TOTALE open risico
        # zou uitkomen als deze kans ook genomen wordt, niet alleen het
        # risicobedrag van deze ene trade op zich. Een evaluatie-gekoppelde
        # trade blijft eruit: die is tegen het virtuele evaluatiesaldo
        # gesized, dus zijn risk_eur optellen bij een percentage van het
        # echte portfolio geeft een onzinnige, alarmerende uitslag
        # (total_open_risk_eur laat zulke trades om dezelfde reden al weg).
        open_risk_pct = None
        if confirmed and user["portfolio_eur"] and evaluation_id is None:
            current_open_risk = repo.total_open_risk_eur(user["id"])
            open_risk_pct = (current_open_risk + risk_eur) / user["portfolio_eur"] * 100

        # Inclusief deze nieuwe kans zelf (net aangemaakt met status 'nieuw').
        # Bij precies 1 is dit de enige, geen samenvattingsregel nodig.
        pending_count = repo.count_pending_signals(user["id"])

        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            stop_was_capped = effective_stop_loss != stop_take.stop_loss
            await telegram_notify.send_signal(
                {
                    **signal_data, "risk_eur": risk_eur, "position_size": position_size,
                    "open_risk_pct": open_risk_pct, "pending_count": pending_count,
                    "eval_budget_pct": eval_budget_pct, "eval_blocked_note": eval_blocked_note,
                    "stop_loss": effective_stop_loss, "take_profit": effective_take_profit,
                    "stop_capped_pct": (
                        (max_pct_for_display * 100)
                        if stop_was_capped and max_pct_for_display is not None else None
                    ),
                },
                chat_id=user["telegram_chat_id"], force_silent=force_silent, entry_id=entry_id,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Telegram melding voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
            continue

        # Bij een gecapte stop toont de gedeelde grafiek (ongecapte stop) een
        # ander getal dan de tekst van hetzelfde bericht — dan liever geen
        # plaatje sturen dan een misleidend plaatje.
        if chart_bytes and not stop_was_capped:
            try:
                await telegram_notify.send_signal_chart(
                    chart_bytes, interp.coin, interp.direction, chat_id=user["telegram_chat_id"],
                )
            except Exception:
                logger.exception("Chart versturen voor gebruiker %s, signaal %s is mislukt",
                                  user["username"], signal_id)

        # Precies op de grens gevraagd (== in plaats van >=), zie
        # REPEATED_IGNORE_MUTE_THRESHOLD hierboven.
        if ignored_streak == REPEATED_IGNORE_MUTE_THRESHOLD:
            try:
                await telegram_notify.send_mute_suggestion(interp.coin, chat_id=user["telegram_chat_id"])
            except Exception:
                logger.exception("Mute-suggestie voor gebruiker %s, coin %s is mislukt",
                                  user["username"], interp.coin)


async def _notify_signal_update(signal_id: int, signal_data: dict) -> None:
    """Stuurt een update-melding naar gebruikers die dit signaal nog open
    hebben staan, bevestigd of niet: een gewijzigde toetsing op een nieuw
    bericht over dezelfde coin is altijd het melden waard. Maakt geen nieuwe
    logboekregel aan, die bestaat al.

    Een nog niet genomen (pending) logboekregel die AL aan een evaluatie
    gekoppeld is (evaluation_id gezet bij aanmaak) krijgt hier de vernieuwde
    cap van PRECIES DIE evaluatie (niet "de huidige actieve evaluatie van de
    gebruiker" — die kan intussen een andere, nieuwere run zijn). Een
    gewone portfolio-trade (evaluation_id is None) wordt hier NOOIT gecapt,
    ongeacht of de gebruiker inmiddels wel een evaluatie is gestart: anders
    krijgt een trade die tegen het echte portfolio gesized is een cap die
    bij een heel andere berekening hoort. Een evaluatie die niet meer
    'actief' is, is bevroren (zelfde regel als close_journal_trade): geen
    cap meer, de override valt terug op het gedeelde signaal.

    De override wordt ALTIJD herschreven, ook als er nu geen cap meer geldt
    — anders blijft een eerdere cap voor altijd hangen zodra een latere
    update geen cap meer oplevert (te ruime nieuwe stop, evaluatie
    inmiddels geblokkeerd of bevroren). None valt terug op het gedeelde
    signaal via de bestaande COALESCE in _JOURNAL_SELECT. De opgeslagen
    (auto-)positiegrootte wordt in hetzelfde geval meegeschaald naar de
    nieuwe effectieve stop, anders blijft hij op de oude stop-afstand
    gebaseerd en horen grootte en stop niet meer bij hetzelfde risicobedrag.

    Een AL GENOMEN trade (eigen entry_price staat al vast, een echte open
    positie) blijft bewust ongemoeid: het risico van een al lopende positie
    verandert niet met terugwerkende kracht door een nieuw bericht — dat is
    een expliciete keuze van de product owner, geen omissie. Een genegeerde
    kans (status 'genegeerd') krijgt hier ook geen update meer: die trade
    is voor deze gebruiker al afgesloten."""
    entries = {e["user_id"]: e for e in repo.list_journal_entries_for_signal(signal_id)}
    for user in repo.list_users():
        entry = entries.get(user["id"])
        if (
            not entry or entry["exit_price"] is not None or entry["status"] == "genegeerd"
            or not user["telegram_chat_id"]
        ):
            continue
        if repo.is_coin_muted(user["id"], signal_data["coin"]):
            continue

        message_data = signal_data
        if entry["entry_price"] is None and entry["evaluation_id"] is not None:
            linked_eval = repo.get_evaluation(entry["evaluation_id"])
            stop_was_capped = False
            effective_stop_loss, effective_take_profit = signal_data["stop_loss"], signal_data["take_profit"]
            max_pct_for_display = None
            if linked_eval and linked_eval["status"] == "actief":
                open_risk_eur = repo.total_open_risk_eur_for_evaluation(entry["evaluation_id"])
                if not risk.eval_sizing_blocked(linked_eval, open_risk_eur):
                    max_pct_for_display = risk.eval_max_stop_pct(linked_eval["tier_amount"])
                    capped = risk.apply_eval_stop_cap(
                        signal_data["direction"], signal_data["price"],
                        signal_data["stop_loss"], signal_data["take_profit"], max_pct_for_display,
                    )
                    effective_stop_loss, effective_take_profit = capped.stop_loss, capped.take_profit
                    stop_was_capped = effective_stop_loss != signal_data["stop_loss"]
            repo.update_journal_levels(
                entry["id"], user["id"],
                effective_stop_loss if stop_was_capped else None,
                effective_take_profit if stop_was_capped else None,
                None,
            )
            # De opgeslagen (auto-)positiegrootte is gesized tegen de OUDE
            # effectieve stop; zonder dit meeschalen blijft hij daarop
            # hangen zodra effective_stop_loss hierboven verandert, en komt
            # de getoonde grootte niet meer overeen met entry["risk_eur"]
            # tegen de NIEUWE stop. Alleen zinvol voor een bevestigde kans,
            # net als bij het aanmaken (position_size is anders None).
            if signal_data.get("technical_confirmed"):
                cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
                new_position_size = risk.compute_position_size(
                    entry["risk_eur"] or 0.0, signal_data["price"], effective_stop_loss, cost_rate=cost_rate,
                )
                repo.update_journal_position_size(entry["id"], user["id"], new_position_size)
            message_data = {
                **signal_data, "stop_loss": effective_stop_loss, "take_profit": effective_take_profit,
                "stop_capped_pct": (
                    (max_pct_for_display * 100)
                    if stop_was_capped and max_pct_for_display is not None else None
                ),
            }

        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_signal_update(
                message_data, chat_id=user["telegram_chat_id"], force_silent=force_silent,
            )
        except Exception:
            logger.exception("Telegram update voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
