# Kraken Prop evaluatie: eigen pagina Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De Kraken Prop evaluatie-simulator verplaatsen van een dashboardkaart naar een volwaardige eigen pagina (`/evaluatie`) met een echte saldografiek, uitleg waarom de regels bestaan, disciplinetips, en geschiedenis met patronen.

**Architecture:** Het bestaande backend-model (`prop_evaluations`, `journal_entries.evaluation_id`, `risk.evaluate_prop_progress`) blijft ongewijzigd. De bestaande context-opbouw in de dashboard-route wordt uitgetrokken naar een gedeelde helperfunctie, hergebruikt door zowel het dashboard (compacte samenvatting) als de nieuwe pagina (volledige weergave). Eén nieuwe repo-functie levert de data voor een LightweightCharts-lijngrafiek met twee vaste referentieniveaus.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite, vanilla JS/CSS, LightweightCharts (al elders in de app geladen via CDN).

**Spec:** `docs/superpowers/specs/2026-09-08-kraken-prop-evaluatie-pagina-design.md` (bouwt op `docs/superpowers/specs/2026-09-07-kraken-prop-evaluatie-design.md`, dat backend-model niet gewijzigd)

## Global Constraints

- Geen wijziging aan `risk.py`, aan de regel-logica, of aan hoe oefentrades aan een run gekoppeld worden.
- Databasetoegang uitsluitend via `app/repo.py`.
- Een niet-ISO `exit_time` mag geen enkele nieuwe functie laten crashen — zelfde beschermende `try/except` als eerder toegepast in `list_evaluation_daily_results`.
- Bestaande, al gereviewde CSS-klassen (`risk-gauge`/`risk-mid`/`risk-high`/`goal-fill`, `risk-pulse`, `eval-reveal-pass`/`eval-reveal-fail`, `heat-cell`) worden hergebruikt op de nieuwe pagina, niet gedupliceerd.
- Elke pagina die `base.html` extend geeft `"coins": repo.list_coins()` mee in zijn context — zonder die sleutel breekt de coin-dropdown in de navigatiebalk.
- Geen pytest-suite: elke Python-wijziging krijgt een los testscript met `assert` + `print("OK: ...")` tegen een tijdelijke SQLite-database.
- Voor de grafiek-/CSS-taak is er geen geautomatiseerde test mogelijk (client-side canvas-rendering); die taak schrijft expliciet handmatige Playwright-verificatie voor.

---

### Task 1: `repo.py` — saldografiek-data

**Files:**
- Modify: `app/repo.py`
- Test: `<scratchpad>/test_eval_balance_curve.py`

**Interfaces:**
- Produces: `repo.list_evaluation_balance_curve(evaluation_id: int) -> list[dict]`, elk item `{"time": <ISO-string>, "balance": <float>}`, eerste punt altijd bij `started_at`/`tier_amount`.

- [ ] **Step 1: Voeg de functie toe aan `app/repo.py`**

Voeg toe direct na `list_evaluation_daily_results`:

```python
def list_evaluation_balance_curve(evaluation_id: int) -> list[dict]:
    """Cumulatieve saldo-lijn voor de grafiek op de evaluatie-pagina: één
    punt bij de start (tier_amount, started_at) en daarna één punt per
    gesloten, aan deze run gekoppelde trade, oplopend saldo. Anders dan
    list_evaluation_daily_results (dat per handelsdag optelt voor de
    dag-stippen) geeft dit de exacte volgorde van individuele trades
    terug, voor een vloeiende lijn in plaats van een dagoverzicht."""
    evaluation = get_evaluation(evaluation_id)
    if not evaluation:
        return []
    with db.session() as conn:
        rows = conn.execute(
            """SELECT exit_time, result_eur FROM journal_entries
               WHERE evaluation_id = ? AND exit_price IS NOT NULL
               ORDER BY exit_time""",
            (evaluation_id,),
        ).fetchall()
    curve = [{"time": evaluation["started_at"], "balance": evaluation["tier_amount"]}]
    running = evaluation["tier_amount"]
    for row in rows:
        try:
            datetime.fromisoformat(row["exit_time"])
        except (ValueError, TypeError):
            # Zelfde beschermende patroon als list_evaluation_daily_results:
            # een niet-ISO exit_time mag de grafiek niet laten crashen of
            # een onbruikbaar punt opleveren, die ene sluiting ontbreekt
            # dan gewoon in de lijn.
            continue
        running += (row["result_eur"] or 0.0)
        curve.append({"time": row["exit_time"], "balance": running})
    return curve
```

- [ ] **Step 2: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_eval_balance_curve.py` (gebruik het echte scratchpad-pad, niet een letterlijke map genaamd `<scratchpad>`):

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-eval-balance-curve-0123456789012"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("balancecurveuser", security.hash_password("testpass123"), 1000.0, 1.0, "782")
eval_id = repo.create_evaluation(uid, tier_amount=10000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)

curve0 = repo.list_evaluation_balance_curve(eval_id)
assert len(curve0) == 1
assert curve0[0]["balance"] == 10000.0
print("OK: zonder gesloten trades bevat de lijn alleen het startpunt")

with db.session() as conn:
    conn.execute("INSERT INTO messages (received_at, raw_text) VALUES (?, 'test')", (db.now_iso(),))
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

def make_entry(result_eur, exit_time):
    signal_id = repo.insert_signal({
        "message_id": msg_id, "coin": "TAO", "direction": "long", "category": "oefening",
        "price": 100.0, "rsi": 50, "macd": 0, "macd_signal": 0, "volume_ratio": 1,
        "ema9": 100, "ema21": 100, "atr": 5, "atr_avg20": 5, "adx": 20,
        "technical_confirmed": 1, "confidence": "hoog vertrouwen", "reason": "test",
        "stop_loss": 90.0, "take_profit": 120.0, "context_note": None,
        "is_practice": 1, "plain_explanation": None,
    })
    entry_id = repo.create_journal_entry(signal_id, uid, risk_eur=100.0, evaluation_id=eval_id)
    with db.session() as conn:
        conn.execute(
            "UPDATE journal_entries SET exit_price = 105, exit_time = ?, result_eur = ? WHERE id = ?",
            (exit_time, result_eur, entry_id),
        )
    return entry_id

make_entry(200.0, "2026-09-01T10:00:00+00:00")
make_entry(-50.0, "2026-09-02T10:00:00+00:00")

curve = repo.list_evaluation_balance_curve(eval_id)
assert len(curve) == 3
assert curve[0]["balance"] == 10000.0
assert curve[1]["balance"] == 10200.0
assert curve[2]["balance"] == 10150.0
print("OK: cumulatief saldo klopt en volgt de exit_time-volgorde")

# Een niet-ISO exit_time mag de lijn niet laten crashen, en de overige
# punten moeten gewoon terugkomen.
make_entry(1000.0, "niet-een-datum")
curve2 = repo.list_evaluation_balance_curve(eval_id)
assert len(curve2) == 3, f"verwacht dat de kapotte rij overgeslagen wordt, kreeg {curve2}"
print("OK: een niet-ISO exit_time crasht niet en wordt overgeslagen")

print("ALLE EVAL_BALANCE_CURVE TESTS GESLAAGD")
```

- [ ] **Step 3: Run, verwacht een `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_eval_balance_curve.py`
Expected: `AttributeError: module 'app.repo' has no attribute 'list_evaluation_balance_curve'`, opgelost door Step 1.

- [ ] **Step 4: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_eval_balance_curve.py`
Expected: alle 4 "OK:"-regels, eindigend met "ALLE EVAL_BALANCE_CURVE TESTS GESLAAGD".

- [ ] **Step 5: Commit**

```bash
git add app/repo.py
git commit -m "$(cat <<'EOF'
repo.py: saldografiek-data voor de evaluatie-pagina

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 2: `web/main.py` — gedeelde context-helper + nieuwe route

**Files:**
- Modify: `web/main.py`
- Test: `<scratchpad>/test_eval_pagina_routes.py`

**Interfaces:**
- Consumes: `repo.list_evaluation_balance_curve` (Task 1).
- Produces: `_build_eval_context(user: dict, request: Request) -> dict` (gedeeld door `dashboard` en de nieuwe route), `_eval_history_stats(eval_history: list[dict]) -> Optional[dict]`, `_eval_coaching_tip(eval_display: Optional[dict], daily_loss_used_pct: float, drawdown_used_pct: float, profit_progress_pct: float) -> Optional[str]`, `GET /evaluatie`.

Dit is een refactor van bestaande, al gereviewde code (de dashboard-route) plus een nieuwe route. Het gedrag van het dashboard mag niet veranderen door de refactor zelf — alleen de daarna volgende template-wijziging (Task 4) verandert wat zichtbaar is.

- [ ] **Step 1: Trek de bestaande eval-context-opbouw uit `dashboard` in een eigen functie**

Zoek in `web/main.py`'s `dashboard`-route dit blok (rond regel 444-488):

```python
    # Evaluatie simulatie: bij een net beëindigde run (geslaagd/mislukt)
    # is er geen actieve run meer om te tonen, maar de reveal-melding in de
    # URL vraagt om die laatste run toch één keer te laten zien in zijn
    # eindtoestand.
    active_evaluation = repo.get_active_evaluation(user["id"])
    eval_history = repo.list_evaluations_for_user(user["id"])
    eval_display = active_evaluation
    if not eval_display and (request.query_params.get("evaluatie_geslaagd") or request.query_params.get("evaluatie_mislukt")):
        eval_display = eval_history[0] if eval_history else None

    eval_day_number = None
    eval_daily_loss_used_pct = 0.0
    eval_drawdown_used_pct = 0.0
    eval_profit_progress_pct = 0.0
    eval_daily_results = []
    if eval_display:
        end_reference = (
            datetime.fromisoformat(eval_display["ended_at"]) if eval_display["ended_at"]
            else datetime.now(timezone.utc)
        )
        eval_day_number = (end_reference.date() - datetime.fromisoformat(eval_display["started_at"]).date()).days + 1

        display_day_start_balance = eval_display["day_start_balance"]
        if risk.trading_day_label(datetime.now(timezone.utc)) != eval_display["day_start_date"]:
            # De handelsdag is inmiddels doorgeschoven maar er is nog geen
            # trade gesloten om dat in de opgeslagen staat te verwerken
            # (dat gebeurt pas bij de eerstvolgende sluiting via
            # evaluate_prop_progress) — voor de weergave alvast rekenen
            # met een verse dag, anders toont de balk en de risk-pulse
            # ademhaling het verlies van een dag die al voorbij is.
            display_day_start_balance = eval_display["current_balance"]

        daily_loss_amount = display_day_start_balance * eval_display["max_daily_loss_pct"] / 100
        loss_so_far = max(0.0, display_day_start_balance - eval_display["current_balance"])
        eval_daily_loss_used_pct = min(100.0, (loss_so_far / daily_loss_amount * 100) if daily_loss_amount else 0.0)

        drawdown_amount = eval_display["tier_amount"] * eval_display["max_drawdown_pct"] / 100
        drawdown_so_far = max(0.0, eval_display["tier_amount"] - eval_display["current_balance"])
        eval_drawdown_used_pct = min(100.0, (drawdown_so_far / drawdown_amount * 100) if drawdown_amount else 0.0)

        profit_amount = eval_display["tier_amount"] * eval_display["profit_target_pct"] / 100
        profit_so_far = max(0.0, eval_display["current_balance"] - eval_display["tier_amount"])
        eval_profit_progress_pct = min(100.0, (profit_so_far / profit_amount * 100) if profit_amount else 0.0)

        eval_daily_results = _build_eval_day_dots(repo.list_evaluation_daily_results(eval_display["id"]))
```

Verwijder dit hele blok uit `dashboard` en vervang door:

```python
    eval_ctx = _build_eval_context(user, request)
```

Voeg de uitgetrokken functie toe als eigen, module-level functie, vlak vóór `dashboard` (of direct na `_build_eval_day_dots`, waar hij al staat):

```python
def _build_eval_context(user: dict, request: Request) -> dict:
    """Evaluatie-simulatie context, gedeeld door het dashboard (compacte
    samenvatting) en de eigen /evaluatie-pagina (volledige weergave). Bij
    een net beëindigde run (geslaagd/mislukt) is er geen actieve run meer
    om te tonen, maar de reveal-melding in de URL vraagt om die laatste
    run toch één keer te laten zien in zijn eindtoestand."""
    active_evaluation = repo.get_active_evaluation(user["id"])
    eval_history = repo.list_evaluations_for_user(user["id"])
    eval_display = active_evaluation
    if not eval_display and (request.query_params.get("evaluatie_geslaagd") or request.query_params.get("evaluatie_mislukt")):
        eval_display = eval_history[0] if eval_history else None

    eval_day_number = None
    eval_daily_loss_used_pct = 0.0
    eval_drawdown_used_pct = 0.0
    eval_profit_progress_pct = 0.0
    eval_daily_results = []
    eval_daily_loss_remaining_eur = None
    if eval_display:
        end_reference = (
            datetime.fromisoformat(eval_display["ended_at"]) if eval_display["ended_at"]
            else datetime.now(timezone.utc)
        )
        eval_day_number = (end_reference.date() - datetime.fromisoformat(eval_display["started_at"]).date()).days + 1

        display_day_start_balance = eval_display["day_start_balance"]
        if risk.trading_day_label(datetime.now(timezone.utc)) != eval_display["day_start_date"]:
            display_day_start_balance = eval_display["current_balance"]

        daily_loss_amount = display_day_start_balance * eval_display["max_daily_loss_pct"] / 100
        loss_so_far = max(0.0, display_day_start_balance - eval_display["current_balance"])
        eval_daily_loss_used_pct = min(100.0, (loss_so_far / daily_loss_amount * 100) if daily_loss_amount else 0.0)
        eval_daily_loss_remaining_eur = max(0.0, daily_loss_amount - loss_so_far)

        drawdown_amount = eval_display["tier_amount"] * eval_display["max_drawdown_pct"] / 100
        drawdown_so_far = max(0.0, eval_display["tier_amount"] - eval_display["current_balance"])
        eval_drawdown_used_pct = min(100.0, (drawdown_so_far / drawdown_amount * 100) if drawdown_amount else 0.0)

        profit_amount = eval_display["tier_amount"] * eval_display["profit_target_pct"] / 100
        profit_so_far = max(0.0, eval_display["current_balance"] - eval_display["tier_amount"])
        eval_profit_progress_pct = min(100.0, (profit_so_far / profit_amount * 100) if profit_amount else 0.0)

        eval_daily_results = _build_eval_day_dots(repo.list_evaluation_daily_results(eval_display["id"]))

    return {
        "eval_display": eval_display,
        "eval_history": eval_history,
        "eval_day_number": eval_day_number,
        "eval_daily_loss_used_pct": eval_daily_loss_used_pct,
        "eval_drawdown_used_pct": eval_drawdown_used_pct,
        "eval_profit_progress_pct": eval_profit_progress_pct,
        "eval_daily_results": eval_daily_results,
        "eval_daily_loss_remaining_eur": eval_daily_loss_remaining_eur,
    }
```

Zoek in `dashboard`'s `return templates.TemplateResponse(request, "dashboard.html", { ... })`-dict de regel `"unclear_messages": unclear_messages,` en voeg er direct na toe:

```python
        **eval_ctx,
```

(Dit vervangt de losse `"eval_display": eval_display,` etc.-sleutels die er vóór deze refactor stonden niet meer los stonden — die kwamen namelijk al uit hetzelfde blok en worden nu via `**eval_ctx` meegegeven. Als er nog losse `"eval_...":`-regels in de dict staan van vóór deze refactor, verwijder die: `**eval_ctx` levert dezelfde sleutels al.)

- [ ] **Step 2: Voeg de geschiedenis-statistieken-helper toe**

Voeg toe, direct na `_build_eval_context`:

```python
def _eval_history_stats(eval_history: list[dict]) -> Optional[dict]:
    """Patronen uit afgeronde evaluatie-runs voor de geschiedenis-sectie:
    gemiddeld aantal dagen tot slagen/falen (elk apart pas getoond vanaf 2
    afgeronde runs van dat type, anders is 'gemiddeld' misleidend voor een
    losse uitschieter) en de meest voorkomende faalreden. Geeft None
    terug als er nergens genoeg data voor is."""
    passed = [e for e in eval_history if e["status"] == "geslaagd" and e["ended_at"]]
    failed = [e for e in eval_history if e["status"] == "mislukt" and e["ended_at"]]

    def _avg_days(runs: list[dict]) -> float:
        days = [
            (datetime.fromisoformat(r["ended_at"]).date() - datetime.fromisoformat(r["started_at"]).date()).days + 1
            for r in runs
        ]
        return sum(days) / len(days)

    avg_days_to_pass = _avg_days(passed) if len(passed) >= 2 else None
    avg_days_to_fail = _avg_days(failed) if len(failed) >= 2 else None

    common_fail_reason = None
    if failed:
        reasons = Counter(r["closed_reason"] for r in failed if r["closed_reason"])
        if reasons:
            common_fail_reason = reasons.most_common(1)[0][0]

    if avg_days_to_pass is None and avg_days_to_fail is None and common_fail_reason is None:
        return None
    return {
        "avg_days_to_pass": avg_days_to_pass,
        "avg_days_to_fail": avg_days_to_fail,
        "common_fail_reason": common_fail_reason,
    }


def _eval_coaching_tip(
    eval_display: Optional[dict], daily_loss_used_pct: float, drawdown_used_pct: float, profit_progress_pct: float,
) -> Optional[str]:
    """Eén korte, op de actuele status toegesneden tip in plaats van
    altijd dezelfde statische tekst. Alleen relevant voor een actief
    lopende run — een afgeronde run heeft niks meer te sturen. Twee
    situaties zijn de moeite waard om expliciet te benoemen: dicht bij
    een limiet (stoppen is een optie, geen verplichting) en dicht bij het
    winstdoel (het moment waarop discipline het vaakst verslapt)."""
    if not eval_display or eval_display["status"] != "actief":
        return None
    if daily_loss_used_pct >= 70 or drawdown_used_pct >= 70:
        return "Je zit dicht bij een limiet. Overweeg te stoppen voor vandaag, niet omdat het moet, maar omdat het kan."
    if profit_progress_pct >= 70:
        return "Je bent dicht bij je winstdoel. Dit is precies het moment waarop mensen hun regels laten verslappen. Blijf bij je proces."
    return None
```

Voeg `Counter` toe aan de imports bovenaan `web/main.py` (zoek de bestaande `from datetime import datetime, timedelta, timezone`-regel en voeg er een regel boven toe: `from collections import Counter`).

- [ ] **Step 3: Voeg de nieuwe route toe**

Voeg toe direct na `stop_evaluation` (na de bestaande `/evaluatie/stop`-route), vóór de `# Oefentrades: ...`-sectiekop:

```python
@app.get("/evaluatie")
async def evaluatie_page(request: Request, user: dict = Depends(require_login)):
    eval_ctx = _build_eval_context(user, request)
    eval_display = eval_ctx["eval_display"]
    balance_curve = repo.list_evaluation_balance_curve(eval_display["id"]) if eval_display else []
    eval_stats = _eval_history_stats(eval_ctx["eval_history"])
    eval_coaching_tip = _eval_coaching_tip(
        eval_display, eval_ctx["eval_daily_loss_used_pct"], eval_ctx["eval_drawdown_used_pct"],
        eval_ctx["eval_profit_progress_pct"],
    )

    return templates.TemplateResponse(request, "evaluatie.html", {
        "user": user,
        "coins": repo.list_coins(),
        "balance_curve": balance_curve,
        "eval_stats": eval_stats,
        "eval_coaching_tip": eval_coaching_tip,
        **eval_ctx,
    })
```

- [ ] **Step 4: Verplaats het start/stop-formulier naar de nieuwe pagina**

Zoek `start_evaluation` en `stop_evaluation` en vervang beide `return RedirectResponse(url="/dashboard", status_code=303)`-regels (drie stuks in totaal: twee in `start_evaluation`, één in `stop_evaluation`) door `return RedirectResponse(url="/evaluatie", status_code=303)`. Dit is de enige wijziging aan deze twee routes — hun validatielogica blijft ongewijzigd.

- [ ] **Step 5: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_eval_pagina_routes.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-eval-pagina-routes-0123456789012"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("evalpaginauser", security.hash_password("testpass123"), 1000.0, 1.0, "783")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

# --- dashboard blijft werken na de refactor (regressie-check) ---
resp_dash = client.get("/dashboard")
assert resp_dash.status_code == 200
print("OK: dashboard rendert nog steeds zonder fouten na de context-refactor")

# --- /evaluatie zonder actieve run: 200, geen crash ---
resp0 = client.get("/evaluatie")
assert resp0.status_code == 200
print("OK: GET /evaluatie zonder actieve run werkt")

# --- start verwijst nu naar /evaluatie, niet naar /dashboard ---
resp_start = client.post(
    "/evaluatie/start",
    data={"tier_amount": "10000", "profit_target_pct": "8", "max_drawdown_pct": "6"},
    follow_redirects=False,
)
assert resp_start.headers["location"] == "/evaluatie", resp_start.headers["location"]
print("OK: /evaluatie/start verwijst naar /evaluatie")

# --- /evaluatie met een actieve run: 200, bevat de balans-curve-data ---
active = repo.get_active_evaluation(uid)
assert active is not None
resp1 = client.get("/evaluatie")
assert resp1.status_code == 200
print("OK: GET /evaluatie met een actieve run werkt")

# --- stop verwijst ook naar /evaluatie ---
resp_stop = client.post("/evaluatie/stop", follow_redirects=False)
assert resp_stop.headers["location"] == "/evaluatie", resp_stop.headers["location"]
print("OK: /evaluatie/stop verwijst naar /evaluatie")

# --- _eval_history_stats: minder dan 2 afgeronde runs per categorie geeft None voor dat gemiddelde ---
stats_one_failed = web_main._eval_history_stats([
    {"status": "mislukt", "started_at": "2026-09-01T00:00:00+00:00", "ended_at": "2026-09-02T00:00:00+00:00", "closed_reason": "maximaal dagverlies geraakt"},
])
assert stats_one_failed["avg_days_to_fail"] is None
assert stats_one_failed["common_fail_reason"] == "maximaal dagverlies geraakt"
print("OK: _eval_history_stats verbergt een gemiddelde met minder dan 2 runs, toont de faalreden wel al bij 1")

stats_none = web_main._eval_history_stats([])
assert stats_none is None
print("OK: _eval_history_stats geeft None terug zonder afgeronde runs")

stats_two_failed = web_main._eval_history_stats([
    {"status": "mislukt", "started_at": "2026-09-01T00:00:00+00:00", "ended_at": "2026-09-02T00:00:00+00:00", "closed_reason": "maximaal dagverlies geraakt"},
    {"status": "mislukt", "started_at": "2026-09-01T00:00:00+00:00", "ended_at": "2026-09-05T00:00:00+00:00", "closed_reason": "maximaal dagverlies geraakt"},
])
assert stats_two_failed["avg_days_to_fail"] == 3.0
print("OK: _eval_history_stats berekent het gemiddelde correct vanaf 2 runs")

# --- _eval_coaching_tip: alleen bij een actieve run, gekozen op de meest
# urgente situatie ---
active_run = {"status": "actief"}
assert web_main._eval_coaching_tip(None, 0.0, 0.0, 0.0) is None
assert web_main._eval_coaching_tip({"status": "geslaagd"}, 90.0, 0.0, 0.0) is None
assert web_main._eval_coaching_tip(active_run, 0.0, 0.0, 0.0) is None
tip_limit = web_main._eval_coaching_tip(active_run, 75.0, 0.0, 0.0)
assert tip_limit and "limiet" in tip_limit
tip_goal = web_main._eval_coaching_tip(active_run, 0.0, 0.0, 80.0)
assert tip_goal and "winstdoel" in tip_goal
print("OK: _eval_coaching_tip geeft alleen bij een actieve run en een urgente situatie een tip")

print("ALLE EVAL-PAGINA ROUTE TESTS GESLAAGD")
```

- [ ] **Step 6: Run, verwacht een fout (route/helpers bestaan nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_eval_pagina_routes.py`
Expected: `404` op `/evaluatie` of een `AttributeError`, opgelost door Step 1-4.

- [ ] **Step 7: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_eval_pagina_routes.py`
Expected: alle 9 "OK:"-regels, eindigend met "ALLE EVAL-PAGINA ROUTE TESTS GESLAAGD".

- [ ] **Step 8: Commit**

```bash
git add web/main.py
git commit -m "$(cat <<'EOF'
web/main.py: gedeelde evaluatie-context + GET /evaluatie route

Trekt de bestaande dashboard-contextopbouw uit in _build_eval_context,
gedeeld door het dashboard en de nieuwe evaluatie-pagina. Start/stop
verwijzen voortaan naar /evaluatie in plaats van /dashboard.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 3: Nieuwe pagina `evaluatie.html` + navigatielink + saldografiek

**Files:**
- Create: `web/templates/evaluatie.html`
- Create: `web/static/evaluatie.js`
- Modify: `web/templates/base.html`

**Interfaces:**
- Consumes: `eval_display`, `eval_history`, `eval_day_number`, `eval_daily_loss_used_pct`, `eval_drawdown_used_pct`, `eval_profit_progress_pct`, `eval_daily_results`, `eval_daily_loss_remaining_eur`, `eval_stats`, `eval_coaching_tip`, `balance_curve`, `coins` (Task 2).

Puur UI + client-side grafiek; de structurele aanwezigheid van tekst/HTML is met een scratch-test te toetsen (Step 4), de daadwerkelijke grafiek-rendering hoort bij Task 5's handmatige verificatie.

- [ ] **Step 1: Voeg de navigatielink toe aan `web/templates/base.html`**

Zoek:

```html
    <a href="/uitleg">Uitleg</a>
```

Voeg er direct vóór toe:

```html
    <a href="/evaluatie">Evaluatie</a>
```

- [ ] **Step 2: Maak `web/templates/evaluatie.html`**

```html
{% extends "base.html" %}
{% import "_macros.html" as macros %}
{% block title %}Evaluatie — HesPulse{% endblock %}
{% block content %}

<section style="--i: 0">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted">Test of je discipline en signalen een Kraken Prop-achtige evaluatie zouden overleven, zonder er geld aan uit te geven. Elke oefentrade die je op een coin-pagina neemt terwijl een run actief is, telt automatisch mee.</p>
</section>

{% if eval_display %}
<section class="card {{ 'risk-pulse' if eval_display.status == 'actief' and (eval_daily_loss_used_pct >= 85 or eval_drawdown_used_pct >= 85) else '' }} {{ 'eval-reveal-pass' if eval_display.status == 'geslaagd' else ('eval-reveal-fail' if eval_display.status == 'mislukt' else '') }}" style="--i: 1" id="prop-eval-card">
  <div class="prop-eval-head">
    <span class="muted">€{{ "{:,.0f}".format(eval_display.tier_amount).replace(",", ".") }} tier · dag {{ eval_day_number }}{% if eval_display.status != 'actief' %} · {{ eval_display.status }}{% endif %}</span>
    <span class="mono">€{{ "%.2f"|format(eval_display.current_balance) }}</span>
  </div>

  {% if eval_display.status == 'actief' %}
  <p class="summary-value" style="font-size: 32px; margin: 4px 0 16px;">€{{ "%.2f"|format(eval_daily_loss_remaining_eur) }}
    <span class="summary-label" style="display: inline; font-size: 13px;">ruimte tot dagverlieslimiet</span>
  </p>
  {% if eval_coaching_tip %}
  <p class="correlation-warning">
    <svg class="factor-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    {{ eval_coaching_tip }}
  </p>
  {% endif %}
  {% endif %}

  <div class="risk-gauge">
    <div class="risk-gauge-head"><span class="muted">Dagverlies opgebruikt</span><span class="mono">{{ "%.0f"|format(eval_daily_loss_used_pct) }}%</span></div>
    <div class="risk-gauge-bar">
      <div class="risk-gauge-fill {{ 'risk-high' if eval_daily_loss_used_pct >= 85 else ('risk-mid' if eval_daily_loss_used_pct >= 60 else '') }}"
           style="width: {{ [eval_daily_loss_used_pct, 100] | min }}%"></div>
    </div>
  </div>

  <div class="risk-gauge">
    <div class="risk-gauge-head"><span class="muted">Drawdown opgebruikt</span><span class="mono">{{ "%.0f"|format(eval_drawdown_used_pct) }}%</span></div>
    <div class="risk-gauge-bar">
      <div class="risk-gauge-fill {{ 'risk-high' if eval_drawdown_used_pct >= 85 else ('risk-mid' if eval_drawdown_used_pct >= 60 else '') }}"
           style="width: {{ [eval_drawdown_used_pct, 100] | min }}%"></div>
    </div>
  </div>

  <div class="risk-gauge">
    <div class="risk-gauge-head"><span class="muted">Winstdoel</span><span class="mono">{{ "%.0f"|format(eval_profit_progress_pct) }}%</span></div>
    <div class="risk-gauge-bar">
      <div class="risk-gauge-fill goal-fill" style="width: {{ [eval_profit_progress_pct, 100] | min }}%"></div>
    </div>
  </div>

  {% if eval_daily_results %}
  <div class="prop-eval-days">
    {% for day in eval_daily_results %}
    <span class="heat-cell heat-level-{{ day.level }}" title="{{ day.date }}: €{{ '%.2f'|format(day.value) }}"></span>
    {% endfor %}
  </div>
  {% endif %}

  {% if eval_display.status == 'actief' %}
  <form method="post" action="/evaluatie/stop" class="prop-eval-stop">
    <button type="submit" class="button-reset">Stoppen</button>
  </form>
  {% elif eval_display.closed_reason %}
  <p class="muted" style="font-size: 12px; margin-top: 10px;">{{ eval_display.closed_reason }}</p>
  {% endif %}
</section>

{% if balance_curve|length > 1 %}
<section class="card" style="--i: 2">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3,17 9,11 13,15 21,5"/></svg>Saldoverloop</h2>
  <div id="eval-chart" style="height: 260px;"></div>
</section>
{% endif %}

{% else %}
<section class="card" style="--i: 1">
  <p class="muted">Nog geen evaluatie actief.</p>
  <form method="post" action="/evaluatie/start" class="prop-eval-start">
    <label>Bedrag
      <select name="tier_amount">
        <option value="5000">€5.000</option>
        <option value="10000" selected>€10.000</option>
        <option value="25000">€25.000</option>
        <option value="50000">€50.000</option>
        <option value="100000">€100.000</option>
        <option value="200000">€200.000</option>
      </select>
    </label>
    <label>Winstdoel % <input type="number" name="profit_target_pct" value="8" min="1" max="50" step="0.5" required></label>
    <label>Max drawdown % <input type="number" name="max_drawdown_pct" value="6" min="1" max="50" step="0.5" required></label>
    <button type="submit">Start evaluatie</button>
  </form>
</section>
{% endif %}

<section style="--i: 3">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>Waarom deze regels bestaan</h2>
  <p><strong>Dagverlieslimiet.</strong> Voorkomt dat één slechte dag escaleert tot een grote. De limiet dwingt je te stoppen voordat frustratie de beslissingen gaat sturen, niet nadat het al te laat is.</p>
  <p><strong>Drawdown die nooit reset.</strong> Een goede week mag een slechte maand niet verbergen. Dit dwingt consistentie af over de hele looptijd, niet één geluksdag.</p>
  <p><strong>Geen tijdslimiet.</strong> Druk om op tijd te slagen leidt tot overhaaste trades. Zonder deadline is de enige weg naar slagen daadwerkelijk goed handelen.</p>
</section>

<section style="--i: 4">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>Disciplineregels</h2>
  <ul class="checklist">
    <li>Stop voor de dag na twee verliezen op rij, ook als de limiet nog niet geraakt is. De limiet is een noodrem, geen doel om tegenaan te handelen.</li>
    <li>Bepaal je risico per trade vóór je instapt. Achteraf uitrekenen is rationalisatie, geen risicobeheer.</li>
    <li>Een winstdoel halen in de eerste dagen is geen prestatie om te vieren. Het is een signaal om extra voorzichtig te zijn: het verklaart vaak meer geluk dan proces.</li>
    <li>Een virtuele evaluatie die faalt kost niets. Gebruik dat: test hier het gedrag dat een echte evaluatie zou breken, niet je makkelijkste trades.</li>
  </ul>
</section>

<section style="--i: 5">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>Wat een ervaren trader nooit doet</h2>
  <ul class="checklist">
    <li>Nooit een verloren trade "terugpakken" met een grotere volgende trade. Dat is geen strategie, dat is wraak op de markt.</li>
    <li>Nooit doorhandelen zonder pauze na een limiet die bijna geraakt is. Bijna is het signaal, niet het excuus om door te gaan.</li>
    <li>Nooit de regels aanpassen halverwege een run omdat de huidige regels net in de weg zitten. De regels zijn er juist voor het moment dat ze in de weg zitten.</li>
    <li>Nooit een evaluatie beoordelen op één goede of slechte dag. Consistentie over de hele looptijd is het enige dat telt.</li>
  </ul>
</section>

{% if eval_stats %}
<section style="--i: 6">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>Patronen uit je geschiedenis</h2>
  {% if eval_stats.avg_days_to_pass %}<p>Gemiddeld <strong>{{ "%.1f"|format(eval_stats.avg_days_to_pass) }} dagen</strong> tot een geslaagde run.</p>{% endif %}
  {% if eval_stats.avg_days_to_fail %}<p>Gemiddeld <strong>{{ "%.1f"|format(eval_stats.avg_days_to_fail) }} dagen</strong> tot een mislukte run.</p>{% endif %}
  {% if eval_stats.common_fail_reason %}<p>Meest voorkomende faalreden: <strong>{{ eval_stats.common_fail_reason }}</strong>.</p>{% endif %}
</section>
{% endif %}

{% if eval_history %}
<details class="stats-collapse js-accordion" style="--i: 7">
  <summary class="stats-summary">
    <svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
    <span>Evaluatie geschiedenis</span>
    <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </summary>
  {% for run in eval_history %}
  <div class="long-term-item">
    <span class="badge badge-{{ 'long' if run.status == 'geslaagd' else ('short' if run.status == 'mislukt' else 'status') }}">{{ run.status }}</span>
    <span class="muted mono" style="font-size: 11px;">€{{ "{:,.0f}".format(run.tier_amount).replace(",", ".") }} · {{ run.started_at[:10] }}{% if run.ended_at %} tot {{ run.ended_at[:10] }}{% endif %}</span>
    {% if run.closed_reason %}<p class="muted" style="font-size: 11px; margin: 4px 0 0;">{{ run.closed_reason }}</p>{% endif %}
  </div>
  {% endfor %}
</details>
{% endif %}

<script>
  const evalBalanceCurve = {{ balance_curve | tojson }};
  const evalTierAmount = {{ eval_display.tier_amount | tojson if eval_display else "null" }};
  const evalMaxDrawdownPct = {{ eval_display.max_drawdown_pct | tojson if eval_display else "null" }};
  const evalProfitTargetPct = {{ eval_display.profit_target_pct | tojson if eval_display else "null" }};
  const evalIsActive = {{ (eval_display.status == 'actief') | tojson if eval_display else "false" }};
  const evalDailyLossUsedPct = {{ eval_daily_loss_used_pct | tojson }};
  const evalDrawdownUsedPct = {{ eval_drawdown_used_pct | tojson }};
</script>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4/dist/lightweight-charts.standalone.production.js"></script>
<script src="/static/evaluatie.js"></script>
{% endblock %}
```

- [ ] **Step 3: Maak `web/static/evaluatie.js`**

```javascript
(function () {
  const container = document.getElementById("eval-chart");
  if (!container || typeof evalBalanceCurve === "undefined" || !evalBalanceCurve.length) return;

  const startRect = container.getBoundingClientRect();
  const chart = LightweightCharts.createChart(container, {
    width: Math.round(startRect.width) || window.innerWidth,
    height: Math.round(startRect.height) || 260,
    layout: { background: { color: "#131a1b" }, textColor: "#b7c4c2" },
    grid: { vertLines: { color: "#1c2526" }, horzLines: { color: "#1c2526" } },
    timeScale: { timeVisible: true, borderColor: "#232d2f" },
    rightPriceScale: { borderColor: "#232d2f" },
  });

  // Drawdown-bodem als basiswaarde: een baseline-serie kleurt zichzelf
  // groen boven en rood onder die ene prijs, dus de lijn toont zelf of
  // het saldo aan de veilige of gevaarlijke kant zit, zonder een losse,
  // door de library niet ondersteunde kleurverloop-hack.
  const drawdownFloor = (evalTierAmount && evalMaxDrawdownPct)
    ? evalTierAmount * (1 - evalMaxDrawdownPct / 100)
    : 0;

  const series = chart.addBaselineSeries({
    baseValue: { type: "price", price: drawdownFloor },
    topLineColor: "#33d69f", topFillColor1: "rgba(51, 214, 159, 0.28)", topFillColor2: "rgba(51, 214, 159, 0.05)",
    bottomLineColor: "#f2685c", bottomFillColor1: "rgba(242, 104, 92, 0.05)", bottomFillColor2: "rgba(242, 104, 92, 0.28)",
    lineWidth: 2,
  });

  // LightweightCharts eist strikt oplopende, unieke tijdstippen. Twee
  // trades die toevallig in dezelfde seconde sluiten zouden een reeks
  // met een gelijk of dalend tijdstip opleveren, wat de hele setData()
  // laat falen — vandaar de expliciete "minstens 1 seconde later dan het
  // vorige punt"-correctie, in plaats van aan te nemen dat exit_time
  // altijd al uniek oplopend is.
  let lastTime = -Infinity;
  const points = evalBalanceCurve.map((p) => {
    let t = Math.floor(new Date(p.time).getTime() / 1000);
    if (!Number.isFinite(t)) return null;
    if (t <= lastTime) t = lastTime + 1;
    lastTime = t;
    return { time: t, value: p.balance };
  }).filter(Boolean);

  series.setData(points);

  if (evalTierAmount && evalMaxDrawdownPct) {
    series.createPriceLine({
      price: drawdownFloor,
      color: "#f2685c", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: "max drawdown",
    });
  }
  if (evalTierAmount && evalProfitTargetPct) {
    series.createPriceLine({
      price: evalTierAmount * (1 + evalProfitTargetPct / 100),
      color: "#33d69f", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: "winstdoel",
    });
  }

  chart.timeScale().fitContent();

  new ResizeObserver((entries) => {
    const { width, height } = entries[0].contentRect;
    chart.applyOptions({ width: Math.round(width), height: Math.round(height) || 260 });
  }).observe(container);

  // Ademende vulling in de gevarenzone: canvas-rendering kan niet met
  // CSS-animaties bewogen worden, dus dit gebeurt via een interval dat de
  // opaciteit van de rode vulling laat pulseren — zelfde 85%-drempel als
  // .risk-pulse elders in de app, alleen actief op een lopende run, nooit
  // als het tabblad niet zichtbaar is, en helemaal niet bij
  // prefers-reduced-motion.
  const inDangerZone = evalIsActive && (evalDailyLossUsedPct >= 85 || evalDrawdownUsedPct >= 85);
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let pulseTimer = null;

  function startPulse() {
    if (pulseTimer) return;
    let dim = false;
    pulseTimer = setInterval(() => {
      dim = !dim;
      series.applyOptions({
        bottomFillColor1: dim ? "rgba(242, 104, 92, 0.02)" : "rgba(242, 104, 92, 0.10)",
        bottomFillColor2: dim ? "rgba(242, 104, 92, 0.10)" : "rgba(242, 104, 92, 0.32)",
      });
    }, 1200);
  }
  function stopPulse() {
    if (pulseTimer) { clearInterval(pulseTimer); pulseTimer = null; }
  }

  if (inDangerZone && !reduceMotion) {
    startPulse();
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopPulse();
      else if (inDangerZone && !reduceMotion) startPulse();
    });
  }
})();
```

- [ ] **Step 4: Schrijf een structuur-test in de scratchpad-directory**

Maak `<scratchpad>/test_eval_pagina_html.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-eval-pagina-html-01234567890123"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("evalpaginahtml", security.hash_password("testpass123"), 1000.0, 1.0, "784")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

# --- navigatielink aanwezig op elke pagina ---
resp_dash = client.get("/dashboard")
assert 'href="/evaluatie"' in resp_dash.text
print("OK: navigatiebalk bevat de nieuwe Evaluatie-link")

# --- zonder actieve run: startformulier, geen grafiek-sectie ---
resp0 = client.get("/evaluatie")
assert resp0.status_code == 200
assert "Start evaluatie" in resp0.text
assert 'id="eval-chart"' not in resp0.text
assert "Waarom deze regels bestaan" in resp0.text
assert "Disciplineregels" in resp0.text
assert "Wat een ervaren trader nooit doet" in resp0.text
print("OK: /evaluatie zonder actieve run toont het startformulier en de uitleg/tips, geen grafiek")

# --- met een actieve run en minstens 2 gesloten trades: grafiek-sectie aanwezig ---
eval_id = repo.create_evaluation(uid, tier_amount=10000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)
with db.session() as conn:
    conn.execute("INSERT INTO messages (received_at, raw_text) VALUES (?, 'test')", (db.now_iso(),))
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
signal_id = repo.insert_signal({
    "message_id": msg_id, "coin": "TAO", "direction": "long", "category": "oefening",
    "price": 100.0, "rsi": 50, "macd": 0, "macd_signal": 0, "volume_ratio": 1,
    "ema9": 100, "ema21": 100, "atr": 5, "atr_avg20": 5, "adx": 20,
    "technical_confirmed": 1, "confidence": "hoog vertrouwen", "reason": "test",
    "stop_loss": 90.0, "take_profit": 120.0, "context_note": None,
    "is_practice": 1, "plain_explanation": None,
})
entry_id = repo.create_journal_entry(signal_id, uid, risk_eur=100.0, evaluation_id=eval_id)
with db.session() as conn:
    conn.execute(
        "UPDATE journal_entries SET exit_price = 105, exit_time = ?, result_eur = 50 WHERE id = ?",
        (db.now_iso(), entry_id),
    )

resp1 = client.get("/evaluatie")
assert resp1.status_code == 200
assert 'id="eval-chart"' in resp1.text
assert "ruimte tot dagverlieslimiet" in resp1.text
assert "/static/evaluatie.js" in resp1.text
print("OK: /evaluatie met een actieve run en gesloten trades toont de grafiek-sectie")

# --- coaching-tip verschijnt zodra het winstdoel dichtbij komt ---
repo.update_evaluation_state(eval_id, current_balance=10750.0, day_start_balance=10750.0, day_start_date=repo.get_evaluation(eval_id)["day_start_date"])
resp2 = client.get("/evaluatie")
assert "Dit is precies het moment waarop mensen hun regels laten verslappen" in resp2.text
print("OK: coaching-tip verschijnt zodra het winstdoel dichtbij is")

print("ALLE EVAL-PAGINA HTML TESTS GESLAAGD")
```

- [ ] **Step 5: Run, verwacht een gemiste assert (route bestaat nog niet met deze template)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_eval_pagina_html.py`
Expected: faalt (template ontbreekt of geeft een 500), opgelost door Step 1-3.

- [ ] **Step 6: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_eval_pagina_html.py`
Expected: alle 4 "OK:"-regels, eindigend met "ALLE EVAL-PAGINA HTML TESTS GESLAAGD".

- [ ] **Step 7: Commit**

```bash
git add web/templates/evaluatie.html web/static/evaluatie.js web/templates/base.html
git commit -m "$(cat <<'EOF'
Nieuwe evaluatie-pagina: saldografiek, uitleg, disciplineregels

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 4: Dashboard-kaart inkorten tot samenvatting

**Files:**
- Modify: `web/templates/dashboard.html`
- Test: `<scratchpad>/test_dashboard_eval_teaser.py`

**Interfaces:**
- Consumes: `eval_display` (Task 2, ongewijzigd qua vorm).

- [ ] **Step 1: Vervang het volledige evaluatie-blok door een samenvatting**

Zoek in `web/templates/dashboard.html` het hele blok van `{% if eval_display %}` (de sectie met `id="prop-eval-card"`) tot en met de sluitende `{% endif %}` van de geschiedenis-`<details>` (dus het volledige blok dat nu de drie balken, dag-stippen, start/stop-formulieren én de geschiedenis-accordion bevat — alles wat in Task 3 naar `evaluatie.html` is gekopieerd). Vervang dat hele blok door:

```html
{% if eval_display %}
<section class="card" style="--i: 1">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted" style="margin: 0 0 6px;">€{{ "{:,.0f}".format(eval_display.tier_amount).replace(",", ".") }} tier · €{{ "%.2f"|format(eval_display.current_balance) }}{% if eval_display.status != 'actief' %} · {{ eval_display.status }}{% endif %}</p>
  <a href="/evaluatie">Bekijk evaluatie →</a>
</section>
{% else %}
<section class="card" style="--i: 1">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted">Nog geen evaluatie actief.</p>
  <a href="/evaluatie">Start een evaluatie →</a>
</section>
{% endif %}
```

- [ ] **Step 2: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_dashboard_eval_teaser.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-dashboard-eval-teaser-012345678901"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("dashteaseruser", security.hash_password("testpass123"), 1000.0, 1.0, "785")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp0 = client.get("/dashboard")
assert "Nog geen evaluatie actief" in resp0.text
assert 'href="/evaluatie"' in resp0.text
assert "Start evaluatie" not in resp0.text
assert 'id="prop-eval-card"' not in resp0.text
print("OK: dashboard toont zonder actieve run alleen de samenvatting, geen formulier")

repo.create_evaluation(uid, tier_amount=10000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)
resp1 = client.get("/dashboard")
assert "Bekijk evaluatie" in resp1.text
assert "€10.000 tier" in resp1.text
assert "Dagverlies opgebruikt" not in resp1.text
assert 'id="prop-eval-card"' not in resp1.text
print("OK: dashboard toont met een actieve run alleen de samenvatting, geen balken")

print("ALLE DASHBOARD-EVAL-TEASER TESTS GESLAAGD")
```

- [ ] **Step 3: Run, verwacht een gemiste assert (het oude volledige blok staat er nog)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_dashboard_eval_teaser.py`
Expected: `AssertionError` op `"Dagverlies opgebruikt" not in resp1.text`, opgelost door Step 1.

- [ ] **Step 4: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_dashboard_eval_teaser.py`
Expected: beide "OK:"-regels, eindigend met "ALLE DASHBOARD-EVAL-TEASER TESTS GESLAAGD".

- [ ] **Step 5: Commit**

```bash
git add web/templates/dashboard.html
git commit -m "$(cat <<'EOF'
Dashboard: evaluatie-kaart ingekort tot samenvatting met link

De volledige weergave (balken, grafiek, uitleg, geschiedenis) staat nu
op de eigen /evaluatie-pagina.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 5: Handmatige visuele verificatie

**Files:**
- Geen codewijzigingen. Verificatie-only met Playwright, chromium op `/opt/pw-browsers/chromium` (al aanwezig, geen `playwright install`).

- [ ] **Step 1: Start de app tegen een scratch-database**

```bash
DATABASE_PATH=/tmp/prop_eval_pagina_check.db JWT_SECRET=test-secret-eval-pagina-ui-0123456789012345 \
  uvicorn web.main:app --reload
```

- [ ] **Step 2: Maak een gebruiker, een actieve run, en minstens 3 gesloten gekoppelde trades met verschillende resultaten**

Gebruik een Python-shell of een klein script (hergebruik het patroon uit `test_eval_pagina_html.py`) om in te loggen via de browser en de saldo-curve genoeg variatie te geven om zichtbaar te zijn (bijvoorbeeld: +150, -80, +220).

- [ ] **Step 3: Verifieer de navigatie**

Klik op "Evaluatie" in de navigatiebalk vanaf het dashboard. Controleer dat de URL naar `/evaluatie` gaat en de pagina laadt zonder consolefouten (`page.on("console")`/`page.on("pageerror")`).

- [ ] **Step 4: Verifieer de saldografiek**

Controleer dat `#eval-chart` een canvas bevat (LightweightCharts rendert op canvas), dat de lijn zichtbaar oploopt/daalt met de ingevoerde resultaten, en dat er twee gestippelde horizontale lijnen zichtbaar zijn (rood onder, groen boven — de drawdown-bodem en het winstdoel). Controleer dat het gedeelte van de lijn boven de drawdown-bodem groen gevuld is en het gedeelte eronder (indien aanwezig in je testdata) rood. Maak een screenshot: `eval_pagina_chart.png`.

- [ ] **Step 4b: Verifieer de ademende vulling in de gevarenzone**

Maak een run waarbij dagverlies of drawdown boven de 85%-drempel zit (zelfde aanpak als de bestaande tension-verificatie voor de dashboard-kaart). Herlaad `/evaluatie` en controleer met herhaalde `getComputedStyle`/canvas-sampling of series-opties-inspectie dat de rode vulling onder de basislijn zichtbaar van opaciteit wisselt over een paar seconden (niet statisch). Verifieer ook dat dit stopt zodra je het tabblad verbergt (`page.evaluate` om `document.hidden` te simuleren, of het tabblad daadwerkelijk wisselen) en dat het met `page.emulate_media(reduced_motion="reduce")` helemaal niet start.

- [ ] **Step 4c: Verifieer de coaching-tip en de nieuwe sectie**

Controleer dat de coaching-tip verschijnt wanneer je testdata dicht bij een limiet of het winstdoel zit (zoek de tekst "Overweeg te stoppen" of "regels laten verslappen"), en afwezig is bij een run zonder bijzondere status. Controleer dat de sectie "Wat een ervaren trader nooit doet" op de pagina staat, met de vier regels leesbaar.

- [ ] **Step 5: Verifieer de dashboard-samenvatting**

Ga terug naar `/dashboard`. Controleer dat de evaluatie-kaart nu alleen tier, saldo, status en een link toont, geen balken of formulieren. Maak een screenshot: `dashboard_eval_teaser.png`.

- [ ] **Step 6: Verifieer dat het geslaagd/mislukt-reveal nog werkt, nu op de nieuwe pagina**

Sluit een gekoppelde trade met een winst die het winstdoel haalt (via de coin-pagina, zoals een echte gebruiker). Volg de redirect (die gaat naar de pagina waar het formulier op stond, bijvoorbeeld de coin-pagina of het dashboard, afhankelijk van `next`). Navigeer daarna naar `/evaluatie` en controleer dat het geslaagd-reveal daar afspeelt (groene puls, eenmalig, zoals eerder al geverifieerd voor de dashboard-kaart). Maak een screenshot: `eval_pagina_geslaagd.png`.

- [ ] **Step 7: Verifieer `prefers-reduced-motion` op de nieuwe pagina**

Herhaal Step 6 met `page.emulate_media(reduced_motion="reduce")`. Controleer dat de puls niet afspeelt, alleen de eindstaat direct zichtbaar is.

- [ ] **Step 8: Rapporteer**

Vat kort samen wat bevestigd is, met de screenshots als bewijs. Geen commit nodig.

---

## Self-Review

**Spec coverage:**
- Navigatielink + dashboard-samenvatting → Task 3 (link), Task 4 (samenvatting). ✓
- Statuskop met uitgelicht kerngetal (resterende dagbudget) → Task 2 (`eval_daily_loss_remaining_eur`), Task 3 (template). ✓
- Echte saldografiek met drawdown-/winstdoel-niveaus → Task 1 (data), Task 3 (LightweightCharts). ✓
- Uitleg waarom de regels bestaan → Task 3. ✓
- Disciplineregels → Task 3. ✓
- Geschiedenis met patronen (gemiddelde dagen, meest voorkomende faalreden) → Task 2 (`_eval_history_stats`), Task 3 (template). ✓
- Niet-doelen (geen wijziging aan risk.py, aan de regel-logica, aan de koppeling van oefentrades) → geen enkele taak raakt `app/risk.py` of de bestaande koppel-logica in `create_practice_trade`/`close_journal`. ✓
- Vier gekozen creatieve uitbreidingen (kleurindicatie via baseline-serie, ademende vulling in de gevarenzone, statusafhankelijke coaching-tip, sectie "wat een ervaren trader nooit doet") → allemaal in Task 2 (`_eval_coaching_tip`) en Task 3 (template + `evaluatie.js`), elk met een technisch haalbare, aan echte waarden gekoppelde en `prefers-reduced-motion`-respecterende invulling, zoals vastgelegd in de spec-aanvulling. ✓

**Placeholder scan:** geen "TBD"/"implement later"/ongeschreven testcode gevonden bij het doorlopen van elke taak.

**Type-consistentie:** `_build_eval_context`'s return-dict-sleutels (Task 2) zijn exact wat zowel `dashboard.html` (Task 4, alleen `eval_display` gebruikt) als `evaluatie.html` (Task 3, alle sleutels gebruikt) verwachten. `list_evaluation_balance_curve`'s itemvorm (`{"time": str, "balance": float}`, Task 1) is exact wat `evaluatie.js` (Task 3) verwerkt. `_eval_history_stats`'s return-vorm (`None` of een dict met drie optionele sleutels) wordt in de template correct met `{% if %}` per sleutel afgehandeld, nooit aangenomen dat alle drie aanwezig zijn.
