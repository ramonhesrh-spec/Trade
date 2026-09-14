# Live interactiviteit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Het dashboard bewegender en interactiever maken met zes secties die allemaal aan echte, live data gekoppeld zijn: koersticker, laatste-seintje-banner, SL/TP-voortgangsbalk, ademende risico-indicator, prijsrichting-pijltje, en een activiteit-boost op de bestaande hartslag.

**Architecture:** Vier van de zes secties hergebruiken bestaande mechanismen (`.ticker-*` CSS van de landingspagina, `triggerSignalWave()`, `.risk-gauge-fill`, de bestaande flash-logica) in plaats van iets nieuws te bouwen. Twee nieuwe stukjes state komen bovenop de al bestaande poll-cycli (`/api/open_positions` elke 20s, `/api/system_status` elke poll-tick), geen nieuwe polling-lus.

**Tech Stack:** FastAPI/Jinja2 (server), vanilla JS (dashboard.js/base.html), CSS (style.css). Geen nieuwe dependency.

**Spec:** docs/superpowers/specs/2026-09-14-live-interactiviteit-design.md

## Global Constraints

- Elke nieuwe of uitgebreide animatie respecteert `prefers-reduced-motion` (bestaande conventie, zie style.css se bestaande `@media (prefers-reduced-motion: reduce)`-blokken).
- Geen enkele beweging op een verzonnen waarde: elke sectie is aan een echte, actuele waarde gekoppeld (CLAUDE.md).
- De koersticker (Sectie 1 van de spec) verschijnt ALLEEN op de `/dashboard`-route, nergens anders (bevestigd met de product owner) — geen nieuwe polling-lus op andere pagina's.
- De SL/TP-progress-formule mag maar op ÉÉN plek staan (`app/risk.py`); `telegram_notify._progress_bar` en de web-render gebruiken allebei diezelfde functie, nooit een eigen kopie.
- Zonder open trades toont de topbar geen ticker-element (server-side leeg, geen placeholder-cijfers).

---

### Task 1: risk.py — gedeelde SL/TP-progress-functie + telegram_notify hergebruikt hem

**Files:**
- Modify: `app/risk.py` (nieuwe functie toevoegen, aan het eind van het bestand)
- Modify: `app/telegram_notify.py:47-64` (`_progress_bar` gebruikt de nieuwe functie i.p.v. zijn eigen berekening)
- Test: scratch-DB script (geen pytest-suite in dit project, zie CLAUDE.md)

**Interfaces:**
- Produces: `risk.compute_sltp_progress_pct(direction: str, price: float, stop_loss: float, take_profit: float) -> float` — percentage (0.0-100.0) van waar `price` zit tussen `stop_loss` (0%) en `take_profit` (100%), geclampt.

- [ ] **Step 1: Nieuwe functie in app/risk.py**

Voeg toe aan het eind van `app/risk.py`:

```python
def compute_sltp_progress_pct(direction: str, price: float, stop_loss: float, take_profit: float) -> float:
    """Percentage (0-100) van waar de prijs nu zit tussen stop loss (0%) en
    take profit (100%). Gedeeld tussen de Telegram-tekstbalk
    (telegram_notify._progress_bar) en de live voortgangsbalk op het
    dashboard, zodat beide altijd exact hetzelfde percentage tonen. Bij
    risk.py se standaard 1:2 risk:reward-ontwerp staat een gloednieuwe
    kans al op ongeveer 33%, dat is geen fout, dat is de ingebouwde
    verhouding tussen de stop-afstand en de doelafstand."""
    if direction == "long":
        span = take_profit - stop_loss
        pos = (price - stop_loss) / span if span else 0.0
    else:
        span = stop_loss - take_profit
        pos = (stop_loss - price) / span if span else 0.0
    return max(0.0, min(1.0, pos)) * 100
```

- [ ] **Step 2: telegram_notify._progress_bar hergebruikt de functie**

Huidige code (`app/telegram_notify.py:47-64`):

```python
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
```

Nieuwe code — vervang de hele functie door:

```python
def _progress_bar(price: float, stop_loss: float, take_profit: float, direction: str) -> str:
    """Blokjesbalk die toont waar de huidige prijs zit tussen stop loss (0%)
    en take profit (100%). Percentage komt uit risk.compute_sltp_progress_pct
    (gedeeld met de live voortgangsbalk op het dashboard), hier alleen naar
    blokjes vertaald."""
    pct = risk.compute_sltp_progress_pct(direction, price, stop_loss, take_profit)
    filled = round(pct / 100 * PROGRESS_BAR_WIDTH)
    bar = "▓" * filled + "░" * (PROGRESS_BAR_WIDTH - filled)
    return f"{bar} {pct:.0f}% naar TP"
```

Controleer of `app/telegram_notify.py` `risk` al importeert (`from app import config, exchange, repo` rond regel 11) — zo niet, voeg `risk` toe aan die import-regel.

- [ ] **Step 3: Test**

Scratch-DB-vrij script (pure functie, geen database nodig):

```python
import sys
sys.path.insert(0, "/home/user/Trade")
from app import risk, telegram_notify

# Long, prijs precies op de stop -> 0%
assert risk.compute_sltp_progress_pct("long", 95.0, 95.0, 110.0) == 0.0
# Long, prijs precies op take profit -> 100%
assert risk.compute_sltp_progress_pct("long", 110.0, 95.0, 110.0) == 100.0
# Long, prijs halverwege -> 50%
assert abs(risk.compute_sltp_progress_pct("long", 102.5, 95.0, 110.0) - 50.0) < 1e-9
# Long, prijs voorbij TP -> geclampt op 100%
assert risk.compute_sltp_progress_pct("long", 200.0, 95.0, 110.0) == 100.0
# Long, prijs voorbij SL (verkeerde kant) -> geclampt op 0%
assert risk.compute_sltp_progress_pct("long", 50.0, 95.0, 110.0) == 0.0
# Short: spiegelbeeld
assert risk.compute_sltp_progress_pct("short", 105.0, 105.0, 90.0) == 0.0
assert risk.compute_sltp_progress_pct("short", 90.0, 105.0, 90.0) == 100.0

# telegram_notify._progress_bar geeft hetzelfde percentage terug als de bar-tekst
bar = telegram_notify._progress_bar(102.5, 95.0, 110.0, "long")
assert "50%" in bar, bar
print("OK: alle scenario's kloppen, _progress_bar gebruikt de gedeelde functie")
```

- [ ] **Step 4: Commit**

```bash
git add app/risk.py app/telegram_notify.py
git commit -m "risk.py: gedeelde SL/TP-progress-functie, telegram_notify hergebruikt hem"
```

---

### Task 2: web/main.py — server-context voor ticker, banner en risico-puls

**Files:**
- Modify: `web/main.py` (`dashboard`-route rond regel 602-660, `/api/system_status`-route rond regel 745-764)
- Test: scratch-DB script + TestClient

**Interfaces:**
- Consumes: `risk.compute_sltp_progress_pct` (Task 1)
- Produces: `dashboard`-route se template-context krijgt een nieuwe sleutel `ticker_coins` (`list[dict]`, elk `{"coin": str, "current_price": float | None}`, uniek per coin, alleen uit echte, open trades); elke entry in `taken_entries` krijgt een nieuw veld `sltp_progress_pct` (`float`, alleen als `stop_loss`/`take_profit` bekend zijn, anders `None`). `/api/system_status` krijgt twee nieuwe sleutels: `last_signal` (`{"id": int, "coin": str, "label": str, "received_at": str} | None`) en `risk_pct` (`float | None`, dagbudget/drawdown-gebruik voor een evaluatie-gebruiker, anders het bestaande portfolio-open-risicopercentage).

- [ ] **Step 1: ticker_coins + sltp_progress_pct in de dashboard-route**

Zoek in `web/main.py`'s `dashboard`-route de regel:

```python
    taken_entries = [e for e in open_entries if e["entry_price"] is not None]
    pending_entries = [e for e in open_entries if e["entry_price"] is None]
    _attach_discipline_facts(taken_entries)
```

Voeg er direct na toe:

```python
    for e in taken_entries:
        e["sltp_progress_pct"] = (
            risk.compute_sltp_progress_pct(e["direction"], e["current_price"], e["stop_loss"], e["take_profit"])
            if e["current_price"] is not None and e["stop_loss"] and e["take_profit"] else None
        )
    # Unieke coins uit echte, open trades voor de topbar-ticker (Sectie 1
    # van de spec) — alleen op het dashboard zelf, waar de 20s-polling van
    # dashboard.js toch al draait om deze prijzen te verversen.
    seen_ticker_coins: set[str] = set()
    ticker_coins = []
    for e in taken_entries:
        if e["coin"] not in seen_ticker_coins:
            seen_ticker_coins.add(e["coin"])
            ticker_coins.append({"coin": e["coin"], "current_price": e["current_price"]})
```

Zoek de `return templates.TemplateResponse(...)`-call van de `dashboard`-route (aan het eind van de functie) en voeg `"ticker_coins": ticker_coins,` toe aan de context-dict die daarin meegegeven wordt.

- [ ] **Step 2: last_signal + risk_pct in /api/system_status**

Huidige code (`web/main.py:745-764`):

```python
@app.get("/api/system_status")
async def api_system_status(user: dict = Depends(require_login)):
    """Levensteken van het systeem zelf, niet van de markt: is de exchange
    nu bereikbaar, en wanneer kwam het laatste Discord bericht binnen.
    Eén live check per opvraag, geen opgeslagen status die kan verouderen
    zonder dat iemand het merkt."""
    try:
        await asyncio.to_thread(exchange.fetch_last_price, "BTC")
        exchange_ok = True
    except Exception:
        exchange_ok = False
    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
        "week_result_eur": repo.week_result_eur(user["id"]),
        "volatility_ratio": repo.largest_open_position_volatility(user["id"]),
    }
```

Nieuwe code — vervang de hele functie door:

```python
@app.get("/api/system_status")
async def api_system_status(user: dict = Depends(require_login)):
    """Levensteken van het systeem zelf, niet van de markt: is de exchange
    nu bereikbaar, en wanneer kwam het laatste Discord bericht binnen.
    Eén live check per opvraag, geen opgeslagen status die kan verouderen
    zonder dat iemand het merkt."""
    try:
        await asyncio.to_thread(exchange.fetch_last_price, "BTC")
        exchange_ok = True
    except Exception:
        exchange_ok = False

    recent_signals = repo.list_recent_signals_for_user(user["id"], limit=1)
    last_signal = None
    if recent_signals:
        s = recent_signals[0]
        last_signal = {
            "id": s["id"], "coin": s["coin"],
            "label": f"{s['direction']} · {s['confidence']}",
            "received_at": s["created_at"],
        }

    active_eval = repo.get_active_evaluation(user["id"])
    if active_eval:
        open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
        daily_remaining = risk.compute_eval_daily_budget_remaining(active_eval, open_risk_eur)
        drawdown_remaining = risk.compute_eval_drawdown_budget_remaining(active_eval, open_risk_eur)
        daily_budget_total = active_eval["day_start_balance"] * active_eval["max_daily_loss_pct"] / 100
        drawdown_total = active_eval["tier_amount"] * active_eval["max_drawdown_pct"] / 100
        daily_used_pct = (1 - daily_remaining / daily_budget_total) * 100 if daily_budget_total else 0.0
        drawdown_used_pct = (1 - drawdown_remaining / drawdown_total) * 100 if drawdown_total else 0.0
        risk_pct = max(daily_used_pct, drawdown_used_pct)
    else:
        portfolio = user.get("portfolio_eur")
        open_risk = repo.total_open_risk_eur(user["id"])
        risk_pct = (open_risk / portfolio * 100) if portfolio else None

    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
        "week_result_eur": repo.week_result_eur(user["id"]),
        "volatility_ratio": repo.largest_open_position_volatility(user["id"]),
        "last_signal": last_signal,
        "risk_pct": risk_pct,
    }
```

`repo.list_recent_signals_for_user` bestaat nog niet: de bestaande `list_recent_signals(coin, limit)` in `app/repo.py` is PER-COIN (geen `user_id`-parameter, geen join met `journal_entries`), dus niet herbruikbaar hiervoor. Voeg een kleine nieuwe functie toe aan `app/repo.py`, in de buurt van de andere `_JOURNAL_SELECT`-gebruikende functies:

```python
def list_recent_signals_for_user(user_id: int, limit: int = 1) -> list[dict]:
    """Meest recente ECHTE signalen (geen oefentrade-events) die deze
    gebruiker een logboekregel opleverden, nieuwste eerst. Gebruikt voor
    het laatste-seintje-bannertje op het dashboard (/api/system_status)."""
    with db.session() as conn:
        rows = conn.execute(
            _JOURNAL_SELECT + """
            WHERE je.user_id = ? AND s.is_practice = 0
            ORDER BY s.created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
```

Let op: `daily_used_pct`/`drawdown_used_pct` kunnen negatief worden als `daily_remaining`/`drawdown_remaining` groter is dan de totale budgetten (kan gebeuren bij een positieve dag) — clamp beide op `max(0.0, ...)` vóór de `max()`-vergelijking, anders toont de risico-puls een negatief percentage.

- [ ] **Step 2b: risk_pct clampen**

Pas de twee regels uit Step 2 aan naar:

```python
        daily_used_pct = max(0.0, (1 - daily_remaining / daily_budget_total) * 100) if daily_budget_total else 0.0
        drawdown_used_pct = max(0.0, (1 - drawdown_remaining / drawdown_total) * 100) if drawdown_total else 0.0
```

- [ ] **Step 3: Test**

Scratch-DB script + `TestClient(app)` (zelfde patroon als eerdere taken vandaag):
1. User zonder open trades, geen evaluatie → `GET /` dashboard: `ticker_coins == []`. `GET /api/system_status`: `last_signal is None`, `risk_pct is None` (geen portfolio_eur) of `0.0`.
2. User met één open, echte trade (stop_loss/take_profit/current_price bekend) → `taken_entries[0]["sltp_progress_pct"]` is een getal tussen 0 en 100, komt overeen met `risk.compute_sltp_progress_pct` los uitgerekend. `ticker_coins == [{"coin": ..., "current_price": ...}]`.
3. User met een actieve evaluatie en een deel van het dagbudget al gebruikt → `risk_pct` komt overeen met een losse handmatige berekening met dezelfde formule, en is nooit negatief ook niet als er nog geen enkele trade gesloten is (dan is `daily_remaining == daily_budget_total`, dus 0%).
4. User met een net aangemaakt, ECHT signaal → `last_signal` bevat de coin/richting/tijd van dat signaal.

- [ ] **Step 4: Commit**

```bash
git add web/main.py app/repo.py
git commit -m "web/main.py: server-context voor ticker, laatste-seintje-banner en risico-puls"
```

---

### Task 3: base.html — ticker-markup, laatste-seintje-banner, risico-puls- en hartslag-boost-JS

**Files:**
- Modify: `web/templates/base.html` (topbar rond regel 269-300, refresh()-functie rond regel 732-745, `triggerSignalWave()` rond regel 721-730)
- Modify: `web/static/style.css` (nieuwe, kleine CSS-toevoegingen)
- Test: handmatige Playwright-verificatie (samen met Task 6)

**Interfaces:**
- Consumes: `ticker_coins`-contextvariabele en `last_signal`/`risk_pct`-velden uit `/api/system_status` (Task 2).
- Produces: DOM-elementen `#dashboard-ticker-track` (met `[data-ticker-coin]`-items), `#last-signal-banner`/`#last-signal-text`, CSS custom properties `--risk-pulse-duration` en (kortstondig) `--heartbeat-duration`.

- [ ] **Step 1: Ticker-markup in de topbar (alleen als er ticker_coins zijn)**

In `web/templates/base.html`, direct na de sluitende `</div>` van `topbar-top` (na regel 300-ish, zoek de exacte sluiting van dat blok) en vóór de sluitende `</header>`:

```html
{% if ticker_coins %}
<div class="ticker-strip topbar-ticker" aria-hidden="true">
  <div class="ticker-track" id="dashboard-ticker-track">
    {% for c in ticker_coins %}
    <span class="ticker-item" data-ticker-coin="{{ c.coin }}">{{ c.coin }} <span class="ticker-price">{{ "%.4f"|format(c.current_price) if c.current_price else "···" }}</span></span>
    {% endfor %}
    {% for c in ticker_coins %}
    <span class="ticker-item" data-ticker-coin="{{ c.coin }}" aria-hidden="true">{{ c.coin }} <span class="ticker-price">{{ "%.4f"|format(c.current_price) if c.current_price else "···" }}</span></span>
    {% endfor %}
  </div>
</div>
{% endif %}
```

De lijst staat er TWEE keer achter elkaar (zelfde patroon als `landing.html`'s ticker): de CSS-animatie schuift maar 50% op en herhaalt dan naadloos, zonder deze verdubbeling zou je een sprong zien. De JS in Task 5 update BEIDE voorkomens van elke coin (gebruik `document.querySelectorAll`, niet `querySelector`).

CSS: `.topbar-ticker` hergebruikt `.ticker-strip`/`.ticker-track`/`.ticker-item`/`.ticker-price` uit style.css ongewijzigd (regel 994-1008); voeg alleen toe:

```css
.topbar-ticker { margin: 0; border-top: 1px solid var(--border); }
```

- [ ] **Step 2: Laatste-seintje-banner-markup**

Direct na het `.topbar-ticker`-blok (of na `</header>` als er geen ticker is):

```html
<div class="last-signal-banner" id="last-signal-banner" aria-live="polite" {% if not last_signal_text %}hidden{% endif %}>
  <span id="last-signal-text">{{ last_signal_text or "" }}</span>
</div>
```

`last_signal_text` moet als contextvariabele vanuit de `dashboard`-route meegegeven worden (Task 2 leverde `last_signal` alleen via `/api/system_status`, niet server-side voor de EERSTE render — voeg in Task 2's Step 1 ook toe: haal `repo.list_recent_signals_for_user(user["id"], limit=1)` op en bouw dezelfde `"{{coin}} · {{richting}} · {{vertrouwen}}"`-tekst, geef 'm mee als `last_signal_text` in de template-context, zodat de banner bij de allereerste page-load al gevuld is in plaats van pas na de eerste `/api/system_status`-poll).

CSS:

```css
.last-signal-banner { padding: 6px 16px; font-size: 12.5px; color: var(--text-muted); text-align: center; transition: opacity 0.3s ease; }
```

- [ ] **Step 3: JS — ticker/banner bijwerken + hartslag-boost**

In `base.html`'s bestaande `refresh()`-functie (rond regel 732), na de bestaande `document.documentElement.style.setProperty("--brand-breathe-duration", ...)`-regel, voeg toe:

```js
document.documentElement.style.setProperty("--risk-pulse-duration", riskPulseDuration(s.risk_pct));
lastKnownMessageAt = s.last_message_at;

if (s.last_signal && s.last_signal.id !== lastSignalId) {
  var isFirstLoad = lastSignalId === null;
  lastSignalId = s.last_signal.id;
  if (!isFirstLoad) {
    var banner = document.getElementById("last-signal-text");
    var wrapper = document.getElementById("last-signal-banner");
    if (banner && wrapper) {
      wrapper.hidden = false;
      banner.style.opacity = 0;
      setTimeout(function () {
        banner.textContent = s.last_signal.coin + " · " + s.last_signal.label + " · " + timeAgo(s.last_signal.received_at);
        banner.style.opacity = 1;
      }, 300);
    }
    triggerSignalWave();
  }
}
```

Voeg vlak vóór de `refresh()`-functie twee nieuwe module-scope variabelen toe (naast de bestaande `var lastPendingCount = null;`):

```js
var lastSignalId = null;
var lastKnownMessageAt = null;

// Hoe dichter bij de evaluatie/portfolio-risicolimiet, hoe sneller de
// risicogauge se shimmer klopt: 2.4s bij 0%, 0.8s bij 100%. null/undefined
// (geen portfolio_eur ingesteld) valt terug op het neutrale basistempo.
function riskPulseDuration(pct) {
  if (pct === null || pct === undefined) return "2.4s";
  var duration = 2.4 - (Math.min(Math.max(pct, 0), 100) / 100) * 1.6;
  return duration.toFixed(2) + "s";
}
```

Werk `triggerSignalWave()` bij (huidige code rond regel 721-730):

```js
function triggerSignalWave() {
  var wave = document.getElementById("signal-wave");
  if (wave) {
    wave.classList.remove("is-active");
    void wave.offsetWidth;
    wave.classList.add("is-active");
  }
  // Kortstondige hartslag-boost op het exacte moment van een nieuw signaal,
  // in plaats van te wachten tot de eerstvolgende minuten-drempel van
  // heartbeatDuration. Na 3 seconden valt de eerstvolgende refresh()-cyclus
  // vanzelf terug op het tempo dat bij de werkelijke tijd-sinds-laatste-
  // bericht hoort, geen aparte "terug naar normaal"-logica nodig.
  document.documentElement.style.setProperty("--heartbeat-duration", "0.6s");
  setTimeout(function () {
    document.documentElement.style.setProperty("--heartbeat-duration", heartbeatDuration(lastKnownMessageAt));
  }, 3000);
}
```

- [ ] **Step 4: CSS voor de risico-puls-koppeling**

Zoek in `style.css` regel 582-591 (`.risk-gauge-fill::after`) en voeg toe:

```css
.risk-gauge-fill::after { animation-duration: var(--risk-pulse-duration, 2.4s); }
```

(Deze regel komt bovenop de bestaande `::after`-declaratie, niet die vervangen — zoek de exacte huidige `animation`-property in die regel en voeg `animation-duration` als losse override toe zodat de rest van de animatie-declaratie ongewijzigd blijft.)

- [ ] **Step 5: Commit**

```bash
git add web/templates/base.html web/static/style.css
git commit -m "base.html: koersticker, laatste-seintje-banner, risico-puls en hartslag-boost"
```

---

### Task 4: _macros.html + style.css — SL/TP-voortgangsbalk en prijsrichting-pijltje

**Files:**
- Modify: `web/templates/_macros.html` (`open_trade_body`-macro, regel 40+)
- Modify: `web/static/style.css` (nieuwe klassen)
- Test: handmatige Playwright-verificatie (samen met Task 6)

**Interfaces:**
- Consumes: `e.sltp_progress_pct` (Task 2), bestaande `e.id`/`e.stop_loss`/`e.take_profit`/`e.direction`/`e.current_price`.

- [ ] **Step 1: SL/TP-voortgangsbalk in open_trade_body**

Huidige code (`web/templates/_macros.html`, in `open_trade_body`, na de `data-grid`):

```html
<div class="data-grid">
  <div class="cell"><div class="k">Entry</div><div class="v">{{ "%.4f"|format(e.entry_price) }}</div></div>
  <div class="cell"><div class="k">Nu</div><div class="v" data-price="{{ e.id }}">{{ "%.4f"|format(e.current_price) if e.current_price else "-" }}</div></div>
  <div class="cell"><div class="k">SL</div><div class="v neg">{{ "%.4f"|format(e.stop_loss) if e.stop_loss else "-" }}</div></div>
  <div class="cell"><div class="k">TP</div><div class="v pos">{{ "%.4f"|format(e.take_profit) if e.take_profit else "-" }}</div></div>
  <div class="cell"><div class="k">Grootte</div><div class="v">{{ "%.6f"|format(e.position_size) ~ " " ~ e.coin if e.position_size else "-" }}</div></div>
</div>
```

Nieuwe code — voeg de pijltje-span toe in de "Nu"-cel, en de voortgangsbalk direct na de `data-grid`:

```html
<div class="data-grid">
  <div class="cell"><div class="k">Entry</div><div class="v">{{ "%.4f"|format(e.entry_price) }}</div></div>
  <div class="cell"><div class="k">Nu</div><div class="v" data-price="{{ e.id }}">{{ "%.4f"|format(e.current_price) if e.current_price else "-" }}<span class="price-direction" data-price-direction="{{ e.id }}" aria-hidden="true"></span></div></div>
  <div class="cell"><div class="k">SL</div><div class="v neg">{{ "%.4f"|format(e.stop_loss) if e.stop_loss else "-" }}</div></div>
  <div class="cell"><div class="k">TP</div><div class="v pos">{{ "%.4f"|format(e.take_profit) if e.take_profit else "-" }}</div></div>
  <div class="cell"><div class="k">Grootte</div><div class="v">{{ "%.6f"|format(e.position_size) ~ " " ~ e.coin if e.position_size else "-" }}</div></div>
</div>
{% if e.sltp_progress_pct is not none %}
<div class="sltp-progress" data-sltp="{{ e.id }}" data-stop="{{ e.stop_loss }}" data-take="{{ e.take_profit }}" data-direction="{{ e.direction }}">
  <div class="sltp-progress-fill" style="width: {{ e.sltp_progress_pct }}%"></div>
</div>
{% endif %}
```

- [ ] **Step 2: CSS**

Toevoegen aan `style.css`, in de buurt van de bestaande `.risk-gauge-*`-regels (zelfde soort component):

```css
.sltp-progress { height: 5px; border-radius: 3px; background: var(--border); overflow: hidden; margin: 8px 0 4px; }
.sltp-progress-fill {
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--red), #f2b03e, var(--green));
  transition: width 0.6s ease;
}
.price-direction { font-size: 10px; margin-left: 3px; }
.price-direction.pos { color: var(--green); }
.price-direction.neg { color: var(--red); }
@media (prefers-reduced-motion: reduce) { .sltp-progress-fill { transition: none; } }
```

- [ ] **Step 3: Commit**

```bash
git add web/templates/_macros.html web/static/style.css
git commit -m "_macros.html: SL/TP-voortgangsbalk en prijsrichting-pijltje op elke open trade"
```

---

### Task 5: dashboard.js — live bijwerken van ticker, voortgangsbalk en prijsrichting

**Files:**
- Modify: `web/static/dashboard.js` (bestaande `refresh()`-functie, rond regel 63-100)
- Test: handmatige Playwright-verificatie (samen met Task 6)

**Interfaces:**
- Consumes: bestaande `/api/open_positions`-response (al bevat `current_price`/`stop_loss`/`take_profit`/`direction`/`is_practice` per positie).
- Produces: bijgewerkte DOM voor `#dashboard-ticker-track [data-ticker-coin]`, `[data-sltp] .sltp-progress-fill`, `[data-price-direction]`.

- [ ] **Step 1: Gedeelde JS-versie van de progress-formule**

Voeg toe aan het begin van `dashboard.js` (buiten de bestaande IIFE, of als losse functie erboven — moet bereikbaar zijn vanuit `refresh()`):

```js
// Zelfde formule als risk.compute_sltp_progress_pct in app/risk.py: waar
// zit de prijs nu tussen stop loss (0%) en take profit (100%). Hier als
// JS-poort voor de live-update na de eerste, server-side render, geen
// aparte serverroundtrip nodig voor elke poll-tick.
function computeSltpProgressPct(direction, price, stopLoss, takeProfit) {
  var pos;
  if (direction === "long") {
    var span = takeProfit - stopLoss;
    pos = span ? (price - stopLoss) / span : 0;
  } else {
    var spanShort = stopLoss - takeProfit;
    pos = spanShort ? (stopLoss - price) / spanShort : 0;
  }
  return Math.max(0, Math.min(1, pos)) * 100;
}
```

- [ ] **Step 2: Ticker, voortgangsbalk en prijsrichting bijwerken in refresh()**

In `dashboard.js`'s bestaande `refresh()` (in de `.then((positions) => { positions.forEach((p) => { ... }) })`-lus), na de bestaande `pnlPctEl`-update-blok (rond regel 90-92) en vóór het "spanningsgloed"-commentaarblok (regel 93+), voeg toe:

```js
// Prijsrichting-pijltje: hergebruikt dezelfde previous[key]-vergelijking
// als de bestaande flash-logica hierboven, geen aparte state nodig.
const dirEl = document.querySelector(`[data-price-direction="${p.id}"]`);
if (dirEl && p.current_price !== null) {
  const priceKey = `price-${p.id}`;
  if (previous[priceKey] !== undefined && previous[priceKey] !== p.current_price) {
    const up = p.current_price > previous[priceKey];
    dirEl.textContent = up ? "▲" : "▼";
    dirEl.classList.toggle("pos", up);
    dirEl.classList.toggle("neg", !up);
  }
}

// SL/TP-voortgangsbalk: CSS transition op width doet de vloeiende
// beweging, hier alleen de nieuwe waarde zetten.
const sltpEl = document.querySelector(`[data-sltp="${p.id}"] .sltp-progress-fill`);
if (sltpEl && p.current_price !== null && p.stop_loss && p.take_profit) {
  const pct = computeSltpProgressPct(p.direction, p.current_price, p.stop_loss, p.take_profit);
  sltpEl.style.width = pct + "%";
}
```

LET OP: `dirEl`-blok moet NA de bestaande `if (previous[key] !== undefined ...) flash(...)`-call voor de prijs staan, maar VOORDAT `previous[key] = p.current_price;` die waarde overschrijft (anders vergelijkt dit blok de nieuwe waarde met zichzelf) — lees de exacte huidige volgorde in `refresh()` (regel 72-79) voordat je dit invoegt, en plaats de `dirEl`-logica er direct tussen (na de `flash()`-call, vóór `previous[key] = p.current_price;`), NIET pas na regel 92 zoals hierboven ruwweg aangegeven. Pas dit desnoods aan zodat de volgorde klopt: lees eerst `previous[key]`, dan pas overschrijven.

- [ ] **Step 3: Ticker bijwerken (nieuwe functie, aangeroepen vanuit refresh())**

Voeg toe aan `dashboard.js`:

```js
function updateTicker(positions) {
  const track = document.getElementById("dashboard-ticker-track");
  if (!track) return; // geen ticker-element op deze pagina/zonder open trades
  const seen = new Set();
  positions.forEach((p) => {
    if (p.is_practice || p.current_price === null || seen.has(p.coin)) return;
    seen.add(p.coin);
    document.querySelectorAll(`[data-ticker-coin="${p.coin}"] .ticker-price`).forEach((priceEl) => {
      const key = `ticker-${p.coin}`;
      priceEl.textContent = p.current_price.toFixed(4);
    });
  });
}
```

Roep `updateTicker(positions);` aan direct na de bestaande `positions.forEach((p) => { ... })`-lus in `refresh()` (dus na de hele bestaande forEach, met `positions` als argument).

- [ ] **Step 4: Commit**

```bash
git add web/static/dashboard.js
git commit -m "dashboard.js: live bijwerken van ticker, SL/TP-balk en prijsrichting-pijltje"
```

---

### Task 6: Handmatige Playwright-verificatie + regressie + push

**Files:** geen nieuwe, alleen verifiëren.

- [ ] **Step 1: Lokale server opzetten**

```bash
cd /home/user/Trade
DATABASE_PATH=/tmp/live_interactiviteit_verify.db python3 -c "from app import db; db.init_db()"
DATABASE_PATH=/tmp/live_interactiviteit_verify.db python3 scripts/create_user.py  # of handmatig een testuser + open trade + evaluatie aanmaken
DATABASE_PATH=/tmp/live_interactiviteit_verify.db uvicorn web.main:app --reload &
```

Zorg voor minstens: één echte, open trade met stop_loss/take_profit/current_price bekend, één actieve evaluatie met een deel van het dagbudget gebruikt, en één recent, echt signaal (voor de banner).

- [ ] **Step 2: Playwright-screenshots**

Navigeer naar `/dashboard`, maak screenshots van: de topbar met ticker zichtbaar, de laatste-seintje-banner, de SL/TP-voortgangsbalk op een open trade, het prijsrichting-pijltje (forceer een prijswijziging tussen twee polls als dat lokaal lastig is, of verifieer de DOM-structuur direct), en de risicogauge. Maak daarna dezelfde screenshots met `page.emulate_media(reduced_motion="reduce")` om te bevestigen dat alle animaties stilvallen zonder cijfers te verliezen.

- [ ] **Step 3: Regressie op de rest van de site**

Bevestig dat bestaande features niet gebroken zijn: de flash-animatie op prijs/PnL, de bestaande signal-wave, de bestaande heartbeat-snelheid buiten een net-binnengekomen-signaal-moment, de landingspagina se eigen ticker (ongewijzigd, apart bestand). Draai de scratch-tests uit Task 1 en Task 2 nog een keer tegen de huidige HEAD.

- [ ] **Step 4: Push**

```bash
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```
