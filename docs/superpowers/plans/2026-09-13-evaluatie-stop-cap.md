# Evaluatie: stop loss inperken op basis van evaluatiegrootte — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zodra een gebruiker een actieve, niet-geblokkeerde evaluatie
heeft, wordt de stop loss voor ZIJN eigen trade ingeperkt naarmate het
evaluatiesaldo kleiner is, zonder het gedeelde signaal voor andere
gebruikers te veranderen.

**Architecture:** Twee nieuwe pure functies in `app/risk.py` berekenen de
maximale stop-afstand voor een evaluatiegrootte en passen die toe op een
al berekende stop/target. `app/signal_processor.py`'s bestaande
`_resolve_signal_risk` (uit het vorige deelproject) wordt uitgebreid om
deze inperking toe te passen en de effectieve stop/target terug te geven;
de aanroepende fanout-loops zetten die als `stop_loss_override`/
`take_profit_override` op de per-gebruiker `journal_entries`-rij, via de
al bestaande `repo.update_journal_levels`. Het gedeelde signaal zelf
verandert niet.

**Tech Stack:** Python, FastAPI, SQLite. Geen nieuwe dependencies, geen
schema-wijziging (de override-kolommen bestaan al).

**Spec:** `docs/superpowers/specs/2026-09-13-evaluatie-stop-cap-design.md`

## Global Constraints

- Zonder actieve, niet-geblokkeerde evaluatie: exact het bestaande gedrag,
  geen enkele wijziging.
- Het GEDEELDE signaal (`signals`-tabel, wat elke gebruiker op het
  dashboard ziet) verandert nooit. Alleen de per-gebruiker
  `journal_entries`-rij krijgt een override.
- Exacte constanten: `STOP_CAP_REFERENCE_TIER = 10_000.0`,
  `STOP_CAP_MIN_PCT = 0.01`, `STOP_CAP_MAX_PCT = 0.10`.
- De sizing-formule uit het vorige deelproject (`compute_eval_risk_eur`,
  dagbudget/drawdown-aandelen, hefboomcap, `eval_sizing_blocked`) blijft
  ongewijzigd; deze taak levert er alleen een (mogelijk al ingeperkte)
  stop_loss aan.

---

### Task 1: risk.py — inperkingsformule en toepassing

**Files:**
- Modify: `app/risk.py`
- Test: scratch script

**Interfaces:**
- Produces: `STOP_CAP_REFERENCE_TIER`, `STOP_CAP_MIN_PCT`,
  `STOP_CAP_MAX_PCT`, `eval_max_stop_pct(tier_amount: float) -> float`,
  `apply_eval_stop_cap(direction: str, entry_price: float, stop_loss: float, take_profit: float, max_stop_pct: float) -> StopTake`.

- [ ] **Step 1: Nieuwe constanten en functies**

Voeg toe in `app/risk.py`, na de bestaande `MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION`-
constante en vóór `compute_risk_eur` (of een andere logische plek na de
bestaande stop/take-functies — de exacte positie maakt niet uit zolang het
vóór het eerste gebruik staat):

```python
# Bij dit evaluatiesaldo (of hoger) wordt de stop loss niet meer ingeperkt:
# het maximum groeit dan naar STOP_CAP_MAX_PCT, wat in de praktijk geen
# enkele normale marktstructuur-stop meer raakt (die liggen vrijwel altijd
# onder de 5%).
STOP_CAP_REFERENCE_TIER = 10_000.0
# Bij een evaluatiesaldo van (bijna) nul mag de stop nog maar dit percentage
# van de entry-prijs zijn.
STOP_CAP_MIN_PCT = 0.01
# Vanaf STOP_CAP_REFERENCE_TIER: dit percentage, functioneel "geen grens".
STOP_CAP_MAX_PCT = 0.10


def eval_max_stop_pct(tier_amount: float) -> float:
    """Maximale stop-afstand als fractie van de entry-prijs, lineair
    oplopend van STOP_CAP_MIN_PCT (bij tier_amount 0) tot STOP_CAP_MAX_PCT
    (bij STOP_CAP_REFERENCE_TIER en hoger). Geen harde knip: een evaluatie
    net onder de referentie-tier krijgt bijna dezelfde ruimte als er net
    boven, in plaats van een plotselinge sprong."""
    fraction = min(max(tier_amount, 0.0) / STOP_CAP_REFERENCE_TIER, 1.0)
    return STOP_CAP_MIN_PCT + (STOP_CAP_MAX_PCT - STOP_CAP_MIN_PCT) * fraction


def apply_eval_stop_cap(
    direction: str, entry_price: float, stop_loss: float, take_profit: float, max_stop_pct: float,
) -> StopTake:
    """Trekt een te brede stop loss in tot max_stop_pct van de entry-prijs.
    Take profit schaalt evenredig mee, zodat de risk:reward-verhouding van
    de oorspronkelijke berekening exact behouden blijft (in plaats van een
    aparte doelberekening te herhalen, die bij een niveau-gebaseerd target
    andere aannames zou maken dan de oorspronkelijke keuze). Geen wijziging
    als de bestaande stop al binnen de grens valt — dit is een bovengrens,
    geen streefwaarde."""
    direction = direction.lower()
    max_distance = entry_price * max_stop_pct
    if direction == "long":
        current_distance = entry_price - stop_loss
        if current_distance <= max_distance or current_distance <= 0:
            return StopTake(stop_loss=stop_loss, take_profit=take_profit)
        scale = max_distance / current_distance
        reward_distance = take_profit - entry_price
        return StopTake(
            stop_loss=entry_price - max_distance,
            take_profit=entry_price + reward_distance * scale,
        )
    elif direction == "short":
        current_distance = stop_loss - entry_price
        if current_distance <= max_distance or current_distance <= 0:
            return StopTake(stop_loss=stop_loss, take_profit=take_profit)
        scale = max_distance / current_distance
        reward_distance = entry_price - take_profit
        return StopTake(
            stop_loss=entry_price + max_distance,
            take_profit=entry_price - reward_distance * scale,
        )
    else:
        raise ValueError(f"onbekende richting: {direction}")
```

- [ ] **Step 2: Test met concrete cijfers**

```python
# scratchpad/test_stopcap_task1_risk.py
import sys
sys.path.insert(0, "/home/user/Trade")
from app import risk

# eval_max_stop_pct: 0 -> 1%, 5000 -> halverwege (5,5%), 10000 en hoger -> 10%.
assert abs(risk.eval_max_stop_pct(0.0) - 0.01) < 1e-9
assert abs(risk.eval_max_stop_pct(5_000.0) - 0.055) < 1e-9
assert abs(risk.eval_max_stop_pct(10_000.0) - 0.10) < 1e-9
assert abs(risk.eval_max_stop_pct(50_000.0) - 0.10) < 1e-9  # geplafonneerd, niet verder

# apply_eval_stop_cap, long: entry 100, stop 90 (10% afstand), max 1%.
# max_distance = 1.0. Nieuwe stop = 99.0. scale = 1/10 = 0.1.
# Oorspronkelijke reward_distance (take_profit 120, dus 20) wordt 20*0.1=2 -> take_profit 102.
result = risk.apply_eval_stop_cap("long", 100.0, 90.0, 120.0, 0.01)
assert abs(result.stop_loss - 99.0) < 1e-9, result.stop_loss
assert abs(result.take_profit - 102.0) < 1e-9, result.take_profit

# Short-variant, symmetrisch.
result_short = risk.apply_eval_stop_cap("short", 100.0, 110.0, 80.0, 0.01)
assert abs(result_short.stop_loss - 101.0) < 1e-9, result_short.stop_loss
assert abs(result_short.take_profit - 98.0) < 1e-9, result_short.take_profit

# Stop al binnen de grens: geen wijziging (long, stop 99.5 -> 0,5% afstand, max 1%).
unchanged = risk.apply_eval_stop_cap("long", 100.0, 99.5, 103.0, 0.01)
assert unchanged.stop_loss == 99.5 and unchanged.take_profit == 103.0

print("Task 1: OK")
```

Run: `python3 scratchpad/test_stopcap_task1_risk.py`
Expected: `Task 1: OK`.

- [ ] **Step 3: Commit**

```bash
git add app/risk.py
git commit -m "risk.py: stop loss inperken op basis van evaluatiegrootte"
```

---

### Task 2: signal_processor.py — dagtrading-fanout: stop inperken per gebruiker

**Files:**
- Modify: `app/signal_processor.py` (`_resolve_signal_risk`, rond regel 388-405; dagtrading-fanout, rond regel 786-861)
- Test: scratch integratietest

**Interfaces:**
- Consumes: `risk.eval_max_stop_pct`, `risk.apply_eval_stop_cap` uit Task 1.
- Produces: `_resolve_signal_risk(user, direction, entry_price, stop_loss, take_profit) -> tuple[float, Optional[int], float, float, float]`
  (SIGNATUUR EN RETURNVORM VERANDERT: 2 nieuwe parameters — `direction`,
  `take_profit` — en 2 nieuwe returnwaarden — `effective_stop_loss`,
  `effective_take_profit` — bovenop de bestaande `risk_eur, evaluation_id,
  cost_rate`). Task 3 (swing-fanout) gebruikt dezelfde nieuwe signatuur.

- [ ] **Step 1: _resolve_signal_risk uitbreiden**

```python
old = '''def _resolve_signal_risk(
    user: dict, entry_price: float, stop_loss: float,
) -> tuple[float, Optional[int], Optional[float]]:
    """Risicobedrag, evaluation_id (of None) en cost_rate (voor
    compute_position_size) voor één signaal aan één gebruiker. Gebruikt de
    actieve evaluatie als sizing-basis zodra die er is en er nog voldoende
    budget is; valt anders terug op het bestaande portfolio_eur x
    risk_percent-gedrag, exact ongewijzigd."""
    active_eval = repo.get_active_evaluation(user["id"])
    if active_eval:
        open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
        if not risk.eval_sizing_blocked(active_eval, open_risk_eur):
            risk_eur = risk.compute_eval_risk_eur(
                active_eval, user["risk_percent"], open_risk_eur, entry_price, stop_loss,
            )
            cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
            return risk_eur, active_eval["id"], cost_rate
    return risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"]), None, 0.0'''
new = '''def _resolve_signal_risk(
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
    return risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"]), None, 0.0, stop_loss, take_profit'''
```

- [ ] **Step 2: Dagtrading-fanout gebruikt de effectieve stop/target**

```python
old = '''        risk_eur, evaluation_id, cost_rate = _resolve_signal_risk(user, ind.price, stop_take.stop_loss)
        position_size = (
            risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)
            if confirmed else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )'''
new = '''        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, interp.direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
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
            repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, position_size)'''
```

- [ ] **Step 3: Telegram-bericht toont de eigen stop, niet de gedeelde**

```python
old = '''            await telegram_notify.send_signal(
                {
                    **signal_data, "risk_eur": risk_eur, "position_size": position_size,
                    "open_risk_pct": open_risk_pct, "pending_count": pending_count,
                    "eval_budget_pct": eval_budget_pct, "eval_blocked_note": eval_blocked_note,
                },
                chat_id=user["telegram_chat_id"], force_silent=force_silent, entry_id=entry_id,
            )'''
new = '''            stop_was_capped = effective_stop_loss != stop_take.stop_loss
            await telegram_notify.send_signal(
                {
                    **signal_data, "risk_eur": risk_eur, "position_size": position_size,
                    "open_risk_pct": open_risk_pct, "pending_count": pending_count,
                    "eval_budget_pct": eval_budget_pct, "eval_blocked_note": eval_blocked_note,
                    "stop_loss": effective_stop_loss, "take_profit": effective_take_profit,
                    "stop_capped_pct": (max_pct_for_display * 100) if stop_was_capped else None,
                },
                chat_id=user["telegram_chat_id"], force_silent=force_silent, entry_id=entry_id,
            )'''
```

Let op: `max_pct_for_display` bestaat nog niet — voeg 'm toe in Step 2's
blok (direct na de `_resolve_signal_risk`-aanroep), zodat de fanout-loop
'm bij de hand heeft voor het Telegram-bericht zonder de evaluatie-check
een derde keer te herhalen:

```python
old = '''        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, interp.direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
        )
        position_size = ('''
new = '''        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, interp.direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
        )
        max_pct_for_display = (
            risk.eval_max_stop_pct(active_eval_for_display["tier_amount"])
            if active_eval_for_display and evaluation_id is not None else None
        )
        position_size = ('''
```

Dit hergebruikt `active_eval_for_display`, die pas verderop in de bestaande
code wordt opgehaald (de `eval_budget_pct`/`eval_blocked_note`-berekening,
rond regel 808-820) — die aanroep naar `repo.get_active_evaluation` moet
dus VÓÓR deze nieuwe regel komen te staan in plaats van erna. Lees de
huidige volgorde van het bestand na en verplaats
`active_eval_for_display = repo.get_active_evaluation(user["id"])` naar
vlak vóór de `_resolve_signal_risk`-aanroep als dat nog niet zo is; de rest
van het bestaande blok (de if/elif voor `eval_budget_pct`/
`eval_blocked_note`) blijft verder ongewijzigd en gebruikt gewoon dezelfde,
al opgehaalde `active_eval_for_display`.

- [ ] **Step 4: Test — stop wordt ingeperkt voor een kleine evaluatie**

```python
# scratchpad/test_stopcap_task2_integration.py
import os
os.environ["DATABASE_PATH"] = "/tmp/stopcap_task2.db"
os.environ.setdefault("ENABLE_ADVANCED_FACTORS", "false")
if os.path.exists("/tmp/stopcap_task2.db"):
    os.remove("/tmp/stopcap_task2.db")

import asyncio
from unittest.mock import patch
import numpy as np
import pandas as pd
from app import db, repo, signal_processor
from app.anthropic_interpret import Interpretation

db.init_db()
user_id = repo.create_user("stopcap2", "wachtwoord123", 5000.0, 2.0, "123456")
# Kleine evaluatie: tier 1000, ver onder de referentie van 10.000, dus een
# stop-cap van rond de 1,9% (0,01 + 0,09 * 1000/10000 = 0,019).
eval_id = repo.create_evaluation(user_id, tier_amount=1_000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)

n = 60
closes = np.linspace(90, 110, n)
df = pd.DataFrame({
    "open": closes, "high": closes + 1, "low": closes - 1, "close": closes,
    "volume": [1000.0] * n,
}, index=pd.date_range("2026-01-01", periods=n, freq="4h"))

with patch("app.exchange.market_exists", return_value=True), \
     patch("app.exchange.to_symbol", return_value="BTC/EUR"), \
     patch("app.exchange.fetch_ohlcv", return_value=df):
    interp = Interpretation(
        coin="BTC", direction="long", category="day_trading", unclear=False,
        reason="", source_levels=[],
    )
    message_id = repo.insert_message("test signaal", [])
    asyncio.run(signal_processor._process_one_coin(message_id, "test signaal", interp))

entries = repo.list_journal(user_id)
assert len(entries) == 1, entries
entry = entries[0]
signal_stop_loss = entry["stop_loss_default"]
effective_stop_loss = entry["stop_loss"]  # COALESCE(override, signaal) via _JOURNAL_SELECT

if signal_stop_loss is not None and entry["price"]:
    distance_pct = abs(entry["price"] - signal_stop_loss) / entry["price"]
    max_expected_pct = 0.01 + 0.09 * (1_000.0 / 10_000.0)
    if distance_pct > max_expected_pct:
        assert abs(entry["price"] - effective_stop_loss) / entry["price"] <= max_expected_pct + 1e-6, (
            f"stop niet ingeperkt: {distance_pct=} > {max_expected_pct=}, effective={effective_stop_loss}"
        )
        assert effective_stop_loss != signal_stop_loss, "override had gezet moeten zijn"
        print(f"Task 2: OK (stop ingeperkt van {signal_stop_loss} naar {effective_stop_loss})")
    else:
        # De synthetische candles gaven toevallig al een krappe stop, geen
        # inperking nodig — geen falen, maar wel loggen zodat dit opvalt.
        assert effective_stop_loss == signal_stop_loss
        print("Task 2: OK (stop was al binnen de grens, geen override gezet — pas de synthetische data aan voor een dwingender scenario indien gewenst)")
else:
    raise AssertionError("kon signaal-stop niet ophalen, controleer entry['stop_loss_default']")
```

Run: `DATABASE_PATH=/tmp/stopcap_task2.db python3 scratchpad/test_stopcap_task2_integration.py`
Expected: `Task 2: OK (...)`.

- [ ] **Step 5: Commit**

```bash
git add app/signal_processor.py
git commit -m "signal_processor.py: stop loss inperken voor dagtrading-signalen bij kleine evaluatie"
```

---

### Task 3: signal_processor.py — swing-fanout: zelfde inperking

**Files:**
- Modify: `app/signal_processor.py` (swing-fanout, rond regel 475-495)

**Interfaces:**
- Consumes: de uitgebreide `_resolve_signal_risk`-signatuur uit Task 2.

- [ ] **Step 1: Swing-fanout gebruikt de effectieve stop/target**

```python
old = '''    for user in repo.list_users():
        risk_eur, evaluation_id, cost_rate = _resolve_signal_risk(user, ind_4h.price, stop_take.stop_loss)
        position_size = risk.compute_position_size(risk_eur, ind_4h.price, stop_take.stop_loss, cost_rate=cost_rate)
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        if not user["telegram_chat_id"]:
            continue
        # Geen is_coin_muted-check hier: mute geldt bewust alleen voor
        # day-trading meldingen (zie de spec), een swing-melding is
        # zeldzaam en juist bedoeld om een grote kans nooit te missen.
        quiet = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_swing_signal(
                coin=coin, direction=direction, price=ind_4h.price,
                stop_loss=stop_take.stop_loss, take_profit=stop_take.take_profit,
                daily_factors=daily_factors, factors_4h=factors_4h,
                level_price=watch["price_level"], pattern_name=watch["pattern_name"],
                chat_id=user["telegram_chat_id"], entry_id=entry_id, force_silent=quiet,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Swing-melding voor %s naar gebruiker %s is mislukt", coin, user["username"])'''
new = '''    for user in repo.list_users():
        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, direction, ind_4h.price, stop_take.stop_loss, stop_take.take_profit,
        )
        position_size = risk.compute_position_size(risk_eur, ind_4h.price, effective_stop_loss, cost_rate=cost_rate)
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        if effective_stop_loss != stop_take.stop_loss:
            repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, position_size)
        if not user["telegram_chat_id"]:
            continue
        # Geen is_coin_muted-check hier: mute geldt bewust alleen voor
        # day-trading meldingen (zie de spec), een swing-melding is
        # zeldzaam en juist bedoeld om een grote kans nooit te missen.
        quiet = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_swing_signal(
                coin=coin, direction=direction, price=ind_4h.price,
                stop_loss=effective_stop_loss, take_profit=effective_take_profit,
                daily_factors=daily_factors, factors_4h=factors_4h,
                level_price=watch["price_level"], pattern_name=watch["pattern_name"],
                chat_id=user["telegram_chat_id"], entry_id=entry_id, force_silent=quiet,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Swing-melding voor %s naar gebruiker %s is mislukt", coin, user["username"])'''
```

- [ ] **Step 2: Test**

```python
# scratchpad/test_stopcap_task3_swing.py
import os
os.environ["DATABASE_PATH"] = "/tmp/stopcap_task3.db"
os.environ.setdefault("ENABLE_ADVANCED_FACTORS", "false")
if os.path.exists("/tmp/stopcap_task3.db"):
    os.remove("/tmp/stopcap_task3.db")

import asyncio
from unittest.mock import patch
import numpy as np
import pandas as pd
from app import db, repo, signal_processor

db.init_db()
user_id = repo.create_user("stopcap3", "wachtwoord123", 5000.0, 2.0, "123456")
# Kleine evaluatie: tier 1000, cap ongeveer 1,9% (0,01 + 0,09 * 1000/10000).
eval_id = repo.create_evaluation(user_id, tier_amount=1_000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)

message_id = repo.insert_message("test swing bericht", [])
# Bewust ver van de huidige prijs (rond 100, zie de synthetische candles
# hieronder): een niveau op 70 voor een long geeft via
# compute_stop_take_from_levels een stop-kandidaat op dat niveau, ruim
# breder dan de ~1,9%-grens van deze kleine evaluatie.
source_level_id = repo.insert_source_level(message_id, "BTC", 70.0, None)
watch_id = repo.create_swing_watch(message_id, source_level_id, "BTC", "long")

n = 60
closes_4h = np.linspace(95, 105, n)
df_4h = pd.DataFrame({
    "open": closes_4h, "high": closes_4h + 1, "low": closes_4h - 1, "close": closes_4h,
    "volume": [1000.0] * n,
}, index=pd.date_range("2026-01-01", periods=n, freq="4h"))
closes_1d = np.linspace(90, 105, n)
df_1d = pd.DataFrame({
    "open": closes_1d, "high": closes_1d + 1, "low": closes_1d - 1, "close": closes_1d,
    "volume": [1000.0] * n,
}, index=pd.date_range("2025-11-01", periods=n, freq="1D"))

def fake_fetch_ohlcv(coin, timeframe="4h"):
    return df_1d if timeframe == "1d" else df_4h

with patch("app.exchange.market_exists", return_value=True), \
     patch("app.exchange.to_symbol", return_value="BTC/EUR"), \
     patch("app.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv):
    asyncio.run(signal_processor.run_swing_check(watch_id))

entries = repo.list_journal(user_id)
assert len(entries) == 1, entries
entry = entries[0]
signal_stop_loss = entry["stop_loss_default"]
effective_stop_loss = entry["stop_loss"]

assert signal_stop_loss is not None
distance_pct = abs(entry["price"] - signal_stop_loss) / entry["price"]
max_expected_pct = 0.01 + 0.09 * (1_000.0 / 10_000.0)
assert distance_pct > max_expected_pct, (
    f"testopzet klopt niet: signaal-stop ({distance_pct:.4f}) is al krapper dan de grens "
    f"({max_expected_pct:.4f}) — pas het niveau (nu 70.0) verder van de prijs af"
)
assert abs(entry["price"] - effective_stop_loss) / entry["price"] <= max_expected_pct + 1e-6, (
    f"stop niet ingeperkt: effective={effective_stop_loss}, price={entry['price']}"
)
assert effective_stop_loss != signal_stop_loss

print(f"Task 3: OK (swing-stop ingeperkt van {signal_stop_loss} naar {effective_stop_loss})")
```

Run: `DATABASE_PATH=/tmp/stopcap_task3.db python3 scratchpad/test_stopcap_task3_swing.py`
Expected: `Task 3: OK (...)`. Als `compute_stop_take_from_levels` het niveau op
70.0 niet als stop-kandidaat kiest (bijvoorbeeld omdat de swing-low uit de
synthetische 4h-candles dichterbij ligt en voorrang krijgt), pas het
niveau of de synthetische candle-reeks aan tot het scenario de bedoelde
"stop breder dan de grens"-situatie ook echt oplevert — de eerste assert
op `distance_pct > max_expected_pct` vangt dit af met een duidelijke
foutmelding in plaats van een stille, niet-representatieve pass.

- [ ] **Step 3: Commit**

```bash
git add app/signal_processor.py
git commit -m "signal_processor.py: stop loss inperken ook voor swing-signalen bij kleine evaluatie"
```

---

### Task 4: telegram_notify.py — zichtbaarheid van de inperking

**Files:**
- Modify: `app/telegram_notify.py` (`format_signal_message`, en een nieuwe helper naast `_eval_budget_line`)

**Interfaces:**
- Consumes: `signal["stop_capped_pct"]` (uit Task 2, `None` als niet
  ingeperkt).

- [ ] **Step 1: Nieuwe regel-helper**

```python
old = '''def _eval_blocked_line(note: str) -> str:
    return f"⛔ {note}"'''
new = '''def _eval_blocked_line(note: str) -> str:
    return f"⛔ {note}"


def _stop_capped_line(pct: float) -> str:
    return f"📏 Stop verkrapt naar max {pct:.1f}% van de prijs vanwege de grootte van je evaluatie."'''
```

(Zoek de exacte plek van `_eval_blocked_line` in het bestand — dit voegt
de nieuwe functie er direct na toe, pas de `old`/`new`-context aan als de
functie-inhoud niet exact zo in het huidige bestand staat.)

- [ ] **Step 2: format_signal_message toont de nieuwe regel**

```python
old = '''    if signal.get("eval_blocked_note"):
        lines += ["", _eval_blocked_line(signal["eval_blocked_note"])]'''
new = '''    if signal.get("eval_blocked_note"):
        lines += ["", _eval_blocked_line(signal["eval_blocked_note"])]
    if signal.get("stop_capped_pct") is not None:
        lines += ["", _stop_capped_line(signal["stop_capped_pct"])]'''
```

- [ ] **Step 3: Test**

```python
# scratchpad/test_stopcap_task4_telegram.py
import sys
sys.path.insert(0, "/home/user/Trade")
from app import telegram_notify

signal = {
    "direction": "long", "coin": "BTC", "confidence": "hoog vertrouwen",
    "price": 100.0, "take_profit": 102.0, "stop_loss": 99.0,
    "reason": "✓ Trend: ok | ✓ Momentum: ok", "risk_eur": 20.0,
    "stop_capped_pct": 1.9,
}
message = telegram_notify.format_signal_message(signal)
assert "verkrapt" in message.lower() and "1.9%" in message, message

signal_no_cap = {**signal, "stop_capped_pct": None}
message_no_cap = telegram_notify.format_signal_message(signal_no_cap)
assert "verkrapt" not in message_no_cap.lower()

print("Task 4: OK")
```

Run: `python3 scratchpad/test_stopcap_task4_telegram.py`
Expected: `Task 4: OK`.

- [ ] **Step 4: Commit**

```bash
git add app/telegram_notify.py
git commit -m "telegram_notify.py: tonen wanneer de stop loss is ingeperkt vanwege de evaluatiegrootte"
```

---

### Task 5: web/main.py — oefentrades krijgen dezelfde inperking

**Files:**
- Modify: `web/main.py` (`_resolve_practice_risk_eur`, beide oefentrade-routes)

**Interfaces:**
- Consumes: `risk.eval_max_stop_pct`, `risk.apply_eval_stop_cap` uit Task 1.
- Produces: `_resolve_practice_risk_eur`'s returnvorm groeit van 6 naar 8
  waarden: bestaande `(risk_eur, note, capped, max_risk_eur, cost_rate,
  link_to_evaluation)` plus `effective_stop_loss, effective_take_profit`.

- [ ] **Step 1: _resolve_practice_risk_eur uitgebreid**

Lees eerst de HUIDIGE volledige functie in `web/main.py` (rond regel
1080-1131, hierboven al geciteerd in de spec) — de brief citeert 'm
letterlijk, maar controleer dat de actuele code overeenkomt vóór je de
`old`-blokken toepast.

```python
old = '''    max_risk_eur = risk.compute_eval_risk_eur(
        active_eval, user["risk_percent"], open_risk_eur, entry_price, stop_loss,
    )
    cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
    requested_risk_eur = manual_risk_eur if manual_risk_eur is not None else max_risk_eur
    capped = requested_risk_eur > max_risk_eur > 0
    computed_risk_eur = min(requested_risk_eur, max_risk_eur) if max_risk_eur > 0 else requested_risk_eur
    leverage_note = (
        f"Systeem: risico verlaagd van €{requested_risk_eur:.2f} naar €{computed_risk_eur:.2f} "
        f"om binnen de regels van je evaluatie te blijven."
    ) if capped else None
    return computed_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, True'''
new = '''    max_pct = risk.eval_max_stop_pct(active_eval["tier_amount"])
    capped_stop = risk.apply_eval_stop_cap(direction, entry_price, stop_loss, take_profit, max_pct)
    max_risk_eur = risk.compute_eval_risk_eur(
        active_eval, user["risk_percent"], open_risk_eur, entry_price, capped_stop.stop_loss,
    )
    cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
    requested_risk_eur = manual_risk_eur if manual_risk_eur is not None else max_risk_eur
    capped = requested_risk_eur > max_risk_eur > 0
    computed_risk_eur = min(requested_risk_eur, max_risk_eur) if max_risk_eur > 0 else requested_risk_eur
    leverage_note = (
        f"Systeem: risico verlaagd van €{requested_risk_eur:.2f} naar €{computed_risk_eur:.2f} "
        f"om binnen de regels van je evaluatie te blijven."
    ) if capped else None
    return (
        computed_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, True,
        capped_stop.stop_loss, capped_stop.take_profit,
    )'''
```

De functie-signatuur en de twee eerdere `return`-statements (de
"geen actieve evaluatie"-tak en de "geblokkeerd"-tak) moeten ook de nieuwe
2 waarden teruggeven — geef daar simpelweg de ONGEWIJZIGDE
`stop_loss, take_profit` (de parameters die de functie al binnenkrijgt)
als 7e/8e waarde terug, exact zoals `_resolve_signal_risk` dat in Task 2
doet voor zijn twee "geen inperking"-paden. Werk de docstring en de
type-hint (`tuple[float, Optional[str], bool, Optional[float], float,
bool, float, float]`) bij, en voeg `take_profit: float` toe als nieuwe
parameter aan de functie-signatuur zelf:

```python
old = '''def _resolve_practice_risk_eur(
    user: dict, active_eval: Optional[dict], manual_risk_eur: Optional[float],
    entry_price: float, stop_loss: float,
) -> tuple[float, Optional[str], bool, Optional[float], float, bool]:'''
new = '''def _resolve_practice_risk_eur(
    user: dict, active_eval: Optional[dict], manual_risk_eur: Optional[float],
    direction: str, entry_price: float, stop_loss: float, take_profit: float,
) -> tuple[float, Optional[str], bool, Optional[float], float, bool, float, float]:'''
```

En de twee vroege `return`-statements:

```python
old = '''    if not active_eval:
        computed_risk_eur = (
            manual_risk_eur if manual_risk_eur is not None
            else risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        )
        return computed_risk_eur, None, False, None, 0.0, False'''
new = '''    if not active_eval:
        computed_risk_eur = (
            manual_risk_eur if manual_risk_eur is not None
            else risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        )
        return computed_risk_eur, None, False, None, 0.0, False, stop_loss, take_profit'''
```

```python
old = '''        leverage_note = (
            "Systeem: dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, "
            "deze oefentrade telt niet mee voor je evaluatie."
        )
        return computed_risk_eur, leverage_note, False, None, 0.0, False'''
new = '''        leverage_note = (
            "Systeem: dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, "
            "deze oefentrade telt niet mee voor je evaluatie."
        )
        return computed_risk_eur, leverage_note, False, None, 0.0, False, stop_loss, take_profit'''
```

- [ ] **Step 2: Beide routes geven direction/take_profit mee en gebruiken de effectieve stop**

```python
old = '''    _df, ind, stop_take = await _fetch_practice_trade_calc(symbol, direction)
    active_eval = repo.get_active_evaluation(user["id"])
    used_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, _link_to_evaluation = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, ind.price, stop_take.stop_loss,
    )
    position_size = risk.compute_position_size(used_risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)
    notional_eur = (position_size * ind.price) if position_size else None

    return JSONResponse({
        "entry_price": ind.price,
        "stop_loss": stop_take.stop_loss,
        "take_profit": stop_take.take_profit,
        "requested_risk_eur": manual_risk_eur,
        "used_risk_eur": used_risk_eur,
        "position_size": position_size,
        "notional_eur": notional_eur,
        "capped": capped,
        "max_risk_eur": max_risk_eur,
        "note": leverage_note,
    })'''
new = '''    _df, ind, stop_take = await _fetch_practice_trade_calc(symbol, direction)
    active_eval = repo.get_active_evaluation(user["id"])
    (
        used_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, _link_to_evaluation,
        effective_stop_loss, effective_take_profit,
    ) = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
    )
    position_size = risk.compute_position_size(used_risk_eur, ind.price, effective_stop_loss, cost_rate=cost_rate)
    notional_eur = (position_size * ind.price) if position_size else None

    return JSONResponse({
        "entry_price": ind.price,
        "stop_loss": effective_stop_loss,
        "take_profit": effective_take_profit,
        "requested_risk_eur": manual_risk_eur,
        "used_risk_eur": used_risk_eur,
        "position_size": position_size,
        "notional_eur": notional_eur,
        "capped": capped,
        "max_risk_eur": max_risk_eur,
        "note": leverage_note,
    })'''
```

```python
old = '''    active_eval = repo.get_active_evaluation(user["id"])
    manual_risk_eur = _parse_optional_float(risk_eur)
    computed_risk_eur, leverage_note, _capped, _max_risk_eur, cost_rate, link_to_evaluation = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, ind.price, stop_take.stop_loss,
    )
    position_size = risk.compute_position_size(computed_risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)

    entry_id = repo.create_journal_entry(
        signal_id, user["id"], computed_risk_eur,
        evaluation_id=active_eval["id"] if link_to_evaluation else None, position_size=position_size,
    )
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)
    if leverage_note:
        repo.update_journal_note(entry_id, user["id"], leverage_note)'''
new = '''    active_eval = repo.get_active_evaluation(user["id"])
    manual_risk_eur = _parse_optional_float(risk_eur)
    (
        computed_risk_eur, leverage_note, _capped, _max_risk_eur, cost_rate, link_to_evaluation,
        effective_stop_loss, effective_take_profit,
    ) = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
    )
    position_size = risk.compute_position_size(computed_risk_eur, ind.price, effective_stop_loss, cost_rate=cost_rate)

    entry_id = repo.create_journal_entry(
        signal_id, user["id"], computed_risk_eur,
        evaluation_id=active_eval["id"] if link_to_evaluation else None, position_size=position_size,
    )
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)
    if effective_stop_loss != stop_take.stop_loss:
        repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, position_size)
    if leverage_note:
        repo.update_journal_note(entry_id, user["id"], leverage_note)'''
```

- [ ] **Step 3: Handmatige Playwright/TestClient-verificatie**

Zelfde aanpak als het vorige deelproject (Binance is netwerk-geblokkeerd in
deze sandbox): monkeypatch `app.exchange.fetch_ohlcv` en gebruik FastAPI's
`TestClient` tegen een scratch-database met een kleine evaluatie (bv. tier
€1.000). Maak een oefentrade aan met een richting waarvan de swing-stop
breder is dan de berekende grens, en controleer dat de aangemaakte
`journal_entries`-rij een `stop_loss_override` heeft die binnen de grens
valt.

- [ ] **Step 4: Commit**

```bash
git add web/main.py
git commit -m "web/main.py: oefentrades krijgen dezelfde stop-inperking als echte signalen"
```

---

### Task 6: Volledige regressie en push

**Files:** geen nieuwe wijzigingen, alleen verificatie.

- [ ] **Step 1: Alle scratch-tests van Taken 1-4 opnieuw draaien**

```bash
rm -f /tmp/stopcap_all.db
DATABASE_PATH=/tmp/stopcap_all.db python3 scratchpad/test_stopcap_task1_risk.py
DATABASE_PATH=/tmp/stopcap_all.db python3 scratchpad/test_stopcap_task2_integration.py
DATABASE_PATH=/tmp/stopcap_all.db python3 scratchpad/test_stopcap_task3_swing.py
python3 scratchpad/test_stopcap_task4_telegram.py
```

- [ ] **Step 2: Regressie op het vorige deelproject (evaluatie-volledige-regels)**

Draai de scratch-tests van dat plan opnieuw (als ze nog in `scratchpad/`
staan) om te bevestigen dat de uitbreiding van `_resolve_signal_risk`'s
signatuur niets van de sizing-formule zelf heeft veranderd — alleen de
stop_loss die eraan meegegeven wordt.

- [ ] **Step 3: Regressie zonder actieve evaluatie**

Herhaal het vorige deelproject se "zonder evaluatie geen wijziging"-check:
een gebruiker zonder actieve evaluatie moet na deze wijziging nog steeds
`entry["stop_loss"] == entry["stop_loss_default"]` hebben (geen override
gezet) en exact dezelfde `risk_eur`/`position_size` als vóór dit plan.

- [ ] **Step 4: Push**

```bash
git log --oneline -8
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```
