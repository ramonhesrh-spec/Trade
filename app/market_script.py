"""Markt-script: elke 4 uur schrijft Claude per coin een korte duiding en maximaal twee scenario's met een voorwaarde
("sluit 5m boven 67.400", "sweep van 66.900 en terug erboven"). De code toetst elk scenario hard voordat het wordt
bewaard: wat niet klopt valt af. Een motor in de SMC-snelcyclus kijkt elke 5 minuten of een voorwaarde klopt. Zodra dat zo
is wordt het een gewoon signaal (trade_type 'script'), dus journaal, uitkomst en Bewijs werken zonder extra code.

Eerlijk over wat dit is: een scenario van Claude is een hypothese. Bewijs toont de score. De melding zegt ongetest en de
motor gaat vanzelf uit als de laatste SCRIPT_MAX_NEGATIVE afgeronde scenario's samen negatief zijn."""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import config, repo
from app.track_record import signal_r

logger = logging.getLogger("market_script")

TRIGGER_TYPES = ("close_above", "close_below", "sweep_reclaim")
MAX_SCENARIOS = 2
EXPIRY_HOURS = 12
MAX_LEVEL_DISTANCE_ATR = 3.0
MAX_ENTRY_DISTANCE_ATR = 1.5
MIN_RR = 2.0
SWEEP_LOOKBACK_BARS = 6
REASON_MAX = 300

TRIGGER_TEXT = {
    "close_above": "5m-candle sluit boven {level}",
    "close_below": "5m-candle sluit onder {level}",
    "sweep_reclaim_long": "sweep onder {level} en terug erboven",
    "sweep_reclaim_short": "sweep boven {level} en terug eronder",
}


@dataclass
class Scenario:
    direction: str
    trigger_type: str
    trigger_level: float
    entry: float
    stop_loss: float
    take_profit: float
    reason: str

    def as_row(self) -> dict:
        return {"direction": self.direction, "trigger_type": self.trigger_type, "trigger_level": self.trigger_level,
                "entry": self.entry, "stop_loss": self.stop_loss, "take_profit": self.take_profit, "reason": self.reason}


def trigger_text(trigger_type: str, direction: str, level: float) -> str:
    key = f"sweep_reclaim_{direction}" if trigger_type == "sweep_reclaim" else trigger_type
    return TRIGGER_TEXT[key].format(level=f"{level:g}")


def rr_of(direction: str, entry: float, stop: float, take: float) -> float:
    risk = abs(entry - stop)
    return abs(take - entry) / risk if risk else 0.0


def validate_scenarios(raw: list, price: float, atr: float, min_stop_pct: Optional[float] = None) -> tuple[list[Scenario], list[str]]:
    """Geeft (geldige scenario's, redenen van wat afviel). Maximaal MAX_SCENARIOS blijven over."""
    min_stop_pct = config.SMC_MIN_STOP_PCT if min_stop_pct is None else min_stop_pct
    good: list[Scenario] = []
    dropped: list[str] = []
    for i, item in enumerate(raw or []):
        try:
            direction = item["direction"]
            ttype = item["trigger"]["type"]
            level = float(item["trigger"]["level"])
            entry, stop, take = float(item["entry"]), float(item["stop_loss"]), float(item["take_profit"])
            reason = str(item.get("reason", "")).strip()
        except (KeyError, TypeError, ValueError):
            dropped.append(f"{i}: onvolledig")
            continue
        info = f"{direction} {ttype} niveau {level:g} entry {entry:g} stop {stop:g} take {take:g}"
        if direction not in ("long", "short") or ttype not in TRIGGER_TYPES:
            dropped.append(f"{i}: onbekende richting of voorwaarde")
        elif not reason:
            dropped.append(f"{i}: geen reden")
        elif not ((direction == "long" and stop < entry < take) or (direction == "short" and take < entry < stop)):
            dropped.append(f"{i}: stop, entry en take staan niet in de juiste volgorde ({info})")
        elif abs(entry - stop) / entry * 100 < min_stop_pct:
            dropped.append(f"{i}: stop te dichtbij ({info})")
        elif rr_of(direction, entry, stop, take) < MIN_RR:
            dropped.append(f"{i}: R:R onder {MIN_RR} ({info})")
        elif atr <= 0 or abs(level - price) > MAX_LEVEL_DISTANCE_ATR * atr or abs(entry - price) > MAX_ENTRY_DISTANCE_ATR * atr:
            dropped.append(f"{i}: niveau of entry te ver van de prijs ({info})")
        elif ttype == "close_above" and level <= price:
            dropped.append(f"{i}: voorwaarde klopt al ({info})")
        elif ttype == "close_below" and level >= price:
            dropped.append(f"{i}: voorwaarde klopt al ({info})")
        elif ttype == "sweep_reclaim" and not ((direction == "long" and level < price) or (direction == "short" and level > price)):
            dropped.append(f"{i}: sweep ligt aan de verkeerde kant van de prijs ({info})")
        else:
            good.append(Scenario(direction, ttype, level, entry, stop, take, reason[:REASON_MAX]))
    if len(good) > MAX_SCENARIOS:
        dropped += [f"{i}: meer dan {MAX_SCENARIOS} scenario's" for i in range(MAX_SCENARIOS, len(good))]
        good = good[:MAX_SCENARIOS]
    return good, dropped


def check_trigger(trigger_type: str, direction: str, level: float, closed_5m: pd.DataFrame) -> bool:
    """Alleen gesloten 5m-candles (de vormende candle is er al afgehaald). Een sweep telt binnen de laatste
    SWEEP_LOOKBACK_BARS candles, met de laatste sluiting terug over het niveau."""
    if closed_5m.empty:
        return False
    last = float(closed_5m["close"].iloc[-1])
    if trigger_type == "close_above":
        return last > level
    if trigger_type == "close_below":
        return last < level
    recent = closed_5m.tail(SWEEP_LOOKBACK_BARS)
    if direction == "long":
        return bool((recent["low"] < level).any()) and last > level
    return bool((recent["high"] > level).any()) and last < level


def still_actionable(direction: str, stop: float, take: float, last_close: float) -> bool:
    """Is de prijs al voorbij stop of take, dan is de kans verlopen."""
    return stop < last_close < take if direction == "long" else take < last_close < stop


def should_disable(results: list[dict], max_negative: int) -> bool:
    rs = [signal_r(r) for r in results]
    rs = [r for r in rs if r is not None]
    return len(rs) >= max_negative and sum(rs) < 0


SYSTEM_PROMPT = """Je bent de marktanalist van HesPulse en schrijft voor één coin een kort script voor de komende uren. \
Je krijgt alleen feiten uit een JSON-pakket. Verzin geen niveaus, nieuws of cijfers die er niet in staan.

Geef:
- summary: twee korte zinnen Nederlands, samen maximaal 220 tekens, zonder opsomming van alle cijfers. Wat gebeurt er nu en waarom (gebruik funding, liquidaties, nieuws, agenda alleen als ze in het pakket staan).
- bias: long, short of neutraal.
- scenarios: maximaal twee. Elk scenario is een voorwaarde met een plan. Een goed scenario heeft een niveau uit het pakket (dag-, week- of swinghoog en -laag, een SMC-zone), een voorwaarde die nu NOG NIET klopt, een limietorder, een stop achter een logisch niveau en een take bij het volgende niveau met minstens 2R.
- Voorwaarden: close_above (een 5m-candle sluit boven het niveau), close_below, of sweep_reclaim (de prijs steekt door het niveau en sluit terug). Bij sweep_reclaim long ligt het niveau onder de prijs, bij short erboven.
- Staat er geen goede kans in, geef een lege lijst. Dat is een goed antwoord.
Het pakket bevat onder 'toegestaan' de grenzen waar je scenario's op getoetst worden: houd je daaraan. Staat er 'vorige_poging_afgekeurd', dan zijn die scenario's om de genoemde reden afgekeurd: los precies dat op of geef een lege lijst.
Roep altijd de tool record_script aan."""

TOOL = {
    "name": "record_script",
    "description": "Legt het markt-script voor één coin vast.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "bias": {"type": "string", "enum": ["long", "short", "neutraal"]},
            "scenarios": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "enum": ["long", "short"]},
                        "trigger": {
                            "type": "object",
                            "properties": {"type": {"type": "string", "enum": list(TRIGGER_TYPES)}, "level": {"type": "number"}},
                            "required": ["type", "level"],
                        },
                        "entry": {"type": "number"},
                        "stop_loss": {"type": "number"},
                        "take_profit": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["direction", "trigger", "entry", "stop_loss", "take_profit", "reason"],
                },
            },
        },
        "required": ["summary", "bias", "scenarios"],
    },
}


def allowed_ranges(price: float, atr: float) -> dict:
    """De grenzen waar validate_scenarios op toetst, als getallen: zo hoeft Claude ze niet te raden."""
    return {
        "niveau_tussen": [round(price - MAX_LEVEL_DISTANCE_ATR * atr, 6), round(price + MAX_LEVEL_DISTANCE_ATR * atr, 6)],
        "entry_tussen": [round(price - MAX_ENTRY_DISTANCE_ATR * atr, 6), round(price + MAX_ENTRY_DISTANCE_ATR * atr, 6)],
        "minimale_stopafstand_pct": config.SMC_MIN_STOP_PCT, "minimale_rr": MIN_RR,
        "volgorde": "long: stop < entry < take. short: take < entry < stop. R:R = afstand entry-take gedeeld door afstand entry-stop.",
    }


def build_context(coin: str, price: float, atr: float, levels: dict, smc_zones: list[dict], derivs: Optional[dict],
                  liquidations: Optional[dict], agenda: list[dict], calls: list[dict], events: list[dict], now: datetime) -> dict:
    """Het hele pakket dat Claude ziet. Alleen feiten, afgerond op bruikbare precisie."""
    return {
        "coin": coin, "tijd_utc": now.strftime("%Y-%m-%d %H:%M"), "prijs": price, "atr_4u": round(atr, 6),
        "toegestaan": allowed_ranges(price, atr),
        "niveaus": levels, "smc_zones": smc_zones, "derivaten": derivs, "liquidaties_4u_usd": liquidations,
        "agenda_24u": [{"over_uren": round((a["at"] - now).total_seconds() / 3600, 1), "wat": a["label"]} for a in agenda],
        "community_calls_24u": calls, "nieuws_12u": events,
    }


def call_claude(context: dict) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.SCRIPT_MODEL, max_tokens=1200, system=SYSTEM_PROMPT, tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_script"},
        messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
    )
    return next(b for b in response.content if b.type == "tool_use").input


def process_response(payload: dict, price: float, atr: float) -> tuple[str, str, list[Scenario], list[str]]:
    scenarios, dropped = validate_scenarios(payload.get("scenarios"), price, atr)
    return str(payload.get("summary", "")).strip()[:260], payload.get("bias", "neutraal"), scenarios, dropped


def gather_context(coin: str, now: datetime) -> tuple[dict, float, float]:
    """Haalt alle bronnen op voor één coin. Een bron die ontbreekt (geen derivatendata, geen nieuws) laat het pakket
    korter worden, het script gaat dan door."""
    from app import derivs, exchange, indicators, market_calendar
    df4h = exchange.fetch_ohlcv(coin, timeframe="4h", limit=120)
    atr = indicators.compute_indicators(df4h).atr
    price = exchange.fetch_last_price(coin)
    df1d = exchange.fetch_ohlcv(coin, timeframe="1d", limit=10)
    closed_d = df1d.iloc[:-1]
    levels = {
        "gisteren_hoog": float(closed_d["high"].iloc[-1]), "gisteren_laag": float(closed_d["low"].iloc[-1]),
        "week_hoog": float(closed_d["high"].tail(7).max()), "week_laag": float(closed_d["low"].tail(7).min()),
        "swing_hoog_4u": float(df4h["high"].tail(20).max()), "swing_laag_4u": float(df4h["low"].tail(20).min()),
    }
    zones = [{"richting": s["direction"], "zone_laag": s["zone_low"], "zone_hoog": s["zone_high"],
              "structuur": s["structure_level"], "sweep": s["sweep_price"], "doel": s["liquidity_target"]}
             for s in repo.list_forming_smc_setups() if s["coin"] == coin]
    derivs_row = None
    try:
        d = pd.read_csv(derivs.cache_path(coin), index_col="ts", parse_dates=["ts"])
        last, ago = d.iloc[-1], d[d.index <= d.index[-1] - pd.Timedelta(hours=4)]
        derivs_row = {"funding": float(last["funding"]), "taker_ratio": float(last["taker_ratio"]),
                      "long_short_alle": float(last["global_ls"]), "long_short_top": float(last["top_ls"]),
                      "oi_verandering_4u_pct": round((last["oi_usd"] / ago.iloc[-1]["oi_usd"] - 1) * 100, 2) if len(ago) else None}
    except Exception:
        pass
    liq = repo.list_liquidations(coin, (now - timedelta(hours=4)).isoformat())
    liq_sum = {"longs": round(sum(r["long_usd"] for r in liq)), "shorts": round(sum(r["short_usd"] for r in liq))} if liq else None
    calls = []
    for c in repo.list_community_calls():
        at = datetime.fromisoformat(c["at"])
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        if (c["coin"] or "").upper() == coin and now - at <= timedelta(hours=24):
            calls.append({"richting": c["direction"], "uren_geleden": round((now - at).total_seconds() / 3600, 1)})
    events = [{"titel": e["title"], "kant": e["direction"], "impact": e["impact"]}
              for e in repo.list_recent_events(coin, (now - timedelta(hours=12)).isoformat(), limit=6)]
    ctx = build_context(coin, price, atr, levels, zones, derivs_row, liq_sum, market_calendar.upcoming(now, 24), calls, events, now)
    return ctx, price, atr


def generate_for_coin(coin: str, now: Optional[datetime] = None) -> Optional[int]:
    now = now or datetime.now(timezone.utc)
    ctx, price, atr = gather_context(coin, now)
    summary, bias, scenarios, dropped = process_response(call_claude(ctx), price, atr)
    if dropped:
        logger.info("%s: %s scenario('s) afgevallen: %s", coin, len(dropped), "; ".join(dropped))
        # Eén herkansing met de redenen erbij. Alleen overnemen als er daarmee meer geldige scenario's zijn.
        try:
            retry = process_response(call_claude({**ctx, "vorige_poging_afgekeurd": dropped}), price, atr)
            if len(retry[2]) > len(scenarios):
                summary, bias, scenarios, dropped = retry
                logger.info("%s: herkansing gaf %s geldige scenario('s)", coin, len(scenarios))
        except Exception:
            logger.exception("%s: herkansing mislukt, eerste poging blijft staan", coin)
    return repo.insert_market_script(coin, summary, bias, config.SCRIPT_MODEL, [s.as_row() for s in scenarios], len(dropped),
                                     (now + timedelta(hours=EXPIRY_HOURS)).isoformat())


def generate_all() -> None:
    if not config.SCRIPT_ENABLED:
        logger.info("Markt-script staat uit")
        return
    for row in repo.list_coins():
        try:
            generate_for_coin(row["symbol"])
        except Exception:
            logger.exception("Script voor %s is mislukt", row["symbol"])


def format_body(s: dict) -> str:
    from app import push_notify
    rr = rr_of(s["direction"], s["entry"], s["stop_loss"], s["take_profit"])
    return push_notify.trade_body("Limietorder", s["entry"], s["stop_loss"], s["take_profit"], rr,
                                  f"Als: {trigger_text(s['trigger_type'], s['direction'], s['trigger_level'])}", s["reason"],
                                  "Ongetest, zie Bewijs.")


async def _fire(s: dict) -> None:
    from app import push_notify
    from app.signal_processor import fanout_confirmed_signal
    coin, direction = s["coin"], s["direction"]
    reason = f"Markt-script: {trigger_text(s['trigger_type'], direction, s['trigger_level'])}. {s['reason']}"
    signal_id = repo.insert_signal({
        "message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": "script",
        "pattern_name": "Markt-script", "price": s["entry"], "rsi": None, "macd": None, "macd_signal": None,
        "volume_ratio": None, "ema9": None, "ema21": None, "atr": None, "atr_avg20": None, "adx": None,
        "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Markt-script (ongetest)",
        "reason": reason, "stop_loss": s["stop_loss"], "take_profit": s["take_profit"], "context_note": None,
        "is_practice": 0, "plain_explanation": None, "suggested_entry_low": None, "suggested_entry_high": None,
        "sniper_entry_price": None, "sniper_reason": None,
    })
    repo.set_scenario_state(s["id"], "fired", signal_id)
    await fanout_confirmed_signal(
        signal_id, coin, direction, s["entry"], s["stop_loss"], s["take_profit"], s["trigger_level"],
        title=push_notify.alert_title(coin, direction, "Script (ongetest)"),
        make_body=lambda *_: format_body(s), reason=reason, signal_type="script",
    )


async def run_triggers(now: Optional[datetime] = None) -> int:
    """Draait in de SMC-snelcyclus. Geeft het aantal scenario's dat afging."""
    from app import exchange
    now = now or datetime.now(timezone.utc)
    repo.expire_scenarios(now.isoformat())
    if not config.SCRIPT_ENABLED or should_disable(repo.list_script_results(config.SCRIPT_MAX_NEGATIVE), config.SCRIPT_MAX_NEGATIVE):
        return 0
    waiting = repo.list_waiting_scenarios()
    fired = 0
    for coin in sorted({s["coin"] for s in waiting}):
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="5m", limit=30)
        except Exception:
            logger.exception("5m-candles voor %s niet op te halen, scenario's blijven wachten", coin)
            continue
        closed = df.iloc[:-1]
        if closed.empty:
            continue
        last = float(closed["close"].iloc[-1])
        for s in (x for x in waiting if x["coin"] == coin):
            if not check_trigger(s["trigger_type"], s["direction"], s["trigger_level"], closed):
                continue
            today = (now - timedelta(hours=24)).isoformat()
            if not still_actionable(s["direction"], s["stop_loss"], s["take_profit"], last) or \
                    repo.count_script_alerts_since(today) >= config.SCRIPT_MAX_ALERTS_PER_DAY:
                repo.set_scenario_state(s["id"], "missed")
                continue
            try:
                await _fire(s)
                fired += 1
            except Exception:
                logger.exception("Scenario %s voor %s is niet gemeld", s["id"], coin)
    return fired


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    generate_all()
