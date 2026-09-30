# Positiegrootte, portfolio en evaluatie weghalen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De verweesde `/dashboard`-pagina, de evaluatie-simulatie-functie, en
alle resterende geld-gebaseerde positiegrootte/resultaat-berekening
(risk_eur/position_size/result_eur, en alles wat daarop leunt: ambient
gloed, cumulatieve grafiek, heatmap, wekelijkse samenvatting, live PnL)
volledig uit de actieve HesPulse-code verwijderen. Alles wat resultaat
toont, toont voortaan percentage.

**Architecture:** Eerst de twee zelfstandige, makkelijke stukken
(`/dashboard`, de losse rekenhulp). Dan evaluatie in twee lagen
(aanroepers eerst, dan de functies die ze aanriepen — nooit andersom,
anders breekt een tussentijdse taak de app). Dan `close_journal_trade`
zelf. Dan de zichtbare journaal/account-opschoning. Dan de grote,
regel-gebaseerde omzetting van elke statistiek- en weergavefunctie die nu
`result_eur` gebruikt naar `result_pct`. Elke taak laat de app werkend en
importeerbaar achter.

**Tech Stack:** FastAPI, Jinja2, SQLite (via `app/db.py`), vanilla JS
(`web/static/*.js`).

**Spec:** `docs/superpowers/specs/2026-09-30-positiegrootte-weghalen-design.md`
(inclusief het addendum onderaan — dat addendum is bindend, niet optioneel)

## Global Constraints

- Geen pytest-suite: verificatie via throwaway scripts tegen een scratch-
  database (`DATABASE_PATH=/tmp/scratch_*.db`) en handmatige Playwright-
  controle tegen een lokale `uvicorn web.main:app`-instantie.
- Commit-berichten eindigen met exact:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
  ```
- Code-commentaar en commit-berichten in het Nederlands, informele stijl.
- **Aanpak A (bindend voor dit hele project)**: `app/schema.sql` en
  `app/db.py:_migrate()` blijven ongewijzigd. Geen enkele kolom of tabel
  wordt verwijderd of gemigreerd — alleen code die ze leest/schrijft.
- **Blijft ongewijzigd, expliciet buiten scope**: `confirm_threshold_pct`,
  de verplichte-factoren-instelling (`TOGGLEABLE_FACTORS`), en
  `repo.winrate_for_user`/`signals.auto_outcome` (het automatische
  trackrecord) — dit zijn allemaal al los van geld.
- **Blijft ongewijzigd**: `risk.compute_stop_take`,
  `risk.compute_stop_take_from_levels`, `risk.compute_sltp_progress_pct`,
  `risk.compute_position_size` (blijft nodig, zie Taak 4 voor waarom),
  `_add_signal_context` (web/main.py) — geen van deze is geld-sizing of
  evaluatie.
- Elke taak die een functie/route verwijdert: grep zelf naar alle
  call-sites vóór je verwijdert, en controleer na de wijziging met
  `python3 -c "import app.X"`/`import web.main` dat er geen
  `NameError`/`AttributeError`/`ImportError` resteert.

---

## Task 1: `/dashboard` verwijderen

**Files:**
- Modify: `web/main.py:803-957` (route verwijderen), `web/main.py:1219-1234`
  (redirect-doel fixen)
- Delete: `web/templates/dashboard.html`
- Modify: `web/templates/base.html:37-67` (boot-pulse-conditie verplaatsen)

**Interfaces:**
- Produces: `/dashboard` geeft voortaan een 303-redirect naar `/signalen`
  terug (zelfde patroon als de bestaande `/`-route).

- [ ] **Step 1: Route vervangen**

Huidige code (`web/main.py:803-957`, de volledige `dashboard`-routefunctie,
803 t/m de afsluitende `})` op 957):

```python
@app.get("/dashboard")
async def dashboard(request: Request, status: str = "alle", user: dict = Depends(require_login)):
    all_entries = repo.list_journal(user["id"], status=None)
    ... [volledige functie-inhoud] ...
    return templates.TemplateResponse(request, "dashboard.html", {
        ...
    })
```

Vervang de HELE functie (803-957) door:

```python
@app.get("/dashboard")
async def dashboard():
    # Verweesde pagina van vóór de puur-signalen-herziening (2026-09-21):
    # geen navigatielink wijst hier meer naartoe, maar een oude
    # PWA-snelkoppeling kan nog steeds deze URL openen. Doorsturen i.p.v.
    # verwijderen voorkomt een kale 404 op zo'n bestaande snelkoppeling.
    return RedirectResponse(url="/signalen", status_code=303)
```

- [ ] **Step 2: Template verwijderen**

```bash
cd /home/user/Trade
git rm web/templates/dashboard.html
```

- [ ] **Step 3: `/settings/portfolio`'s redirect-doel fixen**

Huidige code (`web/main.py:1219-1234`):

```python
@app.post("/settings/portfolio")
async def update_settings(
    portfolio_eur: float = Form(...),
    risk_percent: float = Form(...),
    quiet_hours_start: str = Form(""),
    quiet_hours_end: str = Form(""),
    user: dict = Depends(require_login),
):
    # Allebei leeg = geen stille uren, blijft altijd geluid geven. Slechts
    # één van de twee ingevuld heeft geen betekenis, dan ook geen venster.
    start = quiet_hours_start.strip() or None
    end = quiet_hours_end.strip() or None
    if not (start and end):
        start, end = None, None
    repo.update_user_settings(user["id"], portfolio_eur, risk_percent, start, end)
    return RedirectResponse(url="/dashboard", status_code=303)
```

Verander ALLEEN de laatste regel (de rest van deze route wordt in Taak 6
verder aangepast, dit is puur de minimale fix om `/dashboard`'s
verwijdering niet iets te breken):

```python
    return RedirectResponse(url="/account", status_code=303)
```

- [ ] **Step 4: Boot-pulse-conditie verplaatsen in `base.html`**

Huidige code (`web/templates/base.html:37`):

```html
{% if request.url.path == "/dashboard" %}
```

Vervang door:

```html
{% if request.url.path == "/signalen" %}
```

(De rest van dat blok, regel 38-67, blijft ongewijzigd — dit is de enige
regel die verandert. `/signalen` is sinds de puur-signalen-herziening de
daadwerkelijke standaardpagina na inloggen, dus dit is de juiste plek voor
de "zojuist geopend"-animatie.)

- [ ] **Step 5: Importcheck en handmatige verificatie**

```bash
cd /home/user/Trade && python3 -c "import web.main; print('import OK')"
```

Start de app lokaal tegen een scratch-database en bevestig met curl dat
`/dashboard` een 303 naar `/signalen` teruggeeft:

```bash
cd /home/user/Trade
rm -f /tmp/scratch_dashboard_removal.db
DATABASE_PATH=/tmp/scratch_dashboard_removal.db python3 -c "from app import db; db.init_db()"
DATABASE_PATH=/tmp/scratch_dashboard_removal.db python3 -c "
from app import repo
from app.security import hash_password
repo.create_user(username='t', password_hash=hash_password('testpass123'), portfolio_eur=1000.0, risk_percent=1.0)
"
DATABASE_PATH=/tmp/scratch_dashboard_removal.db JWT_SECRET=test_secret_1234567890 uvicorn web.main:app --port 8011 &
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8011/dashboard
# Expected: 303 (curl volgt redirects niet standaard, dus dit toont de
# redirect-status zelf, niet 200 van de uiteindelijke pagina)
kill %1
rm -f /tmp/scratch_dashboard_removal.db
```

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/main.py web/templates/base.html
git commit -m "$(cat <<'EOF'
/dashboard verwijderen: doorsturen naar /signalen

Verweesde pagina van vóór de puur-signalen-herziening (2026-09-21) —
geen navigatielink wijst er meer naartoe, maar een oude PWA-snelkoppeling
kon nog steeds de oude UI (evaluatie-kaart, risicogauge, oude
journaal-kaarten) openen. Route stuurt nu door naar /signalen i.p.v. een
404, template weg. Boot-pulse-animatie (was aan /dashboard gekoppeld)
verhuist naar /signalen, de daadwerkelijke standaardpagina na inloggen.
/settings/portfolio's redirect-doel gefixt naar /account (stond nog op
/dashboard, zou anders een 404 zijn geworden na deze wijziging).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 2: Losse rekenhulp op de coin-pagina verwijderen

**Files:**
- Modify: `web/main.py` (verwijder `_fetch_practice_trade_calc` regel
  1494-1509, `_resolve_practice_risk_eur` regel 1512-1567,
  `preview_practice_trade`/route `POST /coins/{symbol}/oefen-preview`
  regel 1569-1618)
- Modify: `web/templates/coin.html:234-258` (rekenhulp-blok verwijderen)
- Modify: `web/static/coin.js:661-717` (runPreview-IIFE verwijderen)

**Interfaces:**
- Produces: geen — dit is een verwijder-taak. `risk.compute_position_size`
  blijft bestaan (zie Taak 4), deze taak verwijdert alleen de aanroep
  ervoor vanuit de rekenhulp.

- [ ] **Step 1: Verwijder de drie functies uit `web/main.py`**

Zoek en verwijder (exacte huidige inhoud, regelnummers kunnen na Taak 1
iets verschoven zijn — zoek op functienaam, niet blind op regelnummer):

```python
async def _fetch_practice_trade_calc(symbol: str, direction: str):
    """Live technische berekening voor een oefentrade: candles ophalen,
    indicatoren en stop loss/take profit. Gedeeld door het daadwerkelijk
    aanmaken van een oefentrade en de live-voorbeeldroute ervoor, zodat de
    preview nooit kan afwijken van wat er bij versturen echt gebeurt."""
    df = await asyncio.to_thread(exchange.fetch_ohlcv, symbol)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)
    stop_take = risk.compute_stop_take(direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high)
    return df, ind, stop_take
```

en de volledige `_resolve_practice_risk_eur`-functie (regel 1512-1567 —
lees de exacte huidige inhoud zelf op, dit is een evaluatie-sizing-helper
identiek qua opzet aan `_resolve_signal_risk` in `signal_processor.py`,
met dezelfde structuur: actieve evaluatie ophalen, stop-cap toepassen,
risicobedrag berekenen, terugvallen op het handmatig ingevulde bedrag
zonder evaluatie),

en de volledige route:

```python
@app.post("/coins/{symbol}/oefen-preview")
async def preview_practice_trade(
    symbol: str,
    direction: str = Form(...),
    risk_eur: str = Form(""),
    user: dict = Depends(require_login),
):
    """Live rekenhulp voor het oefentrade-formulier: dezelfde technische
    berekening en hefboom-cap als het echte aanmaken, maar slaat niets op.
    Laat je vooraf zien welke positie en of die gecapt wordt, in plaats
    van dat achteraf op de trade-kaart te ontdekken."""
    symbol = symbol.upper()
    if direction not in ("long", "short") or not repo.coin_is_tracked(symbol):
        return JSONResponse({"error": "ongeldige coin of richting"}, status_code=400)

    manual_risk_eur = _parse_optional_float(risk_eur)

    _df, ind, stop_take = await _fetch_practice_trade_calc(symbol, direction)
    active_eval = repo.get_active_evaluation(user["id"])
    (
        used_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, _link_to_evaluation,
        effective_stop_loss, effective_take_profit,
    ) = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
    )
    position_size = (
        risk.compute_position_size(used_risk_eur, ind.price, effective_stop_loss, cost_rate=cost_rate)
        if used_risk_eur is not None else None
    )
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
    })
```

Let op: `active_evaluation = repo.get_active_evaluation(user["id"])` in de
`coin_page`-route (elders in `web/main.py`, rond regel 1733, buiten dit te
verwijderen blok) blijft voorlopig staan — die wordt in Taak 3 verwijderd
samen met de rest van de evaluatie-aanroepende kant, niet hier. Verwijder
in DEZE taak alleen de drie bovenstaande functies/route.

- [ ] **Step 2: Rekenhulp-blok verwijderen uit `coin.html`**

Huidige code (`web/templates/coin.html:234-258`):

```html
<details class="stats-collapse js-accordion" style="--i: 6">
  <summary class="stats-summary">
    <svg class="h2-icon" ...></svg>
    <span>Oefenen met deze coin</span>
    <svg class="chevron" ...></svg>
  </summary>
  {% if active_evaluation %}
  <p class="muted" style="margin: 0 0 var(--space-4); font-size: var(--text-base);">⚠️ Deze oefentrade telt mee op je lopende evaluatie (€{{ "%.0f"|format(active_evaluation.tier_amount) }}, huidig saldo €{{ "%.2f"|format(active_evaluation.current_balance) }}). Vul een risico in dat bij dát saldo past, anders wordt je normale risicopercentage over je eigen portefeuille gebruikt.</p>
  {% endif %}
  <p class="muted" style="margin: 0 0 var(--space-5);">Kies zelf een richting en krijg direct de volledige toetsing:
  trend, momentum, RSI, volume, stop loss en take profit, precies zoals bij een echt signaal.
  Telt niet mee in je echte winrate en stuurt geen melding.</p>
  <div class="inline-form" id="oefen-form">
    <label>Richting
      <select name="direction" id="oefen-direction">
        <option value="long">Long</option>
        <option value="short">Short</option>
      </select>
    </label>
    <label>Risico in €
      <input type="number" step="0.01" min="0" name="risk_eur" id="oefen-risk-eur" placeholder="risicobedrag in euro">
    </label>
  </div>
  <p class="muted" id="oefen-preview" style="margin: var(--space-4) 0 0; font-size: var(--text-base); min-height: 16px;"></p>
</details>
```

Verwijder dit hele `<details>`-blok (inclusief het openende `<details>` en
sluitende `</details>`).

- [ ] **Step 3: `runPreview`-IIFE verwijderen uit `coin.js`**

Zoek de IIFE die begint met (exacte grep-string, regel 661 in de huidige
staat, kan verschoven zijn):

```javascript
(function () {
  // Live rekenhulp op het oefentrade-formulier
```

en eindigt bij de afsluitende `})();` van diezelfde IIFE (rond regel 717
in de huidige staat — lees de exacte huidige inhoud zelf op om het
precieze eindpunt te vinden, de IIFE bevat `runPreview`,
`scheduleRunPreview`, `formatEur`, en de twee `addEventListener`-regels
voor `directionSelect`/`riskInput`). Verwijder het hele blok.

- [ ] **Step 4: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import web.main; print('import OK')"
```

- [ ] **Step 5: Handmatige Playwright-verificatie**

Bezoek een coin-pagina tegen een scratch-database, bevestig dat de
"Oefenen met deze coin"-sectie niet meer bestaat en er geen JS-console-
fouten optreden (ontbrekende `#oefen-form`/`#oefen-preview`-elementen
mogen geen error geven — `coin.js`'s verwijderde IIFE begint zelf al met
een guard `if (!form || ...) return;`, dus als er per ongeluk toch nog
een restant van de IIFE staat zonder dat het element bestaat, faalt dat
stil, niet met een crash — controleer dus expliciet dat de hele IIFE weg
is, niet alleen dat er geen error verschijnt).

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/main.py web/templates/coin.html web/static/coin.js
git commit -m "$(cat <<'EOF'
Losse positie-rekenhulp op coin-pagina weg

De "Oefenen met deze coin"-rekenhulp (risicobedrag intypen, live
positiegrootte zien) had geen aanmaakroute meer sinds de puur-signalen-
herziening — puur een risico-in-euro's-rekenmachine. Weg, consistent met
"geen enkele geld-berekening meer in HesPulse". _fetch_practice_trade_calc,
_resolve_practice_risk_eur en de /coins/{symbol}/oefen-preview-route
verwijderd uit web/main.py, het formulier uit coin.html, de bijbehorende
JS uit coin.js.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 3: Evaluatie — aanroepende kant verwijderen

**Files:**
- Modify: `web/main.py` (routes `/evaluatie*`, `_build_eval_context`,
  `_check_eval_danger_alert`, `_attach_discipline_facts` + 2
  overgebleven call-sites, `_build_discipline_profile`,
  `_eval_history_stats`, de eval-progress-update-blok in de
  `close_journal`-route, `active_evaluation`-var in `coin_page`)
- Modify: `app/signal_processor.py` (`_resolve_signal_risk`,
  `_notify_signal_update`)
- Delete: `web/templates/evaluatie.html`, `web/static/evaluatie.js`
- Modify: `web/templates/_macros.html` (`discipline_facts`-macro)
- Modify: `web/templates/base.html:155-204` (evaluatie-redirect/confetti-
  dedup-JS)
- Modify: `web/static/style.css` (eval-specifieke CSS, zie Step 8)

**Interfaces:**
- Consumes: niets van Taak 1/2.
- Produces: geen — dit verwijdert AANROEPERS van `risk.py`/`repo.py`'s
  evaluatie-functies. Die functies zelf blijven nog bestaan na deze taak
  (Taak 4 verwijdert ze) — dat is bewust, zodat elke taak de app werkend
  achterlaat (een functie die nog bestaat maar geen aanroeper meer heeft
  is geen bug).

**Belangrijk**: dit is de grootste, meest verspreide taak van het project.
Ga methodisch te werk, één sub-stap per keer, en run na elke stap de
importcheck.

- [ ] **Step 1: De drie `/evaluatie*`-routes verwijderen**

```python
@app.post("/evaluatie/start")
async def start_evaluation(user: dict = Depends(require_login)):
    # Nieuwe evaluatie-runs starten kan sinds HesPulse-verkleinen
    # (2026-09-30) niet meer (zie de spec: ongewenst, prop-evaluatie is
    # weinig gebruikt en kost onderhoud). De route blijft bestaan zodat een
    # oude bladwijzer of het startformulier (nu verwijderd, evaluatie.html)
    # niet op een 404 uitkomt — stil negeren en terug naar /evaluatie, dat
    # bestaande/afgesloten runs blijft tonen.
    return RedirectResponse(url="/evaluatie", status_code=303)
```

en `POST /evaluatie/stop` (regel 1463-1468 in de huidige staat) en
`GET /evaluatie` (regel 1471-1491 in de huidige staat) — lees de exacte
huidige inhoud van deze twee zelf op en verwijder ze volledig, inclusief
hun `@app.post`/`@app.get`-decorator.

- [ ] **Step 2: `_build_eval_context` en `_eval_history_stats` verwijderen**

Verwijder de volledige `_build_eval_context`-functie (rond regel 410-487
in de huidige staat — de functie die begint met
`def _build_eval_context(user: dict, request: Request) -> dict:` en eindigt
bij de `return {...}`-dict met `eval_open_risk_pct` als laatste key) en de
volledige `_eval_history_stats`-functie (begint direct erna, rond regel
490).

- [ ] **Step 3: `_check_eval_danger_alert` verwijderen**

Verwijder de volledige functie inclusief de `EVAL_DANGER_THRESHOLD_PCT`-
constante erboven (huidige exacte inhoud, rond regel 1277-1314):

```python
EVAL_DANGER_THRESHOLD_PCT = 85.0  # zelfde drempel als de risk-pulse-animatie elders in de app


async def _check_eval_danger_alert(
    active_eval: dict, progress: risk.PropProgress, evaluation_id: int, user_id: int,
) -> None:
    """Stuurt een pushmelding zodra dagverlies of drawdown de
    85%-drempel passeert op een run die nog actief is (zelfde percentages
    als _build_eval_context laat zien op de evaluatiepagina). Vuurt maar
    één keer per overschrijding: danger_alert_sent voorkomt herhaling op
    elke volgende trade-close, en wordt teruggezet zodra het percentage
    weer onder de drempel zakt, zodat een latere nieuwe overschrijding in
    dezelfde run wél weer gemeld wordt."""
    daily_loss_amount = progress.day_start_balance * active_eval["max_daily_loss_pct"] / 100
    loss_so_far = max(0.0, progress.day_start_balance - progress.current_balance)
    daily_loss_used_pct = min(100.0, (loss_so_far / daily_loss_amount * 100) if daily_loss_amount else 0.0)
    daily_remaining_eur = max(0.0, daily_loss_amount - loss_so_far)

    drawdown_amount = active_eval["tier_amount"] * active_eval["max_drawdown_pct"] / 100
    drawdown_so_far = max(0.0, active_eval["tier_amount"] - progress.current_balance)
    drawdown_used_pct = min(100.0, (drawdown_so_far / drawdown_amount * 100) if drawdown_amount else 0.0)
    drawdown_remaining_eur = max(0.0, drawdown_amount - drawdown_so_far)

    in_danger_zone = daily_loss_used_pct >= EVAL_DANGER_THRESHOLD_PCT or drawdown_used_pct >= EVAL_DANGER_THRESHOLD_PCT
    if not in_danger_zone:
        if active_eval["danger_alert_sent"]:
            repo.set_evaluation_danger_alert_sent(evaluation_id, False)
        return

    if active_eval["danger_alert_sent"]:
        return

    if drawdown_used_pct >= daily_loss_used_pct:
        pct_type, pct_value, remaining_eur = "drawdown", drawdown_used_pct, drawdown_remaining_eur
    else:
        pct_type, pct_value, remaining_eur = "dagverlies", daily_loss_used_pct, daily_remaining_eur

    title = f"Evaluatie: {pct_type} op {pct_value:.0f}%"
    body = f"Nog {remaining_eur:.0f} EUR ruimte over van {active_eval['tier_amount']:.0f} EUR tier."
    await push_notify.send_push(user_id, title, body, "/evaluatie", silent=False)
    repo.set_evaluation_danger_alert_sent(evaluation_id, True)
```

- [ ] **Step 4: Eval-progress-update-blok verwijderen uit de `close_journal`-route**

Zoek de `close_journal`-route (waar `repo.close_journal_trade(...)` wordt
aangeroepen). Binnen deze route staat, ná de `close_journal_trade`-aanroep,
een `if evaluation_id:`-blok dat de evaluatie-voortgang bijwerkt
(`risk.evaluate_prop_progress`, `repo.update_evaluation_state`,
`repo.close_evaluation`, `_check_eval_danger_alert`) — verwijder dit hele
`if evaluation_id:`-blok. Laat de regel die `close_journal_trade` aanroept
en unpackt voorlopig ongewijzigd staan (`result_eur, is_practice,
evaluation_id = repo.close_journal_trade(...)`) — die wordt in Taak 5
aangepast, niet hier. Na deze stap is `evaluation_id` een ongebruikte
lokale variabele in die route; dat is prima, Python geeft daar geen
foutmelding voor, en Taak 5 ruimt de unpacking zelf op.

- [ ] **Step 5: `_attach_discipline_facts` en `_build_discipline_profile` verwijderen**

Verwijder de volledige `_attach_discipline_facts`-functie:

```python
def _attach_discipline_facts(entries: list[dict]) -> None:
    """Zet trade_number_in_day en risk_percent_used op elke entry die aan
    een evaluatie gekoppeld is (mutatie in place, zelfde patroon als
    entry['position_size'] = _position_size(entry) elders). Puur feiten op
    de kaart zelf, geen oordeel -- de patroonanalyse zit apart in
    _build_discipline_profile. Eén lookup per unieke evaluation_id, niet
    per entry, want list_evaluation_trade_context haalt toch de hele run op."""
    eval_ids = {e["evaluation_id"] for e in entries if e.get("evaluation_id")}
    for eval_id in eval_ids:
        context_by_id = {t["id"]: t for t in repo.list_evaluation_trade_context(eval_id)}
        for entry in entries:
            if entry.get("evaluation_id") == eval_id and entry["id"] in context_by_id:
                ctx = context_by_id[entry["id"]]
                entry["trade_number_in_day"] = ctx["trade_number_in_day"]
                entry["risk_percent_used"] = ctx["risk_percent_used"]
```

en de volledige `_build_discipline_profile`-functie (rond regel 545-602 in
de huidige staat, bevat de `by_risk_size`/`_win_rate_by`-logica).

Verwijder daarna elke `_attach_discipline_facts(...)`-AANROEP (niet de
functie zelf nogmaals, die is al weg) in `account_page`- en
`coin_page`-route (2 call-sites — grep zelf op `_attach_discipline_facts(`
om ze te vinden, de derde call-site in de oude `dashboard`-route is al
weg via Taak 1).

- [ ] **Step 6: `active_evaluation`-context-var verwijderen uit `coin_page`**

In de `coin_page`-route staat `active_evaluation =
repo.get_active_evaluation(user["id"])`, doorgegeven aan de template.
Verwijder deze regel en de bijbehorende key in de
`templates.TemplateResponse(...)`-context-dict van die route.

- [ ] **Step 7: `signal_processor.py` — evaluatie-koppeling verwijderen**

Huidige `_resolve_signal_risk` (volledige functie, regel 357-383 in de
huidige staat):

```python
def _resolve_signal_risk(
    user: dict, direction: str, entry_price: float, stop_loss: float, take_profit: float,
) -> tuple[Optional[float], Optional[int], float, float, float]:
    """Risicobedrag, evaluation_id (of None), cost_rate, en de effectieve
    (mogelijk ingeperkte) stop_loss/take_profit voor één signaal aan één
    gebruiker. Gebruikt de actieve evaluatie als sizing-basis zodra die er
    is en er nog voldoende budget is ..."""
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
    return None, None, 0.0, stop_loss, take_profit
```

Vervang door:

```python
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
```

(De parameters `user`/`direction`/`entry_price` worden nu niet meer
gebruikt binnen de functie — dat is bewust geen probleem, Python geeft
geen foutmelding voor ongebruikte functieparameters, en de aanroepers
blijven zo ongewijzigd.)

Zoek de `_notify_signal_update`-functie. Huidige code rond de
evaluatie-koppeling (regel 1197-1238 in de huidige staat):

```python
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
```

Vervang door alleen:

```python
        message_data = signal_data
```

(De hele `if entry["entry_price"] is None and entry["evaluation_id"] is
not None:`-tak gaat weg — zonder evaluatie is er nooit meer een
`evaluation_id`, dus `message_data` is altijd gewoon `signal_data`.)

- [ ] **Step 8: Templates, JS en CSS verwijderen/opschonen**

```bash
cd /home/user/Trade
git rm web/templates/evaluatie.html web/static/evaluatie.js
```

In `web/templates/_macros.html`, vervang de volledige `discipline_facts`-
macro:

```jinja
{# Disciplinefeiten van een evaluatie-gekoppelde trade (welk volgnummer op
   zijn handelsdag, hoeveel procent van het toenmalige saldo), gebruikt op
   zowel het oefentrade-blok als bij een echte, genomen evaluatie-trade.
   Puur weergave, geen oordeel — zie repo.list_evaluation_trade_context. #}
{% macro discipline_facts(e) %}
{% if e.evaluation_id and e.trade_number_in_day %}
<p class="muted" style="margin: 4px 0 0; font-size: 12.5px;">
  {{ e.trade_number_in_day }}e trade vandaag op deze evaluatie{% if e.risk_percent_used is not none %} · {{ "%.2f"|format(e.risk_percent_used) }}% van het saldo op dat moment{% endif %}
</p>
{% endif %}
{% endmacro %}
```

door — verwijder de macro EN zijn enige aanroep (in `open_trade_body`,
regel `{{ discipline_facts(e) }}`) volledig, in plaats van een lege macro
achter te laten:

1. Verwijder de hele `{% macro discipline_facts(e) %}...{% endmacro %}`-
   definitie.
2. Zoek in dezelfde file `open_trade_body`'s regel `{{ discipline_facts(e) }}`
   en verwijder die regel.

In `web/templates/base.html`, verwijder regel 155-204 (het hele JS-blok
voor `willRedirectForEval`/de `evaluatie_geslaagd`/`evaluatie_mislukt`-
query-param-afhandeling — huidige exacte inhoud):

```javascript
    var willRedirectForEval = (
      (location.search.indexOf("evaluatie_geslaagd=1") !== -1 || location.search.indexOf("evaluatie_mislukt=1") !== -1)
      && location.pathname !== "/evaluatie"
    );

    if (location.search.indexOf("closed_win=1") !== -1) {
      if (!willRedirectForEval) fireConfetti();
      var url = new URL(location.href);
      url.searchParams.delete("closed_win");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }

    if (location.search.indexOf("evaluatie_geslaagd=1") !== -1 || location.search.indexOf("evaluatie_mislukt=1") !== -1) {
      if (location.pathname !== "/evaluatie") {
        var evalFlag = location.search.indexOf("evaluatie_geslaagd=1") !== -1 ? "evaluatie_geslaagd" : "evaluatie_mislukt";
        location.replace("/evaluatie?" + evalFlag + "=1");
      } else {
        var evalStatusUrl = new URL(location.href);
        evalStatusUrl.searchParams.delete("evaluatie_geslaagd");
        evalStatusUrl.searchParams.delete("evaluatie_mislukt");
        history.replaceState(null, "", evalStatusUrl.pathname + evalStatusUrl.search + evalStatusUrl.hash);
      }
    }
```

Vervang door de simpelere, niet-eval-afhankelijke versie (behoudt alleen
de gewone `closed_win`-confetti, zonder de eval-redirect-guard):

```javascript
    if (location.search.indexOf("closed_win=1") !== -1) {
      fireConfetti();
      var url = new URL(location.href);
      url.searchParams.delete("closed_win");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
```

In `web/static/style.css`, zoek en verwijder de evaluatie-specifieke
CSS-classes: `.eval-reveal-pass`, `.eval-reveal-fail`, `.prop-eval-head`
(rond regel 1580-1614 in de huidige staat — lees de exacte huidige inhoud
zelf op via `grep -n "eval-reveal\|prop-eval-head" web/static/style.css`
en verwijder elk gevonden blok). Laat `.risk-gauge`/`.risk-gauge-fill` met
rust in deze taak — die worden pas dood zodra ook Taak 1 (dashboard.html,
al gedaan) en deze taak samen alle gebruikers hebben weggehaald; een
losse grep-verificatie hierop hoort bij Taak 11's eindcontrole, niet hier.

- [ ] **Step 9: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import web.main; import app.signal_processor; print('import OK')"
```

- [ ] **Step 10: Throwaway-scriptverificatie**

```bash
cd /home/user/Trade
rm -f /tmp/scratch_eval_callers.db
DATABASE_PATH=/tmp/scratch_eval_callers.db python3 -c "
from app import db, repo
db.init_db()
from app.security import hash_password
uid = repo.create_user(username='t', password_hash=hash_password('testpass123'), portfolio_eur=1000.0, risk_percent=1.0)
from app import signal_processor
r = signal_processor._resolve_signal_risk({'id': uid, 'risk_percent': 1.0}, 'long', 100.0, 95.0, 110.0)
assert r == (None, None, 0.0, 95.0, 110.0), f'onverwacht: {r}'
print('_resolve_signal_risk OK:', r)
"
rm -f /tmp/scratch_eval_callers.db
```

- [ ] **Step 11: Handmatige Playwright-verificatie**

Bezoek `/evaluatie` rechtstreeks tegen een scratch-database — bevestig een
duidelijke fout of 404 is NIET het doel hier (de route bestaat immers nog
niet meer verwijderd, dat gebeurt pas in Taak 4 als de onderliggende
`repo`/`risk`-functies weg zijn; als de route al een importfout geeft is
er iets misgegaan in deze taak). Bezoek `/signalen`, `/account`,
`/coins/BTC` en controleer dat er geen crash optreedt.

- [ ] **Step 12: Commit**

```bash
cd /home/user/Trade
git add web/main.py app/signal_processor.py web/templates/ web/static/evaluatie.js web/static/style.css
git commit -m "$(cat <<'EOF'
Evaluatie-simulatie: aanroepende kant verwijderd

Alle plekken die de evaluatie-functie AANROEPEN zijn weg: de drie
/evaluatie*-routes (start/stop zijn no-ops geworden, de paginaroute zelf
is weg), _build_eval_context, _check_eval_danger_alert, het
eval-progress-updateblok in /journal/{id}/close, discipline-profile-
opbouw, en de evaluatie-koppeling in signal_processor.py
(_resolve_signal_risk/_notify_signal_update). evaluatie.html/evaluatie.js
weg, discipline_facts-macro weg, evaluatie-redirect/confetti-dedup-JS in
base.html vereenvoudigd, evaluatie-specifieke CSS weg.

De functies die deze aanroepers zelf aanriepen (risk.py/repo.py) staan
er bewust nog — die worden in de volgende taak verwijderd, nadat ze geen
aanroeper meer hebben.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 4: Evaluatie — risk.py en repo.py functies verwijderen

**Files:**
- Modify: `app/risk.py`
- Modify: `app/repo.py`

**Interfaces:**
- Consumes: Taak 3 moet eerst gedaan zijn (anders verwijder je functies
  die nog een aanroeper hebben).
- Produces: geen — verwijder-taak.

- [ ] **Step 1: `app/risk.py` — evaluatie-functies en -constanten verwijderen**

Verwijder deze functies volledig (naam, exacte regel-range in de huidige
staat — zoek op functienaam, regelnummers kunnen na Taak 1-3 verschoven
zijn):

- `evaluate_prop_progress` (40-69)
- `effective_day_start_balance` (129-141)
- `compute_eval_daily_budget_remaining` (144-152)
- `compute_eval_drawdown_budget_remaining` (155-160)
- `eval_sizing_blocked` (163-180)
- `compute_eval_risk_eur` (183-200)
- `eval_max_stop_pct` (285-292)
- `apply_eval_stop_cap` (295-328)
- `compute_risk_eur` (331-332 — dit is de GENERIEKE `portfolio_eur *
  risk_percent / 100`-sizing, al dode code sinds een eerdere opschoning,
  geen enkele actieve aanroeper meer buiten `scripts/test_step1_bitcoin.py`
  — dat losse verificatiescript raak je niet aan, dit is geen pytest-
  suite en het script blijft werken zolang je het niet aanroept)
- `trading_day_label` (14-22 — wordt na het verwijderen van de bovenstaande
  functies volledig ongebruikt; bevestig dit zelf met
  `grep -rn "trading_day_label(" app/ web/` vóór je hem verwijdert, en
  verwijder hem alleen als de enige match de eigen definitie is)

Verwijder deze constanten (zoek elk zelf op met
`grep -n "^EVAL_\|^MAX_EVAL_\|^STOP_CAP_" app/risk.py`):
- `MAX_EVAL_LEVERAGE`
- `EVAL_BUDGET_TRADE_RESERVE`
- `EVAL_BUDGET_BLOCK_THRESHOLD_PCT`
- `STOP_CAP_REFERENCE_TIER`
- `STOP_CAP_MIN_PCT`
- `STOP_CAP_MAX_PCT`
- `EVAL_TRADE_FEE_RATE`
- `EVAL_LEVERAGE_DAILY_RATE`
- `EVAL_SIZING_DAYS_ASSUMPTION`

**Blijft staan** (niet aanraken): `compute_stop_take`,
`compute_stop_take_from_levels`, `compute_position_size` (blijft nodig,
zie hieronder), `compute_unrealized_pnl` (wordt in Taak 9 aangepast, niet
hier), `compute_sltp_progress_pct`, en de constanten
`ATR_BUFFER_MULTIPLIER`/`ATR_STOP_MULTIPLIER_FALLBACK`/`RISK_REWARD_RATIO`/
`MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION`.

**Waarom `compute_position_size` blijft**: `web/main.py`'s
`_position_size`-helper (regel 685-698 in de huidige staat) valt voor OUDE
journaalregels van vóór de `position_size`-kolom bestond terug op
`risk.compute_position_size(entry["risk_eur"], entry["price"],
entry["stop_loss"])` (zonder `cost_rate`) — dit is een legacy-fallback
voor historische data, geen evaluatie- of generieke-sizing-aanroep. Deze
functie blijft dus, ongewijzigd (de `cost_rate`-parameter mag blijven
staan ook al geeft na deze opschoning niemand er nog een waarde aan —
laten staan is minder risico dan de signatuur aanpassen voor iets wat toch
altijd 0.0 default is).

- [ ] **Step 2: `app/repo.py` — evaluatie-CRUD-functies verwijderen**

Verwijder deze functies volledig (zoek elk op met `grep -n "^def " app/repo.py`
om de exacte huidige regelnummers te bevestigen):

- `create_evaluation`
- `get_active_evaluation`
- `get_evaluation`
- `list_evaluations_for_user`
- `update_evaluation_state`
- `set_evaluation_danger_alert_sent`
- `close_evaluation`
- `list_evaluation_daily_results`
- `list_evaluation_balance_curve`
- `list_evaluation_trade_context`
- `total_open_risk_eur_for_evaluation`

Vóór je elke functie verwijdert: bevestig met
`grep -rn "<functienaam>(" app/ web/` dat na Taak 3 alleen de eigen
definitie nog overblijft (geen enkele aanroeper meer). Als je toch nog een
aanroeper vindt die niet in Taak 3 is weggehaald, is dat een gemiste
call-site uit Taak 3 — fix die aanroep dan hier alsnog (verwijder hem),
documenteer dat in je zelfreview, ga niet zomaar door met een kapotte
aanroep in de codebase.

- [ ] **Step 3: Importcheck**

```bash
cd /home/user/Trade && python3 -c "
import app.risk
import app.repo
import app.signal_processor
import web.main
print('import OK')
"
```

- [ ] **Step 4: Grep-verificatie geen resterende evaluatie-aanroepen**

```bash
cd /home/user/Trade
grep -rn "get_active_evaluation\|create_evaluation\|eval_sizing_blocked\|compute_eval_risk_eur\|apply_eval_stop_cap\|eval_max_stop_pct\|evaluate_prop_progress" app/ web/main.py
```

Expected: lege output (of alleen treffers in `scripts/`/`docs/`, die tellen
niet mee — dit commando checkt `app/` en `web/main.py` specifiek).

- [ ] **Step 5: Commit**

```bash
cd /home/user/Trade
git add app/risk.py app/repo.py
git commit -m "$(cat <<'EOF'
Evaluatie-simulatie: risk.py/repo.py functies verwijderd

Nu Taak 3 alle aanroepers weg heeft gehaald, kunnen de evaluatie-eigen
functies zelf ook weg: risk.py's evaluate_prop_progress t/m
apply_eval_stop_cap plus hun constanten, en repo.py's volledige
evaluatie-CRUD (create_evaluation t/m total_open_risk_eur_for_evaluation).
compute_risk_eur (de generieke portfolio_eur x risk_percent-sizing) ook
weg, was al dode code sinds een eerdere opschoning. compute_position_size
blijft — nodig voor de legacy-fallback in web/main.py's _position_size-
helper voor oude journaalregels van vóór de position_size-kolom bestond.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 5: `close_journal_trade` vereenvoudigen + `/api/system_status` opschonen

**Files:**
- Modify: `app/repo.py` (`close_journal_trade`)
- Modify: `web/main.py` (`close_journal`-route's unpacking, `won`-berekening,
  `/api/system_status`)

**Interfaces:**
- Consumes: Taak 4 (evaluatie-functies moeten al weg zijn).
- Produces: `close_journal_trade(entry_id, user_id, exit_price, exit_time)
  -> tuple[float, bool]` (was `tuple[float, bool, Optional[int]]`) — geeft
  nu `(result_pct, is_practice)` terug, geen `result_eur`/`evaluation_id`
  meer. Latere taken (7, 8, 9) gaan ervan uit dat `result_eur` nergens meer
  geschreven wordt door deze functie.

- [ ] **Step 1: `close_journal_trade` herschrijven**

Huidige volledige code (`app/repo.py:1600-1676`):

```python
def close_journal_trade(entry_id: int, user_id: int, exit_price: float, exit_time: str) -> tuple[float, bool, Optional[int]]:
    """Sluit de trade af en geeft (result_eur, is_practice, evaluation_id)
    terug: is_practice bepaalt of dit voor de winst-confetti telt,
    evaluation_id (kan None zijn) vertelt de caller of dit resultaat nog op
    een lopende evaluatie-simulatie moet worden bijgeschreven."""
    entry = get_journal_entry(entry_id, user_id)
    if not entry or entry["entry_price"] is None or entry["status"] == "genegeerd":
        raise ValueError("kan alleen sluiten als er een entry prijs is ingevuld en de trade niet genegeerd is")

    entry_price = entry["entry_price"]
    direction = entry["direction"].lower()
    risk_eur = entry["risk_eur"] or 0.0
    stop_loss = entry["stop_loss"]

    if direction == "long":
        result_pct = (exit_price - entry_price) / entry_price * 100
        risk_per_unit = entry_price - stop_loss if stop_loss else None
    else:
        result_pct = (entry_price - exit_price) / entry_price * 100
        risk_per_unit = stop_loss - entry_price if stop_loss else None

    if risk_per_unit and risk_per_unit > 0:
        move = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
        result_eur = risk_eur * (move / risk_per_unit)
    else:
        result_eur = risk_eur * (result_pct / 100)

    # Fees en hefboomkosten van een Kraken Prop-achtig evaluatie-account
    # gelden alleen voor trades die aan een evaluatie hangen; een gewone
    # portfolio-trade kent dit systeem niet en result_eur blijft daar
    # ongewijzigd, exact het bestaande gedrag.
    if entry["evaluation_id"] is not None:
        notional_eur = (entry["position_size"] or 0.0) * entry_price
        trade_fee_eur = notional_eur * risk.EVAL_TRADE_FEE_RATE
        days_held = 0.0
        if entry["entry_time"]:
            exit_dt = datetime.fromisoformat(exit_time)
            entry_dt = datetime.fromisoformat(entry["entry_time"])
            if exit_dt.tzinfo is not None:
                exit_dt = exit_dt.replace(tzinfo=None)
            if entry_dt.tzinfo is not None:
                entry_dt = entry_dt.replace(tzinfo=None)
            days_held = max(0.0, (exit_dt - entry_dt).total_seconds() / 86400)
        leverage_cost_eur = notional_eur * risk.EVAL_LEVERAGE_DAILY_RATE * days_held
        result_eur -= (trade_fee_eur + leverage_cost_eur)

    with db.session() as conn:
        conn.execute(
            """UPDATE journal_entries
               SET exit_price = ?, exit_time = ?, result_eur = ?, result_pct = ?
               WHERE id = ? AND user_id = ?""",
            (exit_price, exit_time, result_eur, result_pct, entry_id, user_id),
        )
        if not entry["is_practice"] and entry["evaluation_id"] is None:
            conn.execute(
                "UPDATE users SET portfolio_eur = portfolio_eur + ? WHERE id = ?",
                (result_eur, user_id),
            )
    return result_eur, bool(entry["is_practice"]), entry["evaluation_id"]
```

Vervang door:

```python
def close_journal_trade(entry_id: int, user_id: int, exit_price: float, exit_time: str) -> tuple[float, bool]:
    """Sluit de trade af en geeft (result_pct, is_practice) terug:
    is_practice bepaalt of dit voor de winst-confetti telt. result_pct is
    de kale procentuele koersbeweging tussen entry en exit, richting-
    bewust — geen enkele geld-berekening meer sinds evaluatie en generieke
    positiegrootte weg zijn (zie de spec, addendum)."""
    entry = get_journal_entry(entry_id, user_id)
    if not entry or entry["entry_price"] is None or entry["status"] == "genegeerd":
        raise ValueError("kan alleen sluiten als er een entry prijs is ingevuld en de trade niet genegeerd is")

    entry_price = entry["entry_price"]
    direction = entry["direction"].lower()

    if direction == "long":
        result_pct = (exit_price - entry_price) / entry_price * 100
    else:
        result_pct = (entry_price - exit_price) / entry_price * 100

    with db.session() as conn:
        conn.execute(
            """UPDATE journal_entries
               SET exit_price = ?, exit_time = ?, result_pct = ?
               WHERE id = ? AND user_id = ?""",
            (exit_price, exit_time, result_pct, entry_id, user_id),
        )
    return result_pct, bool(entry["is_practice"])
```

- [ ] **Step 2: Caller in `web/main.py` aanpassen**

Zoek de `close_journal`-route. De huidige regel:

```python
        result_eur, is_practice, evaluation_id = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
```

(Taak 3 heeft hier al het `if evaluation_id:`-blok ná deze regel
verwijderd, dus deze regel staat er nog op zichzelf.) Vervang door:

```python
        result_pct, is_practice = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
```

Zoek in dezelfde route de regel die `won` bepaalt (waarschijnlijk
`won = (not is_practice) and result_eur > 0`, gebruikt voor de
winst-confetti-redirect-parameter `closed_win=1`) en vervang
`result_eur > 0` door `result_pct > 0`.

- [ ] **Step 3: `/api/system_status` opschonen**

Huidige code (`web/main.py:1099-1147`, volledige route):

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
        daily_used_pct = max(0.0, (1 - daily_remaining / daily_budget_total) * 100) if daily_budget_total else 0.0
        drawdown_used_pct = max(0.0, (1 - drawdown_remaining / drawdown_total) * 100) if drawdown_total else 0.0
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
        "unread_notifications": repo.count_unread_notifications(user["id"]),
        "week_result_eur": repo.week_result_eur(user["id"]),
        "volatility_ratio": repo.largest_open_position_volatility(user["id"]),
        "last_signal": last_signal,
        "risk_pct": risk_pct,
    }
```

Vervang door (verwijdert `risk_pct` volledig — geen evaluatie en geen
generieke portfolio-sizing meer, dus er is geen betekenisvol
"risicopercentage" meer om te tonen; `week_result_eur` wordt in Taak 8
hernoemd naar een percentage-variant, hier alvast de key aanpassen zodat
deze taak en Taak 8 niet dezelfde regel dubbel bewerken — gebruik
`week_result_pct` als key, ook al bestaat `repo.week_result_pct` pas na
Taak 8: dat is geen probleem zolang je in DEZE taak `repo.week_result_eur`
laat staan onder de nieuwe key, en Taak 8 hernoemt de functie zelf):

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

    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
        "unread_notifications": repo.count_unread_notifications(user["id"]),
        "week_result_pct": repo.week_result_eur(user["id"]),
        "volatility_ratio": repo.largest_open_position_volatility(user["id"]),
        "last_signal": last_signal,
    }
```

(Ja, dit roept tijdelijk nog `repo.week_result_eur` aan onder de nieuwe
`week_result_pct`-key — dat is een bewuste, kortstondige inconsistentie
die Taak 8 oplost door `week_result_eur` zelf om te bouwen naar een
percentage-berekening. Zonder deze tussenstap zou Taak 5 op Taak 8 moeten
wachten, wat de taken onnodig aan elkaar knoopt.)

Zoek en pas ELKE plek aan die `risk_pct` uit `/api/system_status`
consumeert — grep in `web/static/*.js` en `web/templates/*.html` op
`risk_pct` (buiten `web/main.py` zelf, waar je 'm net verwijderd hebt) en
verwijder de bijbehorende UI-weergave (waarschijnlijk een stukje van de
statuspopover in `base.html`). Geef in je rapport exact aan welke
regel(s) je daar hebt aangepast.

- [ ] **Step 4: Importcheck + throwaway-scriptverificatie**

```bash
cd /home/user/Trade && python3 -c "import app.repo; import web.main; print('import OK')"
```

```bash
cd /home/user/Trade
rm -f /tmp/scratch_close_journal.db
DATABASE_PATH=/tmp/scratch_close_journal.db python3 -c "
from app import db, repo
db.init_db()
from app.security import hash_password
uid = repo.create_user(username='t', password_hash=hash_password('testpass123'), portfolio_eur=1000.0, risk_percent=1.0)
signal_id = repo.insert_signal({
    'coin': 'BTC', 'direction': 'long', 'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 50000.0, 'stop_loss': 49000.0, 'take_profit': 52000.0,
    'technical_confirmed': 1, 'confidence': 'hoog', 'hard_gates_ok': 1, 'reason': 'test',
})
entry_id = repo.create_journal_entry(signal_id, uid, None)
repo.update_journal_status(entry_id, uid, 'genomen', entry_price=50000.0)
result_pct, is_practice = repo.close_journal_trade(entry_id, uid, 51000.0, '2026-09-30T12:00:00')
assert abs(result_pct - 2.0) < 0.01, f'verwacht ~2.0%, kreeg {result_pct}'
assert is_practice is False
entry = repo.get_journal_entry(entry_id, uid)
assert entry['result_eur'] is None, f'result_eur had niet meer geschreven moeten worden, kreeg {entry[\"result_eur\"]}'
user_after = repo.get_user(uid)
assert user_after['portfolio_eur'] == 1000.0, f'portfolio_eur had niet meer bijgewerkt moeten worden, kreeg {user_after[\"portfolio_eur\"]}'
print('close_journal_trade OK: result_pct =', result_pct)
"
rm -f /tmp/scratch_close_journal.db
```

- [ ] **Step 5: Commit**

```bash
cd /home/user/Trade
git add app/repo.py web/main.py
git commit -m "$(cat <<'EOF'
close_journal_trade vereenvoudigd + /api/system_status opgeschoond

close_journal_trade berekent alleen nog result_pct (kale procentuele
koersbeweging), geen result_eur meer (was toch al altijd 0 zodra risk_eur
altijd 0 is) en geen portfolio_eur-bijschrijving meer. Signatuur
vereenvoudigd naar (result_pct, is_practice). /api/system_status's
evaluatie/portfolio-risk_pct-berekening weg (geen betekenisvol
risicopercentage meer zonder evaluatie of generieke sizing).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 6: Account-pagina — portfolio-blok en verborgen velden weg

**Files:**
- Modify: `web/templates/account.html`
- Modify: `web/main.py` (`POST /settings/portfolio`)
- Modify: `app/repo.py` (`update_user_settings`)

**Interfaces:**
- Consumes: Taak 1 (redirect-doel is al gefixt naar `/account`).
- Produces: `repo.update_user_settings(user_id, quiet_hours_start,
  quiet_hours_end)` (was `(user_id, portfolio_eur, risk_percent,
  quiet_hours_start, quiet_hours_end)`) — 2 parameters minder.

- [ ] **Step 1: Portfolio-saldo-blok verwijderen uit `account.html`**

Huidige code (`web/templates/account.html:198-209`):

```html
<div class="card" id="portfolio-card">
  <h3>...Portfolio ({{ user.username }})</h3>
  {% if user.portfolio_eur %}
  <p class="big">€{{ "%.2f"|format(user.portfolio_eur) }}</p>
  {% if total_realized_eur != 0 %}
  <p class="muted">
    gestart op €{{ "%.2f"|format(starting_portfolio_eur) }}, sinds dan
    <span class="{{ 'pos' if total_realized_eur >= 0 else 'neg' }}">{{ "+" if total_realized_eur >= 0 else "" }}€{{ "%.2f"|format(total_realized_eur) }} ({{ "+" if portfolio_change_pct >= 0 else "" }}{{ "%.1f"|format(portfolio_change_pct) }}%)</span>
  </p>
  {% endif %}
  <p class="muted levels-hint">Past zich automatisch aan na elke gesloten trade, winst of verlies.</p>
  {% endif %}
```

Verwijder dit hele `<div class="card" id="portfolio-card">`-blok
(inclusief de afsluitende `</div>` — lees de exacte huidige inhoud zelf op
om het precieze eindpunt te vinden, dit voorbeeld toont het begin).

- [ ] **Step 2: Verborgen velden verwijderen, formulier vereenvoudigen**

Huidige code (`web/templates/account.html:210-226`):

```html
    <!-- Taak 11: het formulier om portfolio_eur/risk_percent zelf in te
         stellen is hier verwijderd (geen generieke portfolio-sizing meer
         buiten een evaluatie om), maar allebei blijven als verborgen velden
         meegestuurd zodat dit formulier de stille-uren-instelling (die wel
         nog een echte, aparte functie is) kan blijven opslaan zonder de
         backend-route aan te passen. -->
    <form action="/settings/portfolio" method="post" class="inline-form">
      <input type="hidden" name="portfolio_eur" value="{{ user.portfolio_eur }}">
      <input type="hidden" name="risk_percent" value="{{ user.risk_percent }}">
      <label>Stille uren van
        <input type="time" name="quiet_hours_start" value="{{ user.quiet_hours_start or '' }}">
      </label>
      <label>tot
        <input type="time" name="quiet_hours_end" value="{{ user.quiet_hours_end or '' }}">
      </label>
      <button type="submit">Opslaan</button>
    </form>
```

Vervang door:

```html
    <form action="/settings/portfolio" method="post" class="inline-form">
      <label>Stille uren van
        <input type="time" name="quiet_hours_start" value="{{ user.quiet_hours_start or '' }}">
      </label>
      <label>tot
        <input type="time" name="quiet_hours_end" value="{{ user.quiet_hours_end or '' }}">
      </label>
      <button type="submit">Opslaan</button>
    </form>
```

- [ ] **Step 3: `POST /settings/portfolio` en `update_user_settings` vereenvoudigen**

Huidige code (`web/main.py`, na Taak 1's redirect-fix):

```python
@app.post("/settings/portfolio")
async def update_settings(
    portfolio_eur: float = Form(...),
    risk_percent: float = Form(...),
    quiet_hours_start: str = Form(""),
    quiet_hours_end: str = Form(""),
    user: dict = Depends(require_login),
):
    start = quiet_hours_start.strip() or None
    end = quiet_hours_end.strip() or None
    if not (start and end):
        start, end = None, None
    repo.update_user_settings(user["id"], portfolio_eur, risk_percent, start, end)
    return RedirectResponse(url="/account", status_code=303)
```

Vervang door:

```python
@app.post("/settings/portfolio")
async def update_settings(
    quiet_hours_start: str = Form(""),
    quiet_hours_end: str = Form(""),
    user: dict = Depends(require_login),
):
    start = quiet_hours_start.strip() or None
    end = quiet_hours_end.strip() or None
    if not (start and end):
        start, end = None, None
    repo.update_user_settings(user["id"], start, end)
    return RedirectResponse(url="/account", status_code=303)
```

Zoek de huidige `update_user_settings`-functie in `app/repo.py` (rond
regel 923-937 in de huidige staat) — lees de exacte huidige inhoud op en
verwijder de `portfolio_eur`/`risk_percent`-parameters en hun
`UPDATE users SET portfolio_eur = ?, risk_percent = ?, ...`-kolommen uit de
SQL, zodat de functie alleen nog `quiet_hours_start`/`quiet_hours_end`
bijwerkt.

- [ ] **Step 4: `account_page`-route: `starting_portfolio_eur`/`total_realized_eur`/`portfolio_change_pct` weg**

In de `account_page`-route (`web/main.py`), verwijder de berekening en de
context-dict-keys voor `starting_portfolio_eur`, `total_realized_eur`,
`portfolio_change_pct` — deze voedden alleen het net verwijderde
portfolio-blok. Laat `cumulative = repo.cumulative_result_series(user["id"])`
staan (die wordt in Taak 8 zelf omgebouwd, niet hier, en `cumulative`
zelf blijft nodig voor de grafiek).

Verwijder ook `onboarding["portfolio_set"]` als die in deze route staat
(bevestig eerst met een grep of dat hier aanwezig is — de eerdere
inventarisatie zag dit veld alleen in de nu-al-verwijderde `/dashboard`-
route, dus mogelijk is er hier niets te doen; controleer het zelf).

- [ ] **Step 5: Importcheck + Playwright-verificatie**

```bash
cd /home/user/Trade && python3 -c "import web.main; import app.repo; print('import OK')"
```

Bezoek `/account` tegen een scratch-database, bevestig dat er geen
portfolio-kaart meer staat, en dat het stille-uren-formulier nog steeds
opslaat (vul een tijd in, verstuur, herlaad, bevestig dat de waarde
behouden blijft).

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/templates/account.html web/main.py app/repo.py
git commit -m "$(cat <<'EOF'
Account-pagina: portfolio-saldo-blok en verborgen sizing-velden weg

Het "Taak 11"-restant (verborgen portfolio_eur/risk_percent-velden,
alleen nog nodig om het stille-uren-formulier te laten werken) is nu
overbodig: risk_percent had sinds evaluatie weg is geen enkele functie
meer, portfolio_eur wordt sinds Taak 5 niet meer bijgewerkt. Beide velden
en de portfolio-kaart weg uit account.html, /settings/portfolio en
repo.update_user_settings vereenvoudigd naar alleen stille uren.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 7: Journaal-tabel en CSV-export — geld-kolommen weg

**Files:**
- Modify: `web/templates/account.html` (journaaltabel)
- Modify: `web/templates/_macros.html` (`open_trade_body`'s
  positiegrootte-cel)
- Modify: `web/main.py` (`/export/logboek.csv`, `_position_size`-docstring)

**Interfaces:**
- Consumes: Taak 5 (`result_eur` wordt niet meer geschreven).
- Produces: geen.

- [ ] **Step 1: Journaaltabel in `account.html` aanpassen**

Huidige code (`web/templates/account.html`, regel 427-441 in de huidige
staat, binnen de `{% for e in entries %}`-loop):

```html
        <td class="num">
          {{ "%.4f"|format(e.price) if e.price else "-" }}
          {% if e.position_size %}<span class="muted entry-size">{{ "%.6f"|format(e.position_size) }} {{ e.coin }}</span>{% endif %}
        </td>
        <td class="num sltp-cell">
          <span class="neg">{{ "%.4f"|format(e.stop_loss) if e.stop_loss else "-" }}</span>
          <span class="pos">{{ "%.4f"|format(e.take_profit) if e.take_profit else "-" }}</span>
        </td>
        <td><span class="badge badge-status">{{ e.status }}</span></td>
        <td class="num">
          {% if e.result_eur is not none %}
            <span class="{{ 'pos' if e.result_eur >= 0 else 'neg' }}">
              €{{ "%.2f"|format(e.result_eur) }}{% if e.result_pct_of_risk is not none %} ({{ "%.1f"|format(e.result_pct_of_risk) }}%){% endif %}
            </span>
          {% else %}-{% endif %}
        </td>
```

Vervang door (positiegrootte weg uit de Entry-cel, Resultaat-cel toont
alleen `result_pct`):

```html
        <td class="num">
          {{ "%.4f"|format(e.price) if e.price else "-" }}
        </td>
        <td class="num sltp-cell">
          <span class="neg">{{ "%.4f"|format(e.stop_loss) if e.stop_loss else "-" }}</span>
          <span class="pos">{{ "%.4f"|format(e.take_profit) if e.take_profit else "-" }}</span>
        </td>
        <td><span class="badge badge-status">{{ e.status }}</span></td>
        <td class="num">
          {% if e.result_pct is not none %}
            <span class="{{ 'pos' if e.result_pct >= 0 else 'neg' }}">{{ "%.1f"|format(e.result_pct) }}%</span>
          {% else %}-{% endif %}
        </td>
```

Zoek in dezelfde template de deel-knop (regel 462-464 in de huidige
staat):

```html
          {% elif e.result_eur is not none %}
            <button type="button" class="button-link share-btn"
                    data-share="{{ e.coin }} {{ e.direction|upper }} — entry {{ '%.4f'|format(e.entry_price) }} naar exit {{ '%.4f'|format(e.exit_price) }} — {{ '%+.2f'|format(e.result_eur) }} euro{% if e.result_pct_of_risk is not none %} ({{ '%+.1f'|format(e.result_pct_of_risk) }}%){% endif %} — via HesPulse" title="Deel dit resultaat">Delen</button>
```

Vervang door:

```html
          {% elif e.result_pct is not none %}
            <button type="button" class="button-link share-btn"
                    data-share="{{ e.coin }} {{ e.direction|upper }} — entry {{ '%.4f'|format(e.entry_price) }} naar exit {{ '%.4f'|format(e.exit_price) }} — {{ '%+.1f'|format(e.result_pct) }}% — via HesPulse" title="Deel dit resultaat">Delen</button>
```

- [ ] **Step 2: `_macros.html`'s `open_trade_body` — positiegrootte-cel weg**

Huidige code (regel 90-96 in de huidige staat):

```html
<div class="data-grid">
  <div class="cell"><div class="k">Entry</div><div class="v">{{ "%.4f"|format(e.entry_price) }}</div></div>
  <div class="cell"><div class="k">Nu</div><div class="v" data-price="{{ e.id }}">{{ "%.4f"|format(e.current_price) if e.current_price else "-" }}<span class="price-direction" data-price-direction="{{ e.id }}" aria-hidden="true"></span></div></div>
  <div class="cell"><div class="k">SL</div><div class="v neg">{{ "%.4f"|format(e.stop_loss) if e.stop_loss else "-" }}</div></div>
  <div class="cell"><div class="k">TP</div><div class="v pos">{{ "%.4f"|format(e.take_profit) if e.take_profit else "-" }}</div></div>
  <div class="cell"><div class="k">Grootte</div><div class="v">{{ "%.6f"|format(e.position_size) ~ " " ~ e.coin if e.position_size else "-" }}</div></div>
</div>
```

Vervang door (Grootte-cel weg, de andere 4 cellen ongewijzigd):

```html
<div class="data-grid">
  <div class="cell"><div class="k">Entry</div><div class="v">{{ "%.4f"|format(e.entry_price) }}</div></div>
  <div class="cell"><div class="k">Nu</div><div class="v" data-price="{{ e.id }}">{{ "%.4f"|format(e.current_price) if e.current_price else "-" }}<span class="price-direction" data-price-direction="{{ e.id }}" aria-hidden="true"></span></div></div>
  <div class="cell"><div class="k">SL</div><div class="v neg">{{ "%.4f"|format(e.stop_loss) if e.stop_loss else "-" }}</div></div>
  <div class="cell"><div class="k">TP</div><div class="v pos">{{ "%.4f"|format(e.take_profit) if e.take_profit else "-" }}</div></div>
</div>
```

Verwijder ook, verderop in dezelfde macro, het "Grootte ({{ e.coin }})"
-invoerveld (regel 119-123 in de huidige staat):

```html
    <label>Grootte ({{ e.coin }})
      <input type="number" step="any" name="position_size"
             value="{{ '%.6f'|format(e.position_size_override) if e.position_size_override is not none else '' }}"
             placeholder="{{ '%.6f'|format(e.position_size) if e.position_size else 'auto' }}">
    </label>
```

(Laat de backend-route `/journal/{id}/levels` en
`repo.update_journal_position_size`/`position_size_override`-kolom met
rust — dit is puur het verwijderen van het invoerveld uit de UI, aanpak A
laat de onderliggende opslag-mogelijkheid bestaan.)

- [ ] **Step 3: CSV-export aanpassen**

Huidige volledige code (`web/main.py:1186-1216`):

```python
@app.get("/export/logboek.csv")
async def export_journal_csv(user: dict = Depends(require_login)):
    entries = repo.list_journal(user["id"], status=None, limit=100000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "tijdstip", "coin", "richting", "vertrouwen", "technisch_bevestigd",
        "prijs", "stop_loss", "take_profit", "risicobedrag_eur", "status",
        "entry_price", "exit_price", "exit_time", "resultaat_eur", "resultaat_pct", "notitie",
        "evaluatie_gekoppeld",
    ])
    for e in entries:
        writer.writerow([
            e["created_at"], e["coin"], e["direction"], e["confidence"],
            "ja" if e["technical_confirmed"] else "nee",
            e["price"], e["stop_loss"], e["take_profit"], e["risk_eur"], e["status"],
            e["entry_price"], e["exit_price"], e["exit_time"], e["result_eur"], e["result_pct"],
            e["note"] or "",
            "ja" if e.get("evaluation_id") else "nee",
        ])

    filename = f"hespulse-logboek-{user['username']}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Vervang door (kolommen `risicobedrag_eur`, `resultaat_eur`,
`evaluatie_gekoppeld` weg):

```python
@app.get("/export/logboek.csv")
async def export_journal_csv(user: dict = Depends(require_login)):
    entries = repo.list_journal(user["id"], status=None, limit=100000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "tijdstip", "coin", "richting", "vertrouwen", "technisch_bevestigd",
        "prijs", "stop_loss", "take_profit", "status",
        "entry_price", "exit_price", "exit_time", "resultaat_pct", "notitie",
    ])
    for e in entries:
        writer.writerow([
            e["created_at"], e["coin"], e["direction"], e["confidence"],
            "ja" if e["technical_confirmed"] else "nee",
            e["price"], e["stop_loss"], e["take_profit"], e["status"],
            e["entry_price"], e["exit_price"], e["exit_time"], e["result_pct"],
            e["note"] or "",
        ])

    filename = f"hespulse-logboek-{user['username']}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 4: `_position_size`-docstring opschonen**

Huidige code (`web/main.py:685-698`):

```python
def _position_size(entry: dict) -> Optional[float]:
    """Eigen positiegrootte als die is ingevuld, anders de grootte waarmee de
    trade daadwerkelijk gesized is (journal_entries.position_size, bij het
    aanmaken opgeslagen inclusief de fee-/hefboomcorrectie van een
    evaluatie-trade). Alleen voor oude regels van vóór die kolom bestond
    valt dit terug op een herberekening — die trades kenden nog geen
    kostencorrectie, dus daar ís de kale berekening de juiste waarde."""
    if entry.get("position_size_override") is not None:
        return entry["position_size_override"]
    if entry.get("position_size") is not None:
        return entry["position_size"]
    if entry["risk_eur"] and entry["price"] and entry["stop_loss"]:
        return risk.compute_position_size(entry["risk_eur"], entry["price"], entry["stop_loss"])
    return None
```

Werk alleen de docstring bij (functie-logica blijft ongewijzigd — deze
helper blijft nodig voor historische data, zie Taak 4):

```python
def _position_size(entry: dict) -> Optional[float]:
    """Eigen positiegrootte als die is ingevuld, anders de grootte waarmee de
    trade destijds gesized is (journal_entries.position_size, alleen nog
    gevuld op oude regels van vóór evaluatie/generieke sizing weg waren).
    Voor de oudste regels van vóór die kolom bestond valt dit terug op een
    herberekening. Puur historische weergave — nieuwe journaalregels
    krijgen nooit meer een risk_eur/position_size."""
    if entry.get("position_size_override") is not None:
        return entry["position_size_override"]
    if entry.get("position_size") is not None:
        return entry["position_size"]
    if entry["risk_eur"] and entry["price"] and entry["stop_loss"]:
        return risk.compute_position_size(entry["risk_eur"], entry["price"], entry["stop_loss"])
    return None
```

- [ ] **Step 5: Importcheck + Playwright + CSV-verificatie**

```bash
cd /home/user/Trade && python3 -c "import web.main; print('import OK')"
```

Bezoek `/account` tegen een scratch-database met minstens één gesloten
trade (gebruik het scratch-script uit Taak 5 als basis, voeg
`repo.close_journal_trade(...)` toe), bevestig dat de Resultaat-kolom een
percentage toont, geen euro-teken. Download `/export/logboek.csv` en
bevestig met een korte Python-check dat de header exact de nieuwe,
kortere kolommenlijst bevat.

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/templates/account.html web/templates/_macros.html web/main.py
git commit -m "$(cat <<'EOF'
Journaaltabel + CSV-export: risk_eur/position_size/result_eur weg

result_pct wordt de enige resultaatmaat in de journaaltabel (account.html)
en de CSV-export. Positiegrootte-weergave (Entry-cel, open_trade_body's
Grootte-cel en -invoerveld) weg — risk_eur/position_size worden toch
nooit meer gevuld voor nieuwe trades sinds evaluatie en de generieke
sizing weg zijn.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 8: `app/repo.py` statistiek-laag — euro naar percentage

**Files:**
- Modify: `app/repo.py`

**Interfaces:**
- Consumes: Taak 5 (result_eur wordt niet meer geschreven, dus elke
  functie die er nu op leunt zou anders altijd 0/None teruggeven).
- Produces: `week_result_pct` (was `week_result_eur`, zelfde functienaam-
  conventie, hernoem de FUNCTIE zelf naar `week_result_pct`),
  `cumulative_result_series` blijft heten zoals hij heet maar geeft
  `{"time": ..., "cumulative_pct": ...}` terug (was `cumulative_eur`),
  `daily_results` blijft heten zoals hij heet maar somt `result_pct` i.p.v.
  `result_eur`. Taak 9 consumeert deze nieuwe namen/velden.

**Dit is een grote, mechanische taak over veel functies.** Elke functie
volgt hetzelfde patroon: waar nu `SUM(result_eur)`/`AVG(result_eur)`/
`result_eur`-vergelijkingen staan, wordt dat `result_pct`. Twee volledig
uitgewerkte voorbeelden hieronder, daarna een checklist van de resterende
functies met dezelfde soort wijziging.

- [ ] **Step 1: Inventariseer**

```bash
cd /home/user/Trade
grep -n "result_eur" app/repo.py > /tmp/repo_result_eur_lines.txt
wc -l /tmp/repo_result_eur_lines.txt
```

Dit is je volledige, exacte lijst. Ga hem regel voor regel langs. Elke
functie die je hieronder NIET expliciet genoemd ziet als "blijft
ongewijzigd" moet je zelf beoordelen — pas toe wat in de twee voorbeelden
hieronder staat.

**Blijft ongewijzigd** (evaluatie-specifiek, al verwijderd in Taak 3/4 —
als je hier toch nog een treffer ziet is er iets gemist in een eerdere
taak, meld dat als bevinding): geen — na Taak 4 hoort hier niets
evaluatie-specifieks meer te staan.

- [ ] **Step 2: Volledig uitgewerkt voorbeeld 1 — `week_result_eur`**

Huidige code (regel 2074-2089 in de huidige staat):

```python
def week_result_eur(user_id: int) -> Optional[float]:
    """Resultaat van echte gesloten trades in de laatste 7 dagen. None als
    er niets gesloten is deze week (niet hetzelfde als 0: 0 is exact
    quitte, None is 'geen data om iets over te zeggen'). Gebruikt om de
    ambient achtergrond een beetje mee te laten kleuren met hoe de week
    gaat, geen harde metric."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT SUM(je.result_eur) AS total, COUNT(*) AS n
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND je.exit_time >= ?""",
            (user_id, week_ago),
        ).fetchone()
        return round(row["total"], 2) if row["n"] else None
```

Vervang door (functienaam hernoemd, `SUM(result_eur)` → `AVG(result_pct)` —
gemiddeld percentage is het juiste equivalent van "hoe gaat de week", niet
een som van percentages over meerdere trades, dat zou bij 3 trades van
+5%/+5%/+5% een misleidende "+15%" tonen in plaats van "+5% gemiddeld"):

```python
def week_result_pct(user_id: int) -> Optional[float]:
    """Gemiddeld resultaatpercentage van echte gesloten trades in de
    laatste 7 dagen. None als er niets gesloten is deze week (niet
    hetzelfde als 0: 0 is exact quitte, None is 'geen data om iets over te
    zeggen'). Gebruikt om de ambient achtergrond een beetje mee te laten
    kleuren met hoe de week gaat, geen harde metric."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT AVG(je.result_pct) AS avg_pct, COUNT(*) AS n
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND je.exit_time >= ?""",
            (user_id, week_ago),
        ).fetchone()
        return round(row["avg_pct"], 2) if row["n"] else None
```

Pas de aanroeper in `web/main.py` aan (Taak 5's `/api/system_status`
riep `repo.week_result_eur(user["id"])` onder de `week_result_pct`-key aan
— nu de functie zelf ook `week_result_pct` heet, wordt die regel):

```python
        "week_result_pct": repo.week_result_pct(user["id"]),
```

- [ ] **Step 3: Volledig uitgewerkt voorbeeld 2 — `cumulative_result_series` en `daily_results`**

Huidige code (`cumulative_result_series`, regel 2092-2107):

```python
def cumulative_result_series(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL
               ORDER BY je.exit_time ASC""",
            (user_id,),
        ).fetchall()
    series = []
    running = 0.0
    for row in rows:
        running += row["result_eur"] or 0.0
        series.append({"time": row["exit_time"], "cumulative_eur": round(running, 2)})
    return series
```

Vervang door (dit voedt een CUMULATIEVE grafiek — hier is een lopende SOM
van percentages, niet een gemiddelde, wel het juiste equivalent: elke
trade draagt zijn eigen % bij aan een oplopende lijn, dezelfde grafiekvorm
als voorheen maar in %-eenheden in plaats van €):

```python
def cumulative_result_series(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_pct AS result_pct
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL
               ORDER BY je.exit_time ASC""",
            (user_id,),
        ).fetchall()
    series = []
    running = 0.0
    for row in rows:
        running += row["result_pct"] or 0.0
        series.append({"time": row["exit_time"], "cumulative_pct": round(running, 2)})
    return series
```

Huidige code (`daily_results`, regel 2110-2130):

```python
def daily_results(user_id: int, days: int = 126) -> dict:
    """Resultaat per dag (som van result_eur van echte, gesloten trades) van
    de laatste `days` dagen, als {"YYYY-MM-DD": bedrag}. Basis voor de
    trade-kalender heatmap op het dashboard: een dag zonder gesloten
    trades komt simpelweg niet in dit dict voor."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND je.exit_time >= ?""",
            (user_id, cutoff),
        ).fetchall()
    by_day: dict[str, float] = {}
    for row in rows:
        if not row["exit_time"]:
            continue
        day = row["exit_time"][:10]
        by_day[day] = by_day.get(day, 0.0) + (row["result_eur"] or 0.0)
    return by_day
```

Vervang door (heatmap kleurt per dag — som van percentages van die dag is
hier prima, matcht de bestaande "som per dag"-vorm 1-op-1, alleen de
eenheid verandert):

```python
def daily_results(user_id: int, days: int = 126) -> dict:
    """Resultaatpercentage per dag (som van result_pct van echte, gesloten
    trades) van de laatste `days` dagen, als {"YYYY-MM-DD": percentage}.
    Basis voor de trade-kalender heatmap: een dag zonder gesloten trades
    komt simpelweg niet in dit dict voor."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_pct AS result_pct
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND je.exit_time >= ?""",
            (user_id, cutoff),
        ).fetchall()
    by_day: dict[str, float] = {}
    for row in rows:
        if not row["exit_time"]:
            continue
        day = row["exit_time"][:10]
        by_day[day] = by_day.get(day, 0.0) + (row["result_pct"] or 0.0)
    return by_day
```

- [ ] **Step 4: Resterende functies — pas dezelfde regel toe**

Ga elke overige functie in je Step 1-inventaris langs en pas toe: elke
`SUM`/`AVG`/vergelijking op `result_eur` wordt dezelfde bewerking op
`result_pct`; elk veld met `_eur` in de naam dat een resultaatbedrag
representeert wordt `_pct`; elke `€`-formattering in een docstring/
commentaar wordt bijgewerkt. Voor functies die zowel een `_eur`- als een
al-bestaand `_pct`-veld berekenen (zoals hieronder bij `winrate_stats`):
het bestaande `_pct`-veld is vaak zelf óók `result_eur / risk_eur * 100`
(een risicogewogen R-multiple-percentage, NIET hetzelfde als het kale
`journal_entries.result_pct`) — vervang dat door een directe
`AVG(result_pct)`/gebruik van `journal_entries.result_pct`, niet door de
oude formule met `result_eur` te laten staan.

Functies om te controleren en aan te passen (functienamen zoals ze nu
heten — zoek elk zelf op met `grep -n "^def <naam>" app/repo.py` voor de
exacte huidige inhoud):

- `winrate_stats` (rond regel 1895) — heeft AL een `avg_result_pct`-veld,
  maar berekend als `result_eur / risk_eur * 100` (regel 1926-1927) — dit
  wordt altijd 0. Vervang door een directe `AVG(je.result_pct)` in de SQL
  (of een Python-gemiddelde van `result_pct`-waardes), en verwijder het nu
  zinloze `avg_result_eur`-veld uit de return-dict.
- De tweede, vergelijkbare winrate-functie rond regel 2000-2030 (zelfde
  patroon: `avg_result_eur`/`avg_result_pct` via `result_eur`/`risk_eur`)
  — zelfde fix.
- De reason-bucketed win-check rond regel 2046-2061 — gebruikt alleen
  `(result_eur or 0) > 0` als winst-check, vervang door
  `(result_pct or 0) > 0`.
- De twee functies rond regel 2151 en 2172 die controleren of het laatste
  resultaat negatief was (`row["result_eur"] < 0`) — vervang door
  `row["result_pct"] < 0`.
- `period_stats` (rond regel 2189) en `period_stats_auto_scan` (rond regel
  2234) — gebruikt door `app/periodic_summary.py` (zie Taak 10, NIET hier
  aanpassen aan de aanroepende kant, alleen deze repo.py-functies zelf).
  `total_result_eur`/`best`/`worst` (gebaseerd op `result_eur`) worden
  `total_result_pct`/`best`/`worst` (gebaseerd op `result_pct`, som i.p.v.
  gemiddelde is hier consistent met wat "totaal resultaat deze week"
  betekent).
- `coin_stats` (rond regel 2263) — `avg_result_eur` per coin wordt
  `avg_result_pct`, gebaseerd op `result_pct` i.p.v. `result_eur`.

Laat de evaluatie-eigen functies met rust — die zijn al weg in Taak 4;
als je hier nog `list_evaluation_daily_results`/
`list_evaluation_balance_curve`/`list_evaluation_trade_context` tegenkomt,
is er iets misgegaan in Taak 4, niet iets om hier op te lossen (meld het
als bevinding, ga niet zelf Taak 4 overdoen binnen deze taak).

- [ ] **Step 5: Grep-verificatie**

```bash
cd /home/user/Trade
grep -n "result_eur" app/repo.py
```

Expected: lege output (of hooguit een treffer in een comment die uitlegt
WAAROM iets nu `result_pct` heet in plaats van `result_eur` — geen enkele
functionele `result_eur`-referentie meer).

- [ ] **Step 6: Importcheck + throwaway-scriptverificatie**

```bash
cd /home/user/Trade && python3 -c "import app.repo; import web.main; print('import OK')"
```

```bash
cd /home/user/Trade
rm -f /tmp/scratch_stats_pct.db
DATABASE_PATH=/tmp/scratch_stats_pct.db python3 -c "
from app import db, repo
db.init_db()
from app.security import hash_password
uid = repo.create_user(username='t', password_hash=hash_password('testpass123'), portfolio_eur=1000.0, risk_percent=1.0)
signal_id = repo.insert_signal({
    'coin': 'BTC', 'direction': 'long', 'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 50000.0, 'stop_loss': 49000.0, 'take_profit': 52000.0,
    'technical_confirmed': 1, 'confidence': 'hoog', 'hard_gates_ok': 1, 'reason': 'test',
})
entry_id = repo.create_journal_entry(signal_id, uid, None)
repo.update_journal_status(entry_id, uid, 'genomen', entry_price=50000.0)
repo.close_journal_trade(entry_id, uid, 51000.0, '2026-09-30T12:00:00')
week_pct = repo.week_result_pct(uid)
assert week_pct is not None and abs(week_pct - 2.0) < 0.01, f'verwacht ~2.0, kreeg {week_pct}'
series = repo.cumulative_result_series(uid)
assert series[-1]['cumulative_pct'] is not None
daily = repo.daily_results(uid)
assert any(abs(v - 2.0) < 0.01 for v in daily.values())
print('statistiek-laag OK:', week_pct, series[-1], daily)
"
rm -f /tmp/scratch_stats_pct.db
```

- [ ] **Step 7: Commit**

```bash
cd /home/user/Trade
git add app/repo.py web/main.py
git commit -m "$(cat <<'EOF'
Statistiek-laag: result_eur overal naar result_pct

Elke functie in repo.py die SUM/AVG(result_eur) deed (week_result_eur →
week_result_pct, cumulative_result_series, daily_results, winrate_stats,
period_stats, coin_stats, en de overige win/verlies-checks) draait nu op
result_pct — zonder deze omzetting zouden ze allemaal stil op 0/None
blijven hangen zodra risk_eur nooit meer gevuld wordt (zie het
spec-addendum). Waar een functie al een eigen "_pct"-veld had (bv.
winrate_stats' oude avg_result_pct, berekend als result_eur/risk_eur), was
dat zelf ook risk_eur-afhankelijk — vervangen door een directe
result_pct-berekening.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 9: Live PnL, ambient gloed, heatmap en cumulatieve grafiek — frontend

**Files:**
- Modify: `app/risk.py` (`compute_unrealized_pnl`)
- Modify: `web/main.py` (`_enrich_open_positions`, `/api/open_positions`)
- Modify: `web/templates/_macros.html` (`open_trade_body`'s PnL-regel)
- Modify: `web/static/dashboard.js` (PnL-weergave, tab-titel/favicon indien
  van toepassing)
- Modify: `web/templates/base.html` (`portfolioGlow`-aanroep, heatmap/
  cumulatieve-grafiek-rendering indien in dit bestand)
- Modify: `web/templates/account.html` (heatmap/cumulatieve-grafiek-
  rendering indien hier, niet in base.html)

**Interfaces:**
- Consumes: Taak 8 (`repo.week_result_pct`,
  `cumulative_result_series`'s `cumulative_pct`-veld, `daily_results`'
  percentage-waardes).
- Produces: `risk.compute_unrealized_pnl(direction, entry_price,
  current_price) -> Optional[float]` (was `(direction, entry_price,
  current_price, stop_loss, risk_eur) -> tuple[Optional[float],
  Optional[float]]`) — geeft nu alleen `pnl_pct` terug (de kale
  procentuele koersbeweging), geen `pnl_eur` meer.

- [ ] **Step 1: `compute_unrealized_pnl` herschrijven**

Huidige volledige code (`app/risk.py:367-394`):

```python
def compute_unrealized_pnl(
    direction: str, entry_price: float, current_price: float,
    stop_loss: Optional[float], risk_eur: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Nog niet gerealiseerd resultaat van een open trade tegen de actuele
    prijs, dezelfde rekenwijze als bij het sluiten van een trade: het
    risicobedrag geschaald met hoe ver de prijs al bewogen is ten opzichte
    van de afstand tot de stop loss. Geeft (pnl_eur, pnl_pct), allebei None
    als er geen bruikbare stop-afstand is.

    pnl_pct is hier het percentage van het risicobedrag, niet de rauwe
    koersbeweging: naast een risicogewogen eurobedrag is de kale procentuele
    prijsbeweging een ander getal dat er niets mee te maken heeft, en dus
    misleidend om ernaast te tonen alsof het bij elkaar hoort."""
    direction = direction.lower()
    if direction == "long":
        risk_per_unit = entry_price - stop_loss if stop_loss else None
        move = current_price - entry_price
    else:
        risk_per_unit = stop_loss - entry_price if stop_loss else None
        move = entry_price - current_price

    pnl_eur = None
    if risk_eur and risk_per_unit and risk_per_unit > 0:
        pnl_eur = risk_eur * (move / risk_per_unit)

    pnl_pct = (pnl_eur / risk_eur * 100) if pnl_eur is not None and risk_eur else None
    return pnl_eur, pnl_pct
```

Vervang door:

```python
def compute_unrealized_pnl(direction: str, entry_price: float, current_price: float) -> float:
    """Nog niet gerealiseerd resultaatpercentage van een open trade tegen de
    actuele prijs: de kale procentuele koersbeweging sinds entry,
    richting-bewust. Zelfde formule als journal_entries.result_pct bij het
    sluiten van een trade — geen risicogewogen eurobedrag meer, dat werd
    toch altijd 0 zodra risk_eur nooit meer gevuld wordt (zie het
    spec-addendum)."""
    direction = direction.lower()
    if direction == "long":
        return (current_price - entry_price) / entry_price * 100
    return (entry_price - current_price) / entry_price * 100
```

- [ ] **Step 2: `_enrich_open_positions` en `/api/open_positions` aanpassen**

Huidige code (`web/main.py:718-747`):

```python
async def _enrich_open_positions(entries: list[dict]) -> list[dict]:
    """Vult elke open positie (entry_price al ingevuld) aan met de actuele
    prijs en het nog niet gerealiseerde resultaat. Eén prijs-opvraag per
    coin, ook als er meerdere open trades op dezelfde coin staan. De
    exchange-aanroep loopt via to_thread, anders blokkeert die synchrone
    netwerkcall de hele server voor iedereen tegelijk."""
    price_cache: dict[str, Optional[float]] = {}
    for entry in entries:
        entry["position_size"] = _position_size(entry)
        entry["current_price"] = None
        entry["pnl_eur"] = None
        entry["pnl_pct"] = None
        entry["tension"], entry["tension_color"] = _compute_tension(None, entry["stop_loss"], entry["take_profit"])
        if entry["entry_price"] is None:
            continue
        if entry["coin"] not in price_cache:
            try:
                price_cache[entry["coin"]] = await asyncio.to_thread(exchange.fetch_last_price, entry["coin"])
            except Exception:
                price_cache[entry["coin"]] = None
        current_price = price_cache[entry["coin"]]
        if current_price is None:
            continue
        entry["current_price"] = current_price
        entry["pnl_eur"], entry["pnl_pct"] = risk.compute_unrealized_pnl(
            entry["direction"], entry["entry_price"], current_price,
            entry["stop_loss"], entry["risk_eur"],
        )
        entry["tension"], entry["tension_color"] = _compute_tension(current_price, entry["stop_loss"], entry["take_profit"])
    return entries
```

Vervang door (behoud `entry["position_size"] = _position_size(entry)` —
die blijft voor historische weergave, zie Taak 4/7 — verwijder alleen
`pnl_eur`, herbereken `pnl_pct` met de nieuwe, eenvoudigere signatuur):

```python
async def _enrich_open_positions(entries: list[dict]) -> list[dict]:
    """Vult elke open positie (entry_price al ingevuld) aan met de actuele
    prijs en het nog niet gerealiseerde resultaatpercentage. Eén
    prijs-opvraag per coin, ook als er meerdere open trades op dezelfde
    coin staan. De exchange-aanroep loopt via to_thread, anders blokkeert
    die synchrone netwerkcall de hele server voor iedereen tegelijk."""
    price_cache: dict[str, Optional[float]] = {}
    for entry in entries:
        entry["position_size"] = _position_size(entry)
        entry["current_price"] = None
        entry["pnl_pct"] = None
        entry["tension"], entry["tension_color"] = _compute_tension(None, entry["stop_loss"], entry["take_profit"])
        if entry["entry_price"] is None:
            continue
        if entry["coin"] not in price_cache:
            try:
                price_cache[entry["coin"]] = await asyncio.to_thread(exchange.fetch_last_price, entry["coin"])
            except Exception:
                price_cache[entry["coin"]] = None
        current_price = price_cache[entry["coin"]]
        if current_price is None:
            continue
        entry["current_price"] = current_price
        entry["pnl_pct"] = risk.compute_unrealized_pnl(entry["direction"], entry["entry_price"], current_price)
        entry["tension"], entry["tension_color"] = _compute_tension(current_price, entry["stop_loss"], entry["take_profit"])
    return entries
```

Huidige code (`web/main.py:1082-1097`, `/api/open_positions`):

```python
@app.get("/api/open_positions")
async def api_open_positions(user: dict = Depends(require_login)):
    """Ververst de live prijs en PnL van open posities, gebruikt door het
    dashboard om zonder volledige herlaad bij te werken."""
    entries = await _enrich_open_positions(repo.list_journal(user["id"], status="open"))
    return [
        {
            "id": e["id"], "current_price": e["current_price"],
            "pnl_eur": e["pnl_eur"], "pnl_pct": e["pnl_pct"],
            "is_practice": bool(e["is_practice"]),
            "direction": e["direction"], "stop_loss": e["stop_loss"], "take_profit": e["take_profit"],
            "tension": e["tension"], "tension_color": e["tension_color"],
        }
        for e in entries if e["entry_price"] is not None
    ]
```

Vervang door (`pnl_eur`-key weg uit de response):

```python
@app.get("/api/open_positions")
async def api_open_positions(user: dict = Depends(require_login)):
    """Ververst de live prijs en het resultaatpercentage van open posities,
    gebruikt door het dashboard om zonder volledige herlaad bij te
    werken."""
    entries = await _enrich_open_positions(repo.list_journal(user["id"], status="open"))
    return [
        {
            "id": e["id"], "current_price": e["current_price"],
            "pnl_pct": e["pnl_pct"],
            "is_practice": bool(e["is_practice"]),
            "direction": e["direction"], "stop_loss": e["stop_loss"], "take_profit": e["take_profit"],
            "tension": e["tension"], "tension_color": e["tension_color"],
        }
        for e in entries if e["entry_price"] is not None
    ]
```

- [ ] **Step 3: `open_trade_body`'s PnL-regel aanpassen**

Huidige code (`web/templates/_macros.html:102-105`):

```html
<p style="margin: 8px 0 0; font-size: 20px; font-weight: 700;" class="mono {{ 'pos' if (e.pnl_eur or 0) >= 0 else 'neg' }}" data-pnl="{{ e.id }}">
  {% if e.pnl_eur is not none %}€{{ "%.2f"|format(e.pnl_eur) }}{% else %}-{% endif %}
  <span style="font-size: 13px; font-weight: 500;" data-pnl-pct="{{ e.id }}">({{ "%.1f"|format(e.pnl_pct) if e.pnl_pct is not none else "-" }}%)</span>
</p>
```

Vervang door (toont alleen nog het percentage, geen euro-hoofdcijfer meer
— `data-pnl`/`data-pnl-pct` als attribuutnamen bewust ongewijzigd gelaten
zodat `dashboard.js`'s selectors blijven werken, alleen de INHOUD wordt
percentage):

```html
<p style="margin: 8px 0 0; font-size: 20px; font-weight: 700;" class="mono {{ 'pos' if (e.pnl_pct or 0) >= 0 else 'neg' }}" data-pnl="{{ e.id }}">
  {% if e.pnl_pct is not none %}{{ "%+.1f"|format(e.pnl_pct) }}%{% else %}-{% endif %}
</p>
```

- [ ] **Step 4: `dashboard.js` — PnL-weergave aanpassen**

Zoek in `web/static/dashboard.js` (regel 51, 57, 98-134 in de huidige
staat — lees de exacte huidige inhoud zelf op, dit dekt de flash-
animatie bij een gewijzigde PnL-waarde en het bijwerken van
`[data-pnl]`/`[data-pnl-pct]`-elementen). Overal waar nu `p.pnl_eur`
gelezen/vergeleken wordt (bv. `p.pnl_eur !== null`,
`pnlEl.firstChild.textContent = `€${p.pnl_eur.toFixed(2)} `"`), vervang
door `p.pnl_pct` met een `%`-format in plaats van `€`. Zoek ook naar een
apart `[data-pnl-pct]`-element (los van `[data-pnl]` zelf) — als de
template na Step 3 geen los `data-pnl-pct`-span meer heeft (het percentage
staat nu IN het hoofdelement, niet meer als aparte span erna), verwijder
de bijbehorende JS-selector/update-logica voor dat aparte element ook,
in plaats van hem dood te laten hangen.

Zoek daarnaast in `web/static/dashboard.js` (en, indien aanwezig, in
`base.html`) naar de live tab-titel/favicon-PnL-functionaliteit (grep op
`document.title`/`favicon` in combinatie met `pnl`) — als die op
`pnl_eur` leunt, pas hem aan naar `pnl_pct` met een `%`-suffix in plaats
van een `€`-bedrag. Documenteer in je rapport exact welke regels je hier
vond en aanpaste.

- [ ] **Step 5: `portfolioGlow`-aanroep en heatmap/cumulatieve-grafiek**

`portfolioGlow` zelf (`web/templates/base.html:717-722`) hoeft niet te
veranderen — het is een simpele teken-check (`> 0`/`< 0`/anders 0), werkt
identiek met een percentage als met een eurobedrag. Zoek de AANROEP van
`portfolioGlow(...)` (grep op `portfolioGlow(` in `base.html`, gebruikt
`s.week_result_eur` uit de `/api/system_status`-response) en pas de
gelezen key aan naar `s.week_result_pct` (die key heet zo sinds Taak 5/8).

Zoek de rendering van de trade-kalender-heatmap en de cumulatieve-
resultaatgrafiek (grep op `cumulative_eur`/`daily_results`/
`heatmap_weeks` in `web/static/*.js` en `web/templates/account.html`) —
overal waar nu `cumulative_eur` gelezen wordt, wordt dat `cumulative_pct`
(zie Taak 8's nieuwe veldnaam); overal waar een €-format wordt toegepast
op een heatmap-dagwaarde, wordt dat een %-format. Zoek ook
`_build_heatmap_weeks` in `web/main.py` (de Python-kant die
`repo.daily_results`'s output naar een weken-structuur voor de template
omzet) — die functie zelf hoeft waarschijnlijk niet te wijzigen (hij geeft
gewoon door wat `daily_results` teruggeeft, nu al percentages dankzij
Taak 8), maar controleer dit door de functie zelf op te zoeken en te
bevestigen dat er geen €-specifieke formatting IN die functie zit.

- [ ] **Step 6: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.risk; import web.main; print('import OK')"
```

- [ ] **Step 7: Grep-verificatie**

```bash
cd /home/user/Trade
grep -rn "pnl_eur\|cumulative_eur\|week_result_eur" app/ web/main.py web/templates/ web/static/*.js
```

Expected: lege output.

- [ ] **Step 8: Handmatige Playwright-verificatie**

Draai de app lokaal tegen een scratch-database met minstens één open trade
(gebruik het scratch-setup-patroon uit eerdere taken, maar sluit de trade
NIET af). Bezoek `/account` of `/coins/BTC`, bevestig dat de PnL-regel op
de open-trade-kaart een percentage toont (geen €-teken), en dat er geen
JS-console-fouten optreden. Bevestig ook dat de trade-kalender-heatmap en
de cumulatieve grafiek nog renderen zonder crash (met of zonder zinvolle
data, zolang het niet stuk gaat).

- [ ] **Step 9: Commit**

```bash
cd /home/user/Trade
git add app/risk.py web/main.py web/templates/_macros.html web/static/dashboard.js web/templates/base.html web/templates/account.html
git commit -m "$(cat <<'EOF'
Live PnL, ambient gloed, heatmap en cumulatieve grafiek: naar percentage

compute_unrealized_pnl gaf een risicogewogen (risk_eur-afhankelijk)
pnl_eur/pnl_pct terug — beide altijd 0 zodra risk_eur nooit meer gevuld
wordt. Herschreven naar de kale procentuele koersbeweging, zelfde formule
als journal_entries.result_pct. open_trade_body's PnL-regel, dashboard.js'
live-update, en de aanroepen van portfolioGlow/de heatmap/de cumulatieve
grafiek volgen de nieuwe percentage-gebaseerde velden uit Taak 8.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 10: Wekelijkse/maandelijkse samenvatting — percentage

**Files:**
- Modify: `app/periodic_summary.py`

**Interfaces:**
- Consumes: Taak 8 (`repo.period_stats`/`period_stats_auto_scan` geven nu
  `total_result_pct` i.p.v. `total_result_eur`, en `best`/`worst`-dicts
  bevatten `result_pct` i.p.v. `result_eur`).
- Produces: geen.

- [ ] **Step 1: `_period_summary_text` aanpassen**

Huidige code (`app/periodic_summary.py:28-60`):

```python
def _period_summary_text(stats: dict, auto_scan_stats: Optional[dict]) -> str:
    """Platte-tekst samenvatting voor de notifications-tabel: dezelfde
    cijfers als de oude Telegram-samenvatting, zonder de markdown,
    emoji-koppen of dividers die niet passen in een korte lijst-rij op
    /meldingen."""
    parts = [f"{stats['signal_count']} signalen, waarvan {stats['hoog_count']} hoog vertrouwen."]
    if stats["closed_count"]:
        winrate = stats["wins"] / stats["closed_count"] * 100
        sign = "+" if stats["total_result_eur"] >= 0 else ""
        parts.append(
            f"{stats['closed_count']} trades gesloten, {stats['wins']} gewonnen ({winrate:.0f}%), "
            f"resultaat {sign}€{stats['total_result_eur']:.2f}."
        )
        if stats["best"]:
            b = stats["best"]
            b_sign = "+" if b["result_eur"] >= 0 else ""
            parts.append(f"Beste trade: {b['coin']} {b_sign}€{b['result_eur']:.2f}.")
        if stats["worst"]:
            w = stats["worst"]
            w_sign = "+" if w["result_eur"] >= 0 else ""
            parts.append(f"Zwakste trade: {w['coin']} {w_sign}€{w['result_eur']:.2f}.")
    else:
        parts.append("Geen trades gesloten in deze periode.")
    if auto_scan_stats and auto_scan_stats["signal_count"] > 0:
        winrate_txt = (
            f", winrate {auto_scan_stats['winrate_pct']:.0f}%"
            if auto_scan_stats["winrate_pct"] is not None else ""
        )
        parts.append(
            f"HesPulse vond zelf {auto_scan_stats['signal_count']} kansen "
            f"({auto_scan_stats['closed_count']} afgesloten{winrate_txt})."
        )
    return " ".join(parts)
```

Vervang de `€`-regels door `%`-equivalenten (structuur en de rest van de
functie ongewijzigd):

```python
def _period_summary_text(stats: dict, auto_scan_stats: Optional[dict]) -> str:
    """Platte-tekst samenvatting voor de notifications-tabel: dezelfde
    cijfers als de oude Telegram-samenvatting, zonder de markdown,
    emoji-koppen of dividers die niet passen in een korte lijst-rij op
    /meldingen."""
    parts = [f"{stats['signal_count']} signalen, waarvan {stats['hoog_count']} hoog vertrouwen."]
    if stats["closed_count"]:
        winrate = stats["wins"] / stats["closed_count"] * 100
        sign = "+" if stats["total_result_pct"] >= 0 else ""
        parts.append(
            f"{stats['closed_count']} trades gesloten, {stats['wins']} gewonnen ({winrate:.0f}%), "
            f"resultaat {sign}{stats['total_result_pct']:.1f}%."
        )
        if stats["best"]:
            b = stats["best"]
            b_sign = "+" if b["result_pct"] >= 0 else ""
            parts.append(f"Beste trade: {b['coin']} {b_sign}{b['result_pct']:.1f}%.")
        if stats["worst"]:
            w = stats["worst"]
            w_sign = "+" if w["result_pct"] >= 0 else ""
            parts.append(f"Zwakste trade: {w['coin']} {w_sign}{w['result_pct']:.1f}%.")
    else:
        parts.append("Geen trades gesloten in deze periode.")
    if auto_scan_stats and auto_scan_stats["signal_count"] > 0:
        winrate_txt = (
            f", winrate {auto_scan_stats['winrate_pct']:.0f}%"
            if auto_scan_stats["winrate_pct"] is not None else ""
        )
        parts.append(
            f"HesPulse vond zelf {auto_scan_stats['signal_count']} kansen "
            f"({auto_scan_stats['closed_count']} afgesloten{winrate_txt})."
        )
    return " ".join(parts)
```

- [ ] **Step 2: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.periodic_summary; print('import OK')"
```

- [ ] **Step 3: Throwaway-scriptverificatie**

```bash
cd /home/user/Trade
rm -f /tmp/scratch_periodic_summary.db
DATABASE_PATH=/tmp/scratch_periodic_summary.db python3 -c "
from app import db, repo
db.init_db()
from app.security import hash_password
uid = repo.create_user(username='t', password_hash=hash_password('testpass123'), portfolio_eur=1000.0, risk_percent=1.0)
signal_id = repo.insert_signal({
    'coin': 'BTC', 'direction': 'long', 'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 50000.0, 'stop_loss': 49000.0, 'take_profit': 52000.0,
    'technical_confirmed': 1, 'confidence': 'hoog', 'hard_gates_ok': 1, 'reason': 'test',
})
entry_id = repo.create_journal_entry(signal_id, uid, None)
repo.update_journal_status(entry_id, uid, 'genomen', entry_price=50000.0)
repo.close_journal_trade(entry_id, uid, 51000.0, '2026-09-30T12:00:00')
from datetime import datetime, timedelta, timezone
since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
stats = repo.period_stats(uid, since)
from app.periodic_summary import _period_summary_text
text = _period_summary_text(stats, None)
assert '€' not in text, f'geen euro-teken meer verwacht, kreeg: {text}'
assert '%' in text
print('periodic_summary OK:', text)
"
rm -f /tmp/scratch_periodic_summary.db
```

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add app/periodic_summary.py
git commit -m "$(cat <<'EOF'
Wekelijkse/maandelijkse samenvatting: percentage i.p.v. euro

_period_summary_text gebruikte repo.period_stats' total_result_eur/
result_eur (Taak 8 hernoemde die velden naar total_result_pct/result_pct)
— tekst toont nu "+3.2%" in plaats van "+€32.00".

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 11: Volledige regressie, diff-controle en push

**Files:**
- Geen nieuwe wijzigingen verwacht — deze taak verifieert Taak 1 t/m 10
  samen en rondt af.

**Interfaces:**
- Consumes: alles uit Taak 1 t/m 10.
- Produces: een gepushte branch en een draaiende VPS.

- [ ] **Step 1: Grep-verificatie — geen resterende geld-referenties**

```bash
cd /home/user/Trade
echo "=== portfolio_eur (verwacht: alleen create_user/register_user/schema/migraties/scripts) ==="
grep -rn "portfolio_eur" app/ web/main.py web/templates/
echo "=== risk_percent (verwacht: alleen create_user/register_user/schema/migraties, GEEN sizing-gebruik) ==="
grep -rn "risk_percent" app/ web/main.py web/templates/ | grep -v "confirm_threshold"
echo "=== evaluatie-functienamen (verwacht: leeg) ==="
grep -rn "get_active_evaluation\|create_evaluation\|eval_sizing_blocked\|compute_eval_risk_eur\|apply_eval_stop_cap\|eval_max_stop_pct\|evaluate_prop_progress\|EVAL_TRADE_FEE_RATE\|EVAL_LEVERAGE_DAILY_RATE" app/ web/
echo "=== result_eur/pnl_eur/cumulative_eur (verwacht: leeg) ==="
grep -rn "result_eur\|pnl_eur\|cumulative_eur\|week_result_eur" app/ web/main.py web/templates/ web/static/*.js
echo "=== /dashboard-referenties buiten de redirect zelf (verwacht: leeg) ==="
grep -rn '"/dashboard"' web/templates/ web/static/*.js
```

Ga elke overgebleven treffer na: `portfolio_eur`/`risk_percent` in
`create_user`/`register_user`/`app/schema.sql`/`app/db.py` is verwacht
(kolommen blijven bestaan, aanpak A) — een treffer in een route, template,
of statistiekfunctie is een gemiste plek uit een eerdere taak, fix die
dan hier alsnog en documenteer het in je rapport.

- [ ] **Step 2: Draai de app lokaal tegen een scratch-database**

```bash
cd /home/user/Trade
rm -f /tmp/scratch_full_regression.db
DATABASE_PATH=/tmp/scratch_full_regression.db python3 -c "from app import db; db.init_db()"
DATABASE_PATH=/tmp/scratch_full_regression.db python3 -c "
from app import repo
from app.security import hash_password
repo.create_user(username='regressietest', password_hash=hash_password('testpass123'), portfolio_eur=1000.0, risk_percent=1.0)
signal_id = repo.insert_signal({
    'coin': 'BTC', 'direction': 'long', 'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 50000.0, 'stop_loss': 49000.0, 'take_profit': 52000.0,
    'technical_confirmed': 1, 'confidence': 'hoog', 'hard_gates_ok': 1, 'reason': 'test signaal voor regressie',
})
print('signal_id', signal_id)
"
DATABASE_PATH=/tmp/scratch_full_regression.db JWT_SECRET=test_secret_regressie_1234567890 uvicorn web.main:app --port 8012 &
sleep 2
```

- [ ] **Step 2: Playwright-screenshots en functionele check**

Log in als `regressietest`, en controleer:
- `/signalen`: laadt zonder fout, geen risicogauge/evaluatie-verwijzing.
- `/account`: laadt zonder fout, geen portfolio-kaart, journaaltabel toont
  percentage in de Resultaat-kolom (of "-" als er nog niets gesloten is),
  stille-uren-formulier heeft geen verborgen portfolio-velden meer (check
  de gerenderde HTML-bron, niet alleen het zichtbare formulier).
- `/coins/BTC`: laadt zonder fout, geen "Oefenen met deze coin"-rekenhulp
  meer.
- `/dashboard`: 303-redirect naar `/signalen` (curl-check, zie Taak 1).
- `/evaluatie`: 404 of vergelijkbare nette fout is prima hier — de route
  bestaat na Taak 3 niet meer; bevestig dat dit geen ongeharkte 500-crash
  geeft.
- Markeer het testsignaal als "Genomen" met een eigen entry-prijs via het
  journaal-formulier, bevestig dat de open-trade-kaart verschijnt zonder
  €-teken in de PnL-regel.
- Sluit de trade via het sluiten-formulier, bevestig dat de journaaltabel
  daarna een percentage toont in de Resultaat-kolom.

```bash
kill %1 2>/dev/null
rm -f /tmp/scratch_full_regression.db
```

- [ ] **Step 3: Herdraai alle scratch-testscripts uit Taak 1-10 achter elkaar**

Als de scratchpad-scripts uit eerdere taken nog bestaan, draai ze
allemaal opnieuw, elk met zijn eigen scratch-database. Expected: allemaal
eindigen zonder `AssertionError`/Traceback.

- [ ] **Step 4: Bekijk de volledige diff**

```bash
cd /home/user/Trade && git diff d86bfa5 --stat
```

(`d86bfa5` is de laatste commit vóór dit plan begon — de spec-addendum-
commit.)

Controleer dat alleen de in dit plan genoemde bestanden zijn geraakt:
`app/risk.py`, `app/repo.py`, `app/signal_processor.py`,
`app/periodic_summary.py`, `web/main.py`, `web/templates/account.html`,
`web/templates/_macros.html`, `web/templates/base.html`,
`web/templates/coin.html`, `web/static/coin.js`, `web/static/dashboard.js`,
`web/static/style.css`, plus de verwijderde `web/templates/dashboard.html`/
`web/templates/evaluatie.html`/`web/static/evaluatie.js`. Geen wijziging
aan `app/schema.sql`, `app/db.py`, of `signals`/`confirm_threshold_pct`-
gerelateerde code.

- [ ] **Step 5: Push**

```bash
cd /home/user/Trade && git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 6: VPS-deploy-instructies**

Twee losse commando's (niet combineren):

```bash
cd /opt/crypto-alerts && sudo -u crypto git pull origin claude/crypto-day-trading-alerts-5p8w6v
```

Daarna:

```bash
sudo systemctl restart crypto-web.service
```

En daarna (dit project raakt ook `app/periodic_summary.py`, dat draait
via aparte systemd-timers, niet via `crypto-bot.service` zelf — maar
raakt geen enkele van de altijd-actieve pijplijn-bestanden zoals
`signal_processor.py`'s day-trading-pad direct genoeg om een herstart
nodig te maken vóór de eerstvolgende timer-run. Herstart 'm voor de
zekerheid toch, aangezien signal_processor.py wel is aangeraakt in Taak 3):

```bash
sudo systemctl restart crypto-bot.service
```

- [ ] **Step 7: Bevestig bij de gebruiker**

Meld kort: welke commits gepusht zijn, dat de handmatige verificatie
(Genomen → Sluiten → percentage in journaaltabel) werkte, dat de grep-
verificatie schoon was, en dat de VPS herstart moet worden met de
commando's hierboven.

## Self-Review (uitgevoerd tijdens het schrijven van dit plan)

1. **Spec-dekking:**
   - `/dashboard` weg → Taak 1. ✓
   - Evaluatie-simulatie volledig weg → Taak 3 (aanroepers) + Taak 4
     (functies zelf), gesplitst om elke taak de app werkend te laten
     achterlaten. ✓
   - Generieke positiegrootte-berekening weg → al dode code gebleken
     tijdens onderzoek (Taak 4's bevinding), `compute_risk_eur` weg,
     `compute_position_size` blijft bewust (legacy-fallback). ✓
   - Losse rekenhulp coin-pagina weg → Taak 2. ✓
   - Account-pagina opschoning → Taak 6. ✓
   - Risicogauge weg → grotendeels al weg via Taak 1 (zat alleen in
     dashboard.html/de oude `/dashboard`-route); `/api/system_status`'s
     eigen risk_pct-pad apart opgeruimd in Taak 5, tijdens onderzoek
     ontdekt, niet in de oorspronkelijke spec-tekst genoemd. ✓
   - CSV-export/journaal-weergave → Taak 7. ✓
   - Addendum (ambient gloed, cumulatieve grafiek, heatmap, wekelijkse
     samenvatting, statistiek-laag, live PnL — dat laatste tijdens
     planning zelf ontdekt, niet in het addendum letterlijk genoemd maar
     wel onder dezelfde "puur percentage"-beslissing vallend) → Taak
     8/9/10. ✓
   - "Blijft ongewijzigd" (confirm_threshold_pct, verplichte factoren,
     winrate_for_user/auto_outcome, compute_stop_take(_from_levels),
     compute_sltp_progress_pct) → expliciet genoemd in Global Constraints,
     bevestigd nergens aangeraakt via de Taak 11-grep-verificatie. ✓
2. **Placeholder-scan:** Taak 1, 2, 5, 6, 7, 9, 10 geven volledige,
   letterlijke code (kleine, gerichte wijzigingen). Taak 3 en 4 geven
   letterlijke code voor de kernstukken en een exhaustieve, grep-
   verifieerbare naamlijst voor de rest (evaluatie raakt >20 functies
   verspreid over 2 bestanden — volledige code voor elke functie zou het
   plan onwerkbaar groot maken; elke genoemde functie is met naam en
   ongeveer-regelnummer aangewezen, niet vaag omschreven). Taak 8 geeft
   twee volledig uitgewerkte voorbeelden plus een expliciete, benoemde
   lijst resterende functies met de exacte transformatieregel — zelfde
   aanpak als het eerdere visuele-verfijningsproject deze sessie voor zijn
   mechanische CSS-tokenisatie-taak, daar destijds ook gemotiveerd als
   passend bij de schaal van een pure waarde-vervanging.
3. **Typeconsistentie:** `close_journal_trade`'s nieuwe signatuur
   `(result_pct, is_practice)` wordt consistent gebruikt door Taak 5's
   eigen aanpassing en genoemd als vereiste in Taak 7-10's Interfaces-
   blokken. `repo.week_result_pct`/`cumulative_pct`/`daily_results`'
   percentage-velden (Taak 8) worden letterlijk zo genoemd in Taak 9 en
   10's Consumes-blokken. `risk.compute_unrealized_pnl`'s nieuwe
   eenvoudigere signatuur (Taak 9) wordt consistent gebruikt in dezelfde
   taak se eigen aanpassingen aan `_enrich_open_positions`.
