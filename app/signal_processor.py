"""Verwerkingspijplijn: interpretatie via Anthropic, technische toetsing
voor day trading berichten, risicomanagement en pushmelding.

Dit systeem voert geen trades uit. Het geeft een melding op basis van
regels. Elke trade blijft een handmatige beslissing.
"""
import asyncio
import logging
import time
from typing import Callable, Optional

from app import coinlist, config, exchange, explain, indicators, push_notify, repo, risk
from app.anthropic_interpret import Interpretation, interpret_message
from app.setup_eval import (  # noqa: F401  (market_scanner importeert deze namen hier)
    MAX_STOP_DISTANCE_PCT, MIN_RISK_REWARD_RATIO, evaluate_day_trading_setup, stop_within_max_distance,
)

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
    # Kostenfilter (HesPulse-verkleinen, 2026-09-30): een bericht zonder
    # afbeelding dat geen van de 7 vaste coins noemt, wordt nooit aan
    # Anthropic voorgelegd — dat is de duurste stap per bericht. Een
    # bericht MET afbeelding wordt altijd nog geïnterpreteerd: een
    # screenshot is niet goedkoop op tekst te filteren, en dat is precies
    # het scenario waarin dit filter een echt signaal zou kunnen missen
    # als het ook afbeeldingen zou overslaan. Stap 2 van dit filter (ná de
    # interpretatie, voor het geval Anthropic bij een screenshot toch een
    # niet-gevolgde coin teruggeeft) staat in _process_one_coin hieronder.
    if not image_paths and not coinlist.message_mentions_tracked_coin(raw_text):
        logger.info(
            "Bericht %s bevat geen gevolgde coin en geen afbeelding, niet geïnterpreteerd", message_id,
        )
        repo.mark_message_processed(
            message_id, None, None, None, True,
            note="Geen gevolgde coin herkend in tekst en geen afbeelding, niet geïnterpreteerd (kostenfilter)",
        )
        return

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
                repo.create_notification(
                    None, "admin_error",
                    "Herhaalde API-fouten",
                    f"Anthropic interpretatie is nu {_consecutive_interpret_failures} berichten op rij mislukt. "
                    f"Laatste fout: {exc}",
                    None,
                )
            except Exception:
                logger.exception("Kon admin-melding voor herhaalde API-fouten niet opslaan")
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
    # Vangnet voor stap 1 van het kostenfilter in handle_message: die kan
    # een bericht MET afbeelding niet goedkoop vooraf filteren, dus hier
    # (ná de interpretatie, als de coin al bekend is) alsnog negeren als
    # Anthropic een coin teruggaf die niet op de vaste lijst staat.
    if interp.coin and interp.coin.upper() not in config.FIXED_COINS:
        repo.insert_message_coin_result(
            message_id, interp.coin, interp.direction, interp.category, True,
            note=f"{interp.coin.upper()} staat niet op de vaste coinlijst, niet verder verwerkt",
        )
        logger.info(
            "Coin %s (bericht %s) staat niet op de vaste lijst, overgeslagen", interp.coin, message_id,
        )
        return

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
                repo.insert_source_level(
                    message_id, interp.coin, level.price_level, level.pattern_name,
                )

    if interp.category != "day_trading":
        logger.info("Bericht %s (coin %s) valt in categorie %s, alleen gelogd, geen melding",
                    message_id, interp.coin, interp.category)
        # Live koers vastleggen op het moment van deze analyse: zonder dit
        # referentiepunt (price_at_receipt) is er later geen prijs om een
        # swing-watch of narrative-tijdlijn tegen af te zetten. Mislukt de
        # koersophaal, dan blijft dit veld leeg, geen reden om de rest van
        # de verwerking te blokkeren.
        if interp.direction in ("long", "short"):
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
                repo.set_message_coin_result_price_at_receipt(result_id, live_price)
            except Exception:
                logger.exception("Live prijs voor lange-termijn analyse %s kon niet vastgelegd worden",
                                  interp.coin)

        # lange_termijn-analyses worden sinds HesPulse-verkleinen
        # (2026-09-30) alleen nog intern bijgehouden (evaluate_narrative
        # vult coin_narratives, geen eigen melding meer, zie de docstring
        # daar) — de samenvatting hierboven (message_summary) is het enige
        # zichtbare spoor van dit bericht, totdat een latere
        # dagtradingsignaal voor dezelfde coin ernaar verwijst via
        # _build_context_note.
        if interp.category == "lange_termijn" and interp.direction in ("long", "short"):
            try:
                await evaluate_narrative(interp.coin, interp.direction, result_id)
            except Exception:
                logger.exception("Narrative-evaluatie voor %s (bericht %s) is mislukt",
                                  interp.coin, message_id)
        # Geen aparte Telegram-push meer voor een lange-termijn bericht
        # zonder long/short-richting (dashboard-only, zie de declutter-ronde
        # van 2026-09-14): message_summary staat al op de messages-rij, dus
        # zichtbaar via het bestaande Berichtenoverzicht.
        return

    await process_day_trading_signal(message_id, interp)


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
    richting.

    Puur interne boekhouding sinds HesPulse-verkleinen (2026-09-30): geen
    eigen melding meer (was _send_narrative_notifications) en geen apart
    dashboard-blok meer (coin.html). coin_narratives blijft wel gevuld —
    _build_context_note (elders in dit bestand) leest hier rechtstreeks
    uit en zet het resultaat sinds deze wijziging weer echt in de
    pushmelding van een dagtradingsignaal, zie process_day_trading_signal
    hieronder."""
    if direction not in ("long", "short"):
        return

    active = repo.get_active_narrative(coin)
    if active is None:
        repo.create_narrative(coin, direction, result_id)
        return

    if active["direction"] == direction:
        repo.update_narrative_progress(active["id"], result_id)
        return

    repo.close_narrative(
        active["id"], "tegengesproken",
        f"tegengesproken door een nieuw {direction}-narrative voor {coin}",
    )
    repo.create_narrative(coin, direction, result_id)


def _resolve_signal_risk(
    user: dict, direction: str, entry_price: float, stop_loss: float, take_profit: float,
) -> tuple[Optional[float], Optional[int], float, float, float]:
    """Geen enkele automatische positiegrootte-bron meer (evaluatie en de
    generieke portfolio_eur x risk_percent-sizing zijn allebei verwijderd)
    — risk_eur/evaluation_id zijn altijd None, stop_loss/take_profit blijven
    ongewijzigd. Signatuur bewust ongewijzigd gelaten: dit voorkomt dat elke
    aanroeper elders in dit bestand ook aangepast moet worden voor een
    functie die toch al bijna niets meer doet."""
    return None, None, 0.0, stop_loss, take_profit


_KANSBEREKENING_NOT_APPLICABLE = object()


async def _fanout_confirmed_signal(
    signal_id: int, coin: str, direction: str, entry_price: float,
    stop_loss: float, take_profit: float, premise_level: float, title: str,
    make_body: Callable[[float, float, bool], str],
    skip_push: bool = False,
    kansberekening=_KANSBEREKENING_NOT_APPLICABLE, hard_gates_ok: bool = True,
    reason: str = "",
    signal_type: Optional[str] = None,
    force_silent: bool = False,
) -> None:
    """Deelt een al-bevestigd signaal (geen gepoold percentage, altijd
    gemeld) met alle gebruikers: journaalregel + pushmelding per gebruiker,
    met per-gebruiker evaluatie-sizing en stop-cap. Gedeeld tussen
    run_swing_check (swing) en market_scanner._find_chart_pattern_candidate
    (patroon) — beide zijn "autonoom bevestigd"-signalen met identieke
    fan-out-logica, alleen titel en berichttekst verschillen per soort.
    make_body ontvangt de EFFECTIEVE (mogelijk ingeperkte) stop/take voor
    deze ene gebruiker en of die stop gecapt werd, zodat de melding altijd
    de daadwerkelijke cijfers voor deze gebruiker toont.

    kansberekening (alleen gebruikt door patroon) laat de push-beslissing
    per gebruiker meelopen met diens EIGEN drempel (confirm_threshold_pct,
    zelfde repo.user_confirmed-vergelijking als de "trade kans"-badge op
    /signalen) in plaats van één vaste grens voor iedereen — anders kon een
    gebruiker met een strenge drempel een pushmelding krijgen voor een
    patroon dat op de pagina zelf als afgewezen getoond wordt. De sentinel
    _KANSBEREKENING_NOT_APPLICABLE (default) betekent "dit signaaltype
    heeft geen kansberekening" (swing) en valt terug op het simpele
    skip_push. None is een geldige, andere waarde (patroon zonder genoeg
    historische data) en telt via repo.user_confirmed altijd als niet
    bevestigd, ongeacht de drempel. hard_gates_ok is de bijbehorende harde-
    eisen-vlag, nodig voor diezelfde vergelijking.

    reason is de factor-breakdown-tekst van dit signaal (dezelfde
    "✓ Naam: ... | ✗ Naam: ..."-tekst als signals.reason), nodig om per
    gebruiker zijn eigen verplichte-factoren-eis te toetsen (zie
    repo.user_confirmed). Alleen relevant samen met kansberekening
    (patroon); bij de sentinel (swing) wordt hij simpelweg niet gebruikt.

    skip_push=True (alleen relevant zonder kansberekening) slaat de
    pushmelding voor deze gebruiker helemaal over — niet stil versturen,
    HELEMAAL niet versturen. De journaalregel wordt wel gewoon aangemaakt,
    dus trackrecord/dashboard blijven compleet.

    entry_price is de LIVE prijs op het moment van bevestiging (gebruikt
    voor position sizing en de coin-link in de pushmelding). premise_level
    is het niveau waar de hele trade-premisse op steunt (het bewaakte
    bron-niveau bij een swing-watch, de patroon-trigger bij een
    chart-patroon) — dat kan inmiddels van entry_price afwijken (prijs
    beweegt tussen het zetten van het niveau en de latere bevestiging), dus
    de twee zijn expres losse parameters."""
    # Zie config.SIGNAL_TYPE_INFO_ONLY: de journaalregel blijft, alleen de push vervalt.
    if signal_type in config.SIGNAL_TYPE_INFO_ONLY:
        skip_push, kansberekening = True, _KANSBEREKENING_NOT_APPLICABLE
    required_by_user = repo.list_required_factors_all_users()
    for user in repo.list_users():
        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, direction, entry_price, stop_loss, take_profit,
        )
        # Vergeleken met premise_level, niet met de live entry_price: een
        # gecapte stop die voorbij het niveau ligt waar de trade zijn
        # bestaansrecht aan ontleent, verdedigt die premisse niet meer, dan
        # is de ongecapte stop nuttiger dan een gecapte stop die zijn reden
        # van bestaan al kwijt is.
        stop_was_capped = effective_stop_loss != stop_loss
        if stop_was_capped and (
            (direction == "long" and effective_stop_loss >= premise_level)
            or (direction == "short" and effective_stop_loss <= premise_level)
        ):
            effective_stop_loss, effective_take_profit = stop_loss, take_profit
            stop_was_capped = False
        position_size = (
            risk.compute_position_size(risk_eur, entry_price, effective_stop_loss, cost_rate=cost_rate)
            if risk_eur is not None else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        if stop_was_capped:
            repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, None)

        # Geen telegram_chat_id-gate: push_notify.send_push slaat een
        # gebruiker zonder push-abonnement zelf al stilzwijgend over. Geen
        # is_coin_muted-check: mute geldt bewust alleen voor day-trading
        # meldingen (zie de spec), dit is een autonoom bevestigd signaal
        # (swing-watch of chart-patroon) dat juist bedoeld is om een grote
        # kans nooit te missen.
        if kansberekening is _KANSBEREKENING_NOT_APPLICABLE:
            skip_this_user = skip_push
        else:
            skip_this_user = not repo.user_confirmed(
                kansberekening, hard_gates_ok, user["confirm_threshold_pct"],
                reason=reason, required_factors=required_by_user.get(user["id"], set()),
            )
        if skip_this_user:
            logger.info("Onder de drempel van gebruiker %s voor %s: geen pushmelding",
                        user["username"], coin)
            continue

        quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            body = make_body(effective_stop_loss, effective_take_profit, stop_was_capped)
            await push_notify.send_push(user["id"], title, body, f"/coins/{coin}#signal-{signal_id}", silent=quiet or force_silent)
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Melding voor %s naar gebruiker %s is mislukt", coin, user["username"])


fanout_confirmed_signal = _fanout_confirmed_signal


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
        "pass_pct": None,
        "hard_gates_ok": 1,
        "confidence": "niveau bevestigd",
        "reason": reason,
        "stop_loss": stop_take.stop_loss, "take_profit": stop_take.take_profit,
        "context_note": context_note,
        "is_practice": 0,
        "plain_explanation": None,
    }
    signal_id = repo.insert_signal(signal_data)

    def _swing_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
        pattern_note = f" ({watch['pattern_name']})" if watch["pattern_name"] else ""
        return (
            f"Vanuit bewaakt niveau {watch['price_level']:.4f}{pattern_note}\n"
            f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
        )

    await _fanout_confirmed_signal(
        signal_id, coin, direction, ind_4h.price, stop_take.stop_loss, stop_take.take_profit,
        premise_level=watch["price_level"],
        title=push_notify.alert_title(coin, direction, "Swing"),
        make_body=_swing_body, signal_type="swing",
    )


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
    daily_df=None, daily_ind: indicators.Indicators | None = None, data=None,
) -> list[tuple[str, bool, str]]:
    """Async wrapper rond advanced_extra_factors_sync (zie daar voor de
    volledige uitleg); data=None betekent de live exchange."""
    return await asyncio.to_thread(
        advanced_extra_factors_sync, coin, direction, df, entry_price, atr, zones,
        daily_df, daily_ind, data or exchange,
    )


def advanced_extra_factors_sync(
    coin: str, direction: str, df, entry_price: float, atr: float, zones: list[indicators.SRZone],
    daily_df=None, daily_ind: indicators.Indicators | None = None, data=None,
) -> list[tuple[str, bool, str]]:
    """Berekent de losse checks voor de uitgebreide factorenset (BTC-trend,
    1u bevestiging, divergentie, liquiditeit). Elke check faalt individueel
    en "fail-closed" als de data ervoor niet op te halen is: beter een
    factor die ten onrechte op ✗ staat door een netwerkhapering, dan een
    hoog-vertrouwen melding die stilzwijgend op onvolledige data steunt.

    daily_df/daily_ind zijn optioneel: process_day_trading_signal haalt de
    1d-candle altijd al zelf op voor de Daily-trend-hard-gate (zie daar) en
    geeft die hier door, zodat deze functie 'm niet nogmaals via de
    exchange hoeft op te halen voor de andere dag-factoren (RSI daily,
    Premium/discount (dag), Liquidity sweep (dag)) die hem ook nodig
    hebben. Ontbreken ze (bv. de eerdere fetch faalde), dan valt deze
    functie terug op zijn eigen fetch hieronder."""
    data = data or exchange
    factors: list[tuple[str, bool, str]] = []

    if coin.upper() != "BTC":
        try:
            btc_df = data.fetch_ohlcv("BTC")
            btc_ind = indicators.compute_indicators(btc_df)
            # BTC-trend is nu een harde eis in confirms_direction (zie
            # daar). Bij een vlakke BTC is er geen "tegen de trade in"
            # om op te blokkeren, en zou een altcoin die op eigen kracht
            # uitbreekt onterecht geblokkeerd worden. market_scanner.py
            # sloeg altcoin-signalering vroeger een hele cyclus over bij
            # een zijwaartse BTC, dat is inmiddels verwijderd; deze factor
            # hier blijft wel gewoon een zachte, niet-blokkerende toets.
            if not indicators.btc_is_flat(btc_ind):
                factors.append(indicators.check_btc_trend(direction, btc_ind))
        except Exception:
            logger.exception("BTC-trend kon niet berekend worden")
            factors.append(("BTC-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        if daily_df is None or daily_ind is None:
            daily_df = data.fetch_ohlcv(coin, "1d")
            daily_ind = indicators.compute_indicators(daily_df)
        # Daily-trend zelf wordt niet meer hier berekend: die is nu een
        # altijd-actieve harde eis in confirms_direction, opgehaald in
        # process_day_trading_signal (zie daar), anders zou hij hier
        # dubbel tellen.
        factors.append(indicators.check_daily_rsi(direction, daily_ind))
        daily_swing_low, daily_swing_high = indicators.swing_levels(daily_df)
        factors.append(indicators.check_daily_premium_discount(direction, entry_price, daily_swing_low, daily_swing_high))
        factors.append(indicators.check_daily_liquidity_sweep(direction, daily_df))
    except Exception:
        # Log-tekst dekt alleen nog de factoren die deze functie hier
        # berekent (RSI daily, Premium/discount (dag), Liquidity sweep
        # (dag)) — Daily-trend zelf heeft een eigen fetch/log in
        # process_day_trading_signal, zie de comment hierboven.
        logger.exception("Dag-factoren (RSI/premium-discount/liquidity sweep) voor %s konden niet berekend worden", coin)
        factors.append(("RSI daily", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("Premium/discount (dag)", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("Liquidity sweep (dag)", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        df_1h = data.fetch_ohlcv(coin, "1h")
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
        quote_volume = data.fetch_24h_quote_volume(coin)
        factors.append(indicators.check_liquidity(quote_volume))
    except Exception:
        logger.exception("Liquiditeitscheck voor %s kon niet berekend worden", coin)
        factors.append(("Liquiditeit", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_sr_zone(direction, entry_price, atr, zones, df))
    except Exception:
        logger.exception("Steun/weerstand voor %s kon niet berekend worden", coin)
        factors.append(("Steun/weerstand", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        swing_low, swing_high = indicators.swing_levels(df)
        factors.append(indicators.check_premium_discount(direction, entry_price, swing_low, swing_high))
    except Exception:
        logger.exception("Premium/discount voor %s kon niet berekend worden", coin)
        factors.append(("Premium/discount", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_liquidity_sweep(direction, df))
    except Exception:
        logger.exception("Liquidity sweep voor %s kon niet berekend worden", coin)
        factors.append(("Liquidity sweep", False, "kon niet berekend worden, telt als niet bevestigd"))

    return factors


async def compute_full_confirmation(
    coin: str, direction: str, df, ind: indicators.Indicators, zones: list[indicators.SRZone],
    daily_trend_hard_gate: bool = True, data=None,
) -> tuple[bool, str, float, bool]:
    """Async wrapper rond full_confirmation_sync (zie daar voor de
    volledige uitleg); data=None betekent de live exchange."""
    return await asyncio.to_thread(
        full_confirmation_sync, coin, direction, df, ind, zones, daily_trend_hard_gate, data or exchange,
    )


def full_confirmation_sync(
    coin: str, direction: str, df, ind: indicators.Indicators, zones: list[indicators.SRZone],
    daily_trend_hard_gate: bool = True, data=None,
) -> tuple[bool, str, float, bool]:
    """Volledige factor-toetsing: dagtrend (met vlakke-markt-uitzondering)
    plus, bij config.ENABLE_ADVANCED_FACTORS, de uitgebreide factoren, dan
    indicators.confirms_direction. Geëxtraheerd uit process_day_trading_signal
    zodat market_scanner._check_chart_patterns exact dezelfde toetsing kan
    hergebruiken voor een patroon-richting, zonder deze logica te
    dupliceren. Retourneert (confirmed, breakdown, pass_pct, hard_gates_ok),
    identiek aan wat confirms_direction zelf teruggeeft.

    daily_trend_hard_gate=False (market_scanner._find_chart_pattern_candidate,
    voor een omkeerpatroon) zet Daily-trend om naar puur informatief in
    plaats van blokkerend, zie indicators.confirms_direction's docstring
    voor de volledige redenering."""
    data = data or exchange
    daily_trend_factor = None
    daily_df = None
    daily_ind = None
    try:
        daily_df = data.fetch_ohlcv(coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        # Net als BTC-trend (indicators.btc_is_flat): een coin zonder
        # duidelijke eigen dagtrend mag niet hard geblokkeerd worden, dat
        # zou een normale consolidatie vlak voor een uitbraak onterecht
        # wegfilteren. btc_is_flat is ondanks zijn naam coin-onafhankelijk
        # (alleen ema9/ema21/atr), dus rechtstreeks herbruikbaar hier.
        if not indicators.btc_is_flat(daily_ind):
            daily_trend_factor = indicators.check_daily_trend(direction, daily_ind)
    except Exception:
        logger.exception("Dagtrend kon niet berekend worden voor %s", coin)
        daily_trend_factor = ("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd")

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = advanced_extra_factors_sync(
            coin, direction, df, ind.price, ind.atr, zones, daily_df, daily_ind, data,
        )

    return indicators.confirms_direction(
        ind, direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
        daily_trend_factor=daily_trend_factor, daily_trend_hard_gate=daily_trend_hard_gate,
    )


def _notify_new_coin(coin: str) -> None:
    """Geen Telegram-melding meer (dashboard-only, zie de declutter-ronde
    van 2026-09-14): de coin zelf wordt meteen zichtbaar in het coin-menu
    zodra hij aan de dynamische lijst is toegevoegd, een aparte push
    voegde daar weinig aan toe naast de andere berichttypes."""
    logger.info("Nieuwe coin %s toegevoegd aan de dynamische lijst", coin)


async def process_day_trading_signal(
    message_id: int | None, interp: Interpretation,
    notify_on_update: bool = True,
) -> None:
    tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
    if is_new_coin:
        _notify_new_coin(interp.coin)
    if not tracked:
        logger.info("Coin %s bestaat niet als paar op de exchange, geen technische toetsing mogelijk",
                    interp.coin)
        # Zonder dit verdwijnt een bericht dat de AI wel prima kon lezen
        # (coin en richting zijn al bekend) hierna alsnog volledig stil voor
        # de operator: geen spoor, alsof het nooit aankwam. Sinds de
        # declutter-ronde (2026-09-14) geen aparte Telegram-push meer naar
        # de gebruiker (dashboard-only, zie Berichtenoverzicht), de
        # logboekregel hier blijft wel bestaan als spoor.
        repo.mark_message_untracked(message_id, interp.coin)
        return

    df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin)
    ind = indicators.compute_indicators(df)
    zones = indicators.detect_sr_zones(df)

    confirmed, reason, pass_pct, hard_gates_ok = await compute_full_confirmation(
        interp.coin, interp.direction, df, ind, zones,
    )

    # Geen bericht (autonoom marktscan-signaal, zie app/market_scanner.py)
    # betekent geen bron-niveaus om mee te wegen — die komen altijd uit een
    # gedeeld screenshot. De SR-zone-niveaus (zone_levels, in
    # setup_eval.evaluate_day_trading_setup) blijven wel gewoon meetellen,
    # die komen niet uit een bericht.
    message_levels = (
        [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id, interp.coin)]
        if message_id is not None else []
    )
    evaluation = evaluate_day_trading_setup(
        interp.direction, df, ind, zones, (confirmed, reason, pass_pct, hard_gates_ok),
        lambda zone_price: repo.recent_sr_zone_failure(interp.coin, interp.direction, zone_price, ind.atr),
        message_levels,
    )
    confirmed, reason, pass_pct, hard_gates_ok = (
        evaluation.confirmed, evaluation.reason, evaluation.pass_pct, evaluation.hard_gates_ok,
    )
    stop_take = risk.StopTake(stop_loss=evaluation.stop_loss, take_profit=evaluation.take_profit)
    nearest_sr_zone_price = evaluation.nearest_sr_zone_price
    suggested_entry_low, suggested_entry_high = evaluation.suggested_entry_low, evaluation.suggested_entry_high
    sniper_entry_price, sniper_reason = evaluation.sniper_entry_price, evaluation.sniper_reason
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
        "pass_pct": pass_pct,
        "hard_gates_ok": int(hard_gates_ok),
        "nearest_sr_zone_price": nearest_sr_zone_price,
        "suggested_entry_low": suggested_entry_low,
        "suggested_entry_high": suggested_entry_high,
        "sniper_entry_price": sniper_entry_price,
        "sniper_reason": sniper_reason,
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
    # Niet bij een stille refresh (marktscan ververst een signaal dat al open
    # stond, niemand krijgt een melding): dan is er geen nieuwe melding die
    # de andere kant achterhaalt. Anders zette elke scancyclus een net
    # gemelde tegengestelde kans (bv. een smc-short tegen een genomen
    # 4u-long in) op genegeerd, met een 'Kans vervallen' naar alle eigenaars.
    existing = repo.find_open_signal(interp.coin, interp.direction)
    silent_refresh = existing is not None and not notify_on_update
    ignored = [] if silent_refresh else repo.auto_ignore_opposite_pending(interp.coin, interp.direction)
    if ignored:
        logger.info("%s nog niet genomen tegenovergestelde melding(en) voor %s automatisch genegeerd",
                     len(ignored), interp.coin)
        for user in ignored:
            try:
                repo.create_notification(
                    user["id"], "expired_signal",
                    f"Kans op {interp.coin} vervallen",
                    f"Een nieuwe {interp.direction}-melding op {interp.coin} maakte de vorige kans achterhaald.",
                    f"/coins/{interp.coin}",
                )
            except Exception:
                logger.exception("Vervallen-kans melding voor %s naar gebruiker %s is mislukt",
                                  interp.coin, user["username"])

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
            try:
                repo.create_notification(
                    user["id"], "expired_signal",
                    f"Kans op {interp.coin} vervallen",
                    f"Een oude melding op {interp.coin} is vervangen door een nieuw signaal.",
                    f"/coins/{interp.coin}",
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
        muted = repo.is_coin_muted(user["id"], interp.coin)

        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, interp.direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
        )
        position_size = (
            risk.compute_position_size(risk_eur, ind.price, effective_stop_loss, cost_rate=cost_rate)
            if risk_eur is not None and confirmed else None
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

        # Geen telegram_chat_id-gate meer (Taak 11): push_notify.send_push
        # slaat een gebruiker zonder push-abonnement zelf al stilzwijgend
        # over, en telegram_chat_id wordt sinds de overstap naar push nooit
        # meer ingevuld voor nieuwe gebruikers.

        if muted:
            # De logboekregel bestaat al (hierboven aangemaakt): trackrecord
            # en dashboard-cijfers blijven kloppen, alleen de pushmelding
            # zelf wordt overgeslagen, dat is precies wat "uitzetten" betekent.
            logger.info("Coin %s is gemute voor gebruiker %s, geen pushmelding verstuurd",
                        interp.coin, user["username"])
            continue

        if "day_trading" in config.SIGNAL_TYPE_INFO_ONLY:
            logger.info("day_trading staat op alleen-informatie, geen pushmelding voor %s", interp.coin)
            continue

        if not confirmed:
            # Laag vertrouwen (technical_confirmed=0) krijgt nooit meer een
            # pushmelding, ongeacht de bron (gedeeld bericht of autonome
            # marktscan) — omgekeerd van de eerdere keuze om een gedeeld
            # bericht altijd te melden, ook bij afwijzing: dat leverde in de
            # praktijk vooral ruis op. De logboekregel hierboven blijft wel
            # gewoon bestaan, het trackrecord blijft compleet en zichtbaar
            # op het dashboard, alleen de melding zelf wordt overgeslagen —
            # zelfde patroon als de muted-continue hierboven.
            logger.info("Laag vertrouwen voor %s niet gemeld aan gebruiker %s (technical_confirmed=0)",
                        interp.coin, user["username"])
            continue

        force_silent = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            title = push_notify.alert_title(interp.coin, interp.direction, f"Community, {signal_data['confidence']}")
            body = (
                f"Entry {signal_data['price']:.4f}\n"
                f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            )
            if suggested_entry_low is not None:
                body += f"\nMogelijk betere entry: {suggested_entry_low:.4f}–{suggested_entry_high:.4f}"
            if signal_data.get("sniper_entry_price") is not None:
                body += f"\n🎯 Sniper: {signal_data['sniper_entry_price']:.4f} — {signal_data['sniper_reason']}"
            if signal_data.get("repeated_loss_note"):
                body += f"\n{signal_data['repeated_loss_note']}"
            if signal_data.get("context_note"):
                body += f"\n{signal_data['context_note']}"
            await push_notify.send_push(
                user["id"], title, body, f"/coins/{interp.coin}#signal-{signal_id}", silent=force_silent,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Pushmelding voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
            continue

        # Geen proactieve mute-suggestie meer na herhaald negeren
        # (dashboard-only, zie de declutter-ronde van 2026-09-14): muten kan
        # nog gewoon via het dashboard, alleen de Telegram-push is vervallen.


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
        # Geen telegram_chat_id-gate meer (Taak 11): push_notify.send_push
        # slaat een gebruiker zonder push-abonnement zelf al stilzwijgend
        # over, en telegram_chat_id wordt sinds de overstap naar push nooit
        # meer ingevuld voor nieuwe gebruikers.
        if not entry or entry["exit_price"] is not None or entry["status"] == "genegeerd":
            continue
        if repo.is_coin_muted(user["id"], signal_data["coin"]):
            continue

        message_data = signal_data

        force_silent = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            coin = message_data["coin"]
            confirmed = message_data["technical_confirmed"]
            title = f"{push_notify.coin_symbol(coin)} {coin} {message_data['direction']}, update"
            # Regel-per-regel-opbouw, zelfde reden als process_day_trading_signal
            # hierboven (visuele verfijning, 2026-09-30): een dichte, met ·
            # gescheiden regel is lastig te scannen op een lockscreen.
            # De entry-zone-regel hoort hier ook in te staan, anders mist deze
            # melding (die de marktscan elke cyclus stuurt voor een al open
            # signaal) 'm juist, terwijl de signaalkaart 'm wel altijd toont.
            suggested_low = message_data.get("suggested_entry_low")
            suggested_high = message_data.get("suggested_entry_high")
            if confirmed:
                body = (
                    f"Nieuwe prijs {message_data['price']:.4f}\n"
                    f"Stop {message_data['stop_loss']:.4f} · Take profit {message_data['take_profit']:.4f}"
                )
                if suggested_low is not None:
                    body += f"\nMogelijk betere entry: {suggested_low:.4f}–{suggested_high:.4f}"
                if message_data.get("sniper_entry_price") is not None:
                    body += f"\n🎯 Sniper: {message_data['sniper_entry_price']:.4f} — {message_data['sniper_reason']}"
            else:
                body = f"Nieuwe prijs {message_data['price']:.4f} · nog geen sterke kans"
            if message_data.get("repeated_loss_note"):
                body += f"\n{message_data['repeated_loss_note']}"
            await push_notify.send_push(user["id"], title, body, f"/coins/{coin}#signal-{signal_id}", silent=force_silent)
        except Exception:
            logger.exception("Pushmelding (update) voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
