"""Structuur-setups live: het recept achter de handgetekende trades (breuk van een lijn of range op 30m, terugkeer naar het
gebroken niveau, limietorder, stop net achter de terugkeer, ladder van doelen), gemeld vóórdat de trade uitspeelt.

Drie stappen, elke 5 minuten in de SMC-snelcyclus:
  1. Ontdekken: de detector uit app/replay/breakretest.py (zelfde code als de toets, alleen gesloten candles) vindt een verse
     breuk. Claude geeft een oordeel A, B of C op de kwaliteit. Claude verzint geen prijzen: niveau, stop en doelen komen uit code.
  2. Melden: elke breuk met een plan. A klinkt luid, B, C en een breuk zonder oordeel zijn stil. Het plan staat erin: limietniveau, stop en doelen.
  3. Volgen: raakt de koers het niveau, dan wordt het een gewoon signaal (trade_type 'structuur'), zodat journaal, uitkomst en Bewijs
     werken zonder extra code. Keert de koers terug voorbij het niveau, dan vervalt de setup.

Eerlijk over wat dit is: op een jaar candles scoorde de mechanische versie van dit recept -0,16R netto (zie scripts/breakretest_scan.py).
Het oordeel van Claude moet dat verschil maken en dat is een hypothese. Alles gaat live met het label ongetest, Bewijs toont de
score, en de motor gaat vanzelf uit als de laatste STRUCTURE_MAX_NEGATIVE afgeronde signalen samen negatief zijn."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from app import chance_checks, config, repo, smc_eval
from app.replay import breakretest as br
from app.replay.lab import add_indicators
from app.track_record import signal_r

logger = logging.getLogger("structure_live")

BAR = pd.Timedelta(minutes=br.BAR_MINUTES)
CANDLES_SHOWN = 48
CHART_BARS = 60
MIN_RR = 2.0
REASON_MAX = 240
GRADES = ("A", "B", "C")

SYSTEM_PROMPT = (
    "Je bent een ervaren daytrader die breuken van een lijn of range op de 30-minutengrafiek beoordeelt voor een eigen "
    "handelsplan: breuk, terugkeer naar het gebroken niveau, limietorder daar, stop net erachter, doelen op liquiditeit. "
    "De code heeft de cijfers al gecontroleerd en berekend: jij verzint of wijzigt geen prijs. Jij beoordeelt alleen de kwaliteit. "
    "A: schone structuur (een duidelijke lijn of range met minstens twee aanrakingen), een breuk die door de lijn gaat, en een plan met "
    "ruimte tot het doel. B: bruikbaar, ook als er één zwak punt is (weinig volume, korte lijn, matig doel). C: alleen bij een echt "
    "probleem: rommelige structuur, te weinig ruimte tot het doel, of een breuk recht tegen een sterke hogere trend in. Geef geen C "
    "omdat je twijfelt: twijfel je tussen B en C, kies B; twijfel je tussen A en B, kies A als de lijn of range schoon is. "
    "Schrijf de reden in het Nederlands, in één of twee korte zinnen, zonder opsmuk."
)
TOOL = {
    "name": "record_grade",
    "description": "Leg het oordeel over deze structuur-setup vast.",
    "input_schema": {
        "type": "object",
        "properties": {"grade": {"type": "string", "enum": list(GRADES)},
                       "reason": {"type": "string", "description": "Eén of twee korte zinnen, maximaal 240 tekens."}},
        "required": ["grade", "reason"],
    },
}


def _r(x: float) -> float:
    return float(f"{x:.6g}")


def line_value(setup: dict, at: pd.Timestamp) -> float:
    """Waarde van de gebroken lijn op een tijdstip: de lijn loopt per 30m-candle door vanaf het eerste zwaaipunt."""
    p1 = pd.Timestamp(setup["p1_at"])
    return setup["line_a"] + setup["line_slope"] * ((at - p1) / BAR)


def should_disable(results: list[dict], max_negative: int) -> bool:
    """Zelfde regel als het markt-script: na genoeg afgeronde signalen die samen negatief zijn gaat de motor uit."""
    if len(results) < max_negative:
        return False
    return sum(signal_r(r) or 0.0 for r in results) < 0


def fresh_breaks(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray]:
    """(bars met indicatoren, verse breuken, pivot-hoog, pivot-laag). Vers is een breuk die nog binnen het retest-venster ligt
    en waarvan de koers het niveau sindsdien niet raakte of terug veroverde: dan staat de limietorder nog open."""
    b = add_indicators(bars).reset_index(drop=True)
    events = br.find_breaks(bars)
    n = len(b)
    keep = []
    for ev in events.itertuples():
        if ev.bar < n - 1 - br.RETEST_BARS or ev.bar >= n:
            continue
        sign = 1 if ev.direction == "long" else -1
        alive = True
        for j in range(ev.bar + 1, n):
            level = br.level_at(ev, j)
            touched = b.at[j, "high"] >= level if ev.direction == br.SHORT else b.at[j, "low"] <= level
            reclaimed = -sign * (b.at[j, "close"] - level) > br.BREAK_ATR * ev.atr
            if touched or reclaimed:
                alive = False
                break
        if alive:
            keep.append(ev.Index)
    p_high, p_low = br._pivots(b)
    return b, events.loc[keep].reset_index(drop=True), p_high, p_low


def stop_with_room(direction: str, level: float, extreme: float, atr: float) -> float:
    """Stop net voorbij de terugkeer (kwart ATR), minstens SMC_MIN_STOP_PCT van het niveau: een stop vlak achter het niveau wordt door een wick geraakt
    waarna de koers alsnog de goede kant op gaat."""
    short = direction == br.SHORT
    stop = max(level, extreme) + br.STOP_ATR * atr if short else min(level, extreme) - br.STOP_ATR * atr
    return smc_eval.floor_stop(direction, level, stop)


def plan_for(ev, b: pd.DataFrame, levels: list[float], level: float, extreme: float) -> Optional[dict]:
    """Stop en doelen uit code. None als de stopafstand buiten het toegestane bereik valt of er geen doel ligt."""
    short = ev.direction == br.SHORT
    stop = stop_with_room(ev.direction, level, extreme, ev.atr)
    risk = abs(level - stop)
    risk_pct = risk / level * 100
    if risk_pct > br.MAX_STOP_PCT or (short and level >= stop) or (not short and level <= stop):
        return None
    # Doelen op zwaaipunten als die ruim genoeg liggen, anders een vaste ladder van 1, 2 en 3R. De eis dat het tweede doel op een zwaaipunt minstens
    # MIN_RR ver ligt hield in een stijging naar nieuwe hoogtes bijna elke breuk tegen, en het onderzoek liet zien dat zulke filters de kwaliteit niet verbeteren.
    nearest = br.ladder_targets(ev.direction, level, risk, "niveaus", levels)
    on_levels = nearest is not None and (nearest[0][1] if len(nearest[0]) > 1 else nearest[0][0]) >= MIN_RR
    ladder = nearest if on_levels else br.ladder_targets(ev.direction, level, risk, "ladder 1-2-3R", levels)
    r_list = ladder[0]
    sign = -1 if short else 1
    return {"level": level, "stop": stop, "risk_pct": risk_pct, "targets_r": list(r_list),
            "targets": [level + sign * risk * r for r in r_list], "from_levels": on_levels}


def explain_no_plan(ev, levels: list[float], level: float, extreme: float) -> str:
    """Waarom er geen plan kwam, met de getallen: de stopafstand, en de ruimte tot de eerstvolgende doelen op zwaaipunten."""
    stop = stop_with_room(ev.direction, level, extreme, ev.atr)
    risk = abs(level - stop)
    risk_pct = risk / level * 100 if level else 0.0
    if risk_pct > br.MAX_STOP_PCT:
        return (f"Stop {risk_pct:.2f}% van het niveau, toegestaan is maximaal {br.MAX_STOP_PCT:g}%. "
                f"Niveau {_r(level)}, stop {_r(stop)}.")
    return "Stop in orde, geen plan om een andere reden."


def take_profit_of(plan: dict) -> float:
    """Het signaal meet één doel: het tweede van de ladder (of het eerste als er maar één is). De ladder staat in de melding."""
    targets = plan["targets"]
    return targets[1] if len(targets) > 1 else targets[0]


def judge_context(coin: str, ev, b: pd.DataFrame, plan: dict) -> dict:
    tail = b.tail(CANDLES_SHOWN)
    median_vol = float(b["volume"].tail(100).median()) or 1.0
    return {
        "coin": coin, "kant": ev.direction, "soort": "horizontale range" if ev.kind == "RANGE" else "schuine lijn",
        "aanrakingen": int(ev.touches), "lengte_candles": int(ev.span), "breukvolume_x_gemiddeld": _r(ev.vol_ratio),
        "met_trend_ema21_200": bool(ev.with_trend), "atr_30m_pct": _r(ev.atr / float(b["close"].iloc[-1]) * 100),
        "plan": {"limiet": _r(plan["level"]), "stop": _r(plan["stop"]), "risico_pct": _r(plan["risk_pct"]),
                 "doelen": [_r(t) for t in plan["targets"]], "doelen_in_R": [_r(r) for r in plan["targets_r"]],
                 "doelen_zijn_zwaaipunten": bool(plan["from_levels"])},
        "laatste_candles_30m": [[c.timestamp.strftime("%d %H:%M"), _r(c.open), _r(c.high), _r(c.low), _r(c.close),
                                 _r(c.volume / median_vol)] for c in tail.itertuples()],
        "kolommen": "tijd UTC, open, hoog, laag, slot, volume relatief aan de mediaan",
    }


def call_claude(context: dict) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.STRUCTURE_MODEL, max_tokens=400, system=SYSTEM_PROMPT, tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_grade"},
        messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
    )
    return next(blk for blk in response.content if blk.type == "tool_use").input


def parse_grade(payload: dict) -> tuple[Optional[str], str]:
    grade = str(payload.get("grade", "")).strip().upper()
    return (grade if grade in GRADES else None), str(payload.get("reason", "")).strip()[:REASON_MAX]


def alert_body(setup: dict, plan: dict) -> str:
    from app import push_notify
    rr = abs(plan["targets"][0] - plan["level"]) / abs(plan["level"] - plan["stop"])
    targets = " · ".join(f"{push_notify.fmt_price(t)} ({r:g}R)" for t, r in zip(plan["targets"], plan["targets_r"]))
    kind = "Range" if setup["kind"] == "RANGE" else "Lijn"
    return push_notify.trade_body("Limietorder", plan["level"], plan["stop"], take_profit_of(plan), None,
                                  f"Doelen {targets}", f"{kind} gebroken op 30m. {setup['reason'] or ''}".strip())


async def _push_all(title: str, body: str, url: str, tag: str, loud: bool) -> None:
    from app import push_notify
    for user in repo.list_users():
        quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await push_notify.send_push(user["id"], title, body, url, silent=quiet or not loud, tag=tag)
        except Exception:
            logger.exception("Structuur-melding voor %s naar gebruiker %s is mislukt", tag, user["username"])


async def _discover(coin: str, now: datetime) -> None:
    from app import exchange, push_notify
    df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="30m", limit=300)
    closed = df[df["timestamp"] + BAR <= pd.Timestamp(now)].reset_index(drop=True)
    if len(closed) < br.LOOKBACK + 20:
        return
    b, events, p_high, p_low = fresh_breaks(closed)
    n = len(b)
    for ev in events.itertuples():
        break_at = (b.at[ev.bar, "timestamp"] + BAR).isoformat()
        next_start = b.at[n - 1, "timestamp"] + BAR
        level = br.level_at(ev, n)
        extreme = float(b["high" if ev.direction == br.SHORT else "low"].iloc[ev.bar:n].agg("max" if ev.direction == br.SHORT else "min"))
        levels = br.known_levels(b, p_high, p_low, ev.direction, ev.bar)
        plan = plan_for(ev, b, levels, level, extreme)
        if plan is None:
            # Bewaard zodat de pagina Setups kan tonen hoeveel breuken er waren en waarom er niets uitkwam.
            repo.insert_structure_setup({
                "coin": coin, "direction": ev.direction, "kind": ev.kind, "break_at": break_at, "p1_at": b.at[ev.p1, "timestamp"].isoformat(),
                "line_a": ev.a, "line_slope": ev.slope, "atr": ev.atr, "grade": None,
                "reason": explain_no_plan(ev, levels, level, extreme), "features": "{}", "state": "geen_plan",
                "expires_at": break_at, "plan": None})
            continue
        row = {"coin": coin, "direction": ev.direction, "kind": ev.kind, "break_at": break_at,
               "p1_at": b.at[ev.p1, "timestamp"].isoformat(), "line_a": ev.a, "line_slope": ev.slope, "atr": ev.atr,
               "grade": None, "reason": None, "state": "oordeel",
               "features": json.dumps({"vol_ratio": ev.vol_ratio, "span": int(ev.span), "touches": int(ev.touches),
                                       "with_trend": bool(ev.with_trend)}),
               "expires_at": (next_start + br.RETEST_BARS * BAR).isoformat(),
               "plan": json.dumps({**plan, "levels": levels, "break_extreme": extreme,
                                   "candles": [[c.timestamp.isoformat(), c.open, c.high, c.low, c.close] for c in b.tail(CHART_BARS).itertuples()]})}
        setup_id = repo.insert_structure_setup(row)
        if setup_id is None:
            continue
        try:
            grade, reason = parse_grade(await asyncio.to_thread(call_claude, judge_context(coin, ev, b, plan)))
        except Exception:
            logger.exception("Oordeel van Claude voor %s is mislukt", coin)
            grade, reason = None, ""
        capped = repo.count_structure_alerts_since((now - timedelta(hours=24)).isoformat()) >= config.STRUCTURE_MAX_ALERTS_PER_DAY
        # Elke breuk met een plan wordt gemeld, ook C en een breuk zonder oordeel: jij beslist, het oordeel staat erbij. Alleen A klinkt luid.
        # Bewijs houdt C apart (trade_type 'structuur_c'), zodat zichtbaar blijft of het oordeel iets toevoegt.
        state = "niet_gemeld" if capped else "waiting"
        repo.update_structure_judgement(setup_id, grade, reason, state)
        logger.info("Structuur %s %s %s: oordeel %s (%s)", coin, ev.direction, ev.kind, grade, state)
        if state == "waiting":
            setup = {**row, "id": setup_id, "reason": reason}
            await _push_all(push_notify.alert_title(coin, ev.direction, f"Structuur {grade or 'zonder oordeel'}"), alert_body(setup, plan),
                            f"/structuur#structuur-{setup_id}", f"structuur-{coin}", loud=grade == "A")


async def _fire(setup: dict, plan: dict, entry: float, stop: float, filled_at: pd.Timestamp) -> None:
    from app import push_notify
    from app.signal_processor import fanout_confirmed_signal
    coin, direction = setup["coin"], setup["direction"]
    fired = {**plan, "level": entry, "stop": stop}
    risk = abs(entry - stop)
    sign = -1 if direction == br.SHORT else 1
    fired["targets"] = [entry + sign * risk * r for r in plan["targets_r"]]
    take = take_profit_of(fired)
    grade = setup["grade"] or "zonder oordeel"
    narrative = f"Structuur {grade}: {setup['kind'].lower()} gebroken op 30m, terugkeer naar {push_notify.fmt_price(entry)}. {setup['reason'] or ''}".strip()
    reason, pass_pct = chance_checks.finish(chance_checks.structure_checks(chance_checks.parse_features(setup.get("features")), plan, setup["grade"]))
    signal_id = repo.insert_signal({
        "message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": "structuur_c" if setup["grade"] == "C" else "structuur",
        "pattern_name": "Structuur", "price": entry, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None,
        "ema9": None, "ema21": None, "atr": None, "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": pass_pct,
        "hard_gates_ok": 1, "confidence": f"Structuur {grade}", "reason": reason, "stop_loss": stop,
        "take_profit": take, "context_note": None, "is_practice": 0, "plain_explanation": narrative, "suggested_entry_low": None,
        "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None,
    })
    repo.set_structure_state(setup["id"], "fired", signal_id)
    repo.update_structure_plan(setup["id"], json.dumps({**plan, "fired": {"entry": entry, "stop": stop, "targets": fired["targets"], "hits": 0, "closed": False, "at": filled_at.isoformat(),
                                                                       "events": [{"at": filled_at.isoformat(), "text": "Limiet geraakt, de trade loopt"}]}}))
    rr = abs(take - entry) / risk
    targets = " · ".join(f"{push_notify.fmt_price(t)} ({r:g}R)" for t, r in zip(fired["targets"], plan["targets_r"]))
    await fanout_confirmed_signal(
        signal_id, coin, direction, entry, stop, take, entry,
        title=push_notify.alert_title(coin, direction, f"Structuur {grade} gevuld"),
        make_body=lambda *_: push_notify.trade_body("Entry", entry, stop, take, rr, f"Doelen {targets}", "Limiet geraakt, de trade loopt."),
        reason=reason, signal_type="structuur_c" if setup["grade"] == "C" else "structuur", force_silent=setup["grade"] == "C",
    )


def _shadow_levels(setup: dict, plan: dict, entry: float, stop: float) -> tuple[float, float]:
    risk = abs(entry - stop)
    sign = -1 if setup["direction"] == br.SHORT else 1
    targets_r = plan["targets_r"]
    return stop, entry + sign * risk * (targets_r[1] if len(targets_r) > 1 else targets_r[0])


async def _fire_shadow(setup: dict, plan: dict, entry: float, stop: float) -> None:
    """Een setup met oordeel C die toch vult: alleen een signaal voor Bewijs (trade_type 'structuur_c'), geen melding en geen journaalregels."""
    stop, take = _shadow_levels(setup, plan, entry, stop)
    signal_id = repo.insert_signal({
        "message_id": None, "coin": setup["coin"], "direction": setup["direction"], "category": "day_trading", "trade_type": "structuur_c",
        "pattern_name": "Structuur C", "price": entry, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None,
        "atr": None, "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Structuur C (schaduw)",
        "reason": f"Oordeel C van Claude, stil gevolgd. {setup['reason'] or ''}".strip(), "stop_loss": stop, "take_profit": take, "context_note": None,
        "is_practice": 0, "plain_explanation": None, "suggested_entry_low": None, "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None,
    })
    repo.set_structure_state(setup["id"], "fired", signal_id)


async def _track(now: datetime) -> None:
    from app import exchange
    waiting = repo.list_structure_setups(("waiting", "schaduw"))
    for coin in sorted({s["coin"] for s in waiting}):
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="5m", limit=80)
        except Exception:
            logger.exception("5m-candles voor %s niet op te halen, setups blijven wachten", coin)
            continue
        for s in (x for x in waiting if x["coin"] == coin):
            plan = json.loads(s["plan"])
            after = df[df["timestamp"] >= pd.Timestamp(s["break_at"])]
            extreme = plan["break_extreme"]
            for c in after.itertuples():
                level = line_value(s, c.timestamp)
                # Een koers die voorbij het niveau gaat raakt het niveau ook: een limietorder daar vult dan, dus er is geen
                # aparte "teruggewonnen"-tak. Een mislukte breuk eindigt zo meteen in de stop, zoals de toets het ook meet.
                reach = c.high >= level if s["direction"] == br.SHORT else c.low <= level
                if reach:
                    stop = stop_with_room(s["direction"], level, extreme, s["atr"])
                    risk_pct = abs(level - stop) / level * 100
                    if risk_pct <= br.MAX_STOP_PCT:
                        try:
                            await (_fire(s, plan, level, stop, c.timestamp) if s["state"] == "waiting" else _fire_shadow(s, plan, level, stop))
                        except Exception:
                            logger.exception("Structuur-setup %s voor %s is niet gemeld", s["id"], coin)
                    else:
                        repo.set_structure_state(s["id"], "overgeslagen")
                    break
                extreme = max(extreme, c.high) if s["direction"] == br.SHORT else min(extreme, c.low)


def _target_message(setup: dict, plan: dict, fired: dict, n: int) -> tuple[str, str]:
    """Melding bij het n-de doel (1-based). Bij het eerste doel hoort de instructie uit het recept: stop naar de instap."""
    from app import push_notify
    targets, r_list = fired["targets"], plan["targets_r"]
    title = push_notify.alert_title(setup["coin"], setup["direction"], f"T{n} geraakt")
    first = f"T{n} {push_notify.fmt_price(targets[n - 1])} ({r_list[n - 1]:g}R) geraakt."
    if n == len(targets):
        return title, f"{first} Laatste doel: de trade is klaar."
    nxt = f"Volgend doel T{n + 1} {push_notify.fmt_price(targets[n])} ({r_list[n]:g}R)."
    if n == 1:
        return title, f"{first}\nZet je stop op de instap {push_notify.fmt_price(fired['entry'])}.\n{nxt}"
    return title, f"{first}\n{nxt}"


async def _follow(now: datetime) -> None:
    """Volgt gevulde setups: meldt elk doel dat raakt (bij het eerste hoort 'stop naar de instap') en sluit de setup bij
    stop, terugkeer naar de instap of het laatste doel. Het signaal zelf meet alleen het tweede doel, deze ladder is voor jou."""
    from app import exchange, push_notify
    rows = [s for s in repo.list_structure_setups(("fired",), 30) if (json.loads(s["plan"]).get("fired") or {}).get("closed") is False]
    for coin in sorted({s["coin"] for s in rows}):
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="5m", limit=300)
        except Exception:
            logger.exception("5m-candles voor %s niet op te halen, ladder wordt later gevolgd", coin)
            continue
        for s in (x for x in rows if x["coin"] == coin):
            plan = json.loads(s["plan"])
            fired = plan["fired"]
            short = s["direction"] == br.SHORT
            hits, targets = fired["hits"], fired["targets"]
            live_stop = fired["entry"] if hits >= 1 else fired["stop"]
            changed, messages = False, []
            # Alleen gesloten 5m-candles, en elke candle maar één keer: anders zou een stop op de instap (na T1) terugwerkend
            # op candles van vóór T1 worden toegepast.
            closed = df[df["timestamp"] + pd.Timedelta(minutes=5) <= pd.Timestamp(now)]
            seen = fired.get("seen")
            new = closed[closed["timestamp"] > pd.Timestamp(seen)] if seen else closed[closed["timestamp"] >= pd.Timestamp(fired["at"])]
            for c in new.itertuples():
                fired["seen"] = c.timestamp.isoformat()
                changed = True
                if (c.high >= live_stop) if short else (c.low <= live_stop):
                    fired["closed"], changed = True, True
                    fired.setdefault("events", []).append({"at": c.timestamp.isoformat(), "text": "Stop op de instap geraakt, break-even" if hits >= 1 else "Stop geraakt"})
                    break
                while hits < len(targets) and ((c.low <= targets[hits]) if short else (c.high >= targets[hits])):
                    hits += 1
                    # T1 en het laatste doel zijn luid (er moet iets gebeuren: stop naar de instap, of de trade is klaar), de doelen ertussen stil.
                    messages.append((*_target_message(s, plan, fired, hits), hits == 1 or hits == len(targets)))
                    fired.setdefault("events", []).append({"at": c.timestamp.isoformat(), "text": f"T{hits} geraakt ({plan['targets_r'][hits - 1]:.1f}R)"})
                    if hits == 1:
                        live_stop = fired["entry"]
                    changed = True
                if hits == len(targets):
                    fired["closed"] = True
                    break
            if changed:
                fired["hits"] = hits
                repo.update_structure_plan(s["id"], json.dumps(plan))
            for title, body, loud in messages:
                await _push_all(title, body, push_notify.signal_url(coin, s["signal_id"]), f"structuur-{coin}-t", loud=loud)


async def run(now: Optional[datetime] = None) -> None:
    """Draait in de SMC-snelcyclus."""
    now = now or datetime.now(timezone.utc)
    repo.expire_structure_setups(now.isoformat())
    if not config.STRUCTURE_ENABLED:
        return
    if should_disable(repo.list_type_results("structuur", config.STRUCTURE_MAX_NEGATIVE), config.STRUCTURE_MAX_NEGATIVE):
        repo.notify_engine_disabled("Structuur-breuken", f"De laatste {config.STRUCTURE_MAX_NEGATIVE} afgeronde signalen zijn samen negatief. Zie Bewijs.")
        return
    symbols = {c["symbol"] for c in repo.list_coins()}
    for coin in config.BASE_COINS:
        if coin not in symbols:
            continue
        try:
            await _discover(coin, now)
        except Exception:
            logger.exception("Structuur-check voor %s is mislukt", coin)
    await _track(now)
    await _follow(now)
    repo.beat("structuur", f"{len(config.BASE_COINS)} coins gecontroleerd")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
