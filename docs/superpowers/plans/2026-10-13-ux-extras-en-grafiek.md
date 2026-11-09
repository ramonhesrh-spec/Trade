# UX-extra's en grafiek Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acht kleine functies (verversen, tab naar boven, pauzeknop, prijsalarm, kopieer met een tik, appicoon-badge, versheidsstip, meldingenbanner) en zes beelden (risico- en beloningsvlak, afstandsbalk, minigrafiek, budgetring, resultaatcurve, uurkaart) in één ronde bouwen.

**Architecture:** Elke berekening staat in een pure functie in `app/` (bestaande modules `radar.py`, `trade_plan.py`, `today.py`, `track_record.py`, `push_policy.py`, `chance_steps.py`, plus twee nieuwe kleine modules `app/freshness.py` en `app/price_alerts.py`) met een stdlib-unittest. `web/main.py` levert die uitkomsten aan templates en JSON-routes; de JS-bestanden in `web/static/` vullen alleen in. Nieuwe opslag: kolom `users.push_paused_until` en tabel `price_alerts`.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, SQLite (WAL), vanilla JS, lightweight-charts 4.2.0 (al aanwezig), stdlib unittest, node (alleen `node --check` en de bestaande harness-stijl in `tests/js/`), Playwright (al geïnstalleerd) voor handmatige controles.

**Spec:** Er is geen apart specdocument. De goedgekeurde lijst uit het gesprek van 2026-10-13 is hieronder letterlijk overgenomen en geldt als spec:

- F1 Pull-to-refresh op Radar en Vandaag (vanilla JS, ververst data zonder volledige herlaadslag waar mogelijk, anders location.reload).
- F2 Tik op het icoon van de actieve tab scrolt naar boven (tabbar).
- F3 Pauzeknop voor meldingen: een tik zet alle pushes en Telegram 2 uur stil. Per gebruiker opgeslagen (schema.sql plus idempotente migratie in db._migrate, repo functies, check in het push/telegram verzendpad, knop in UI met resterende tijd). Signalen blijven wel in het journaal.
- F4 Prijsalarm vanaf een Radar-kaart: tik op een niveau, melding zodra de prijs er is. Nieuwe tabel price_alerts per gebruiker, check in app/level_check.py (fire once, sent-flag), endpoint in web/main.py, UI.
- F5 Kopieer met een tik: tik op instap, stop of doel op een kaart en het getal staat op het klembord, met korte bevestiging.
- F6 Appicoon-badge met het aantal kansen die nu in de zone staan (Badging API via navigator.setAppBadge waar ondersteund, vanuit pagina en/of service worker push; val netjes terug).
- F7 Stip bij verouderde data: is de prijs ouder dan 2 minuten, kleurt een kleine stip oranje.
- F8 Banner 'Meldingen staan uit op dit apparaat' met knop om ze aan te zetten (bestaande push-subscribe code).
- G1 Rood vlak tussen instap en stop en groen vlak tussen instap en doel op de candle chart (levelchart.js).
- G2 Afstandsbalk op elke Radar-kaart: dunne lijn met stip voor huidige prijs richting de instap.
- G3 Minigrafiek (laatste 24u) per kaart uit de bestaande candle-cache, één batch-aanroep, geen beursaanroep per kaart.
- G4 Ring op Vandaag: meldingen tegenover het dagbudget (standaard 6).
- G5 Resultaatcurve op Bewijs: cumulatieve R per soort met terugval-schaduw, alleen take_profit/stop_loss tellen, pure functie in app/track_record.py met unittest.
- G6 Uurkaart op Bewijs: raster uur x weekdag met gemiddelde R per cel en aantal trades, cellen onder een minimum n zwak/leeg.

## Global Constraints

- UI-tekst in het Nederlands, kort, nooit een em dash (`—`) in nieuwe tekst.
- Geen nieuwe pip-dependencies. Geen nieuwe JS-bibliotheken.
- Pure logica in `app/`-modules met een stdlib-unittest in `tests/`. Templates rekenen niet: alleen opmaak (`"%.1f"|format`) en lussen.
- Commentaar legt alleen het waarom uit (een valkuil, een afweging), nooit wat de code doet.
- Elk beeld hangt aan een gemeten waarde (koers, plan-niveau, afgeronde uitkomst, verstuurde push). Animatie alleen als overgang van een echte waarde, en altijd uit onder `@media (prefers-reduced-motion: reduce)`.
- Schemawijziging aan een bestaande tabel: `app/schema.sql` én een `PRAGMA table_info`-gegarandeerde `ALTER TABLE` in `app/db.py:_migrate()`. Een geheel nieuwe tabel staat alleen in `schema.sql` (`CREATE TABLE IF NOT EXISTS` bereikt ook bestaande databases); zijn index mag daar ook, want alle kolommen bestaan vanaf het begin.
- Database alleen via `app/repo.py`; geen SQL in `web/main.py` of `app/level_check.py`.
- "Fire once": een alarm wordt eerst als verstuurd gemarkeerd en pas daarna verstuurd, zodat een fout bij versturen nooit elke 15 minuten herhaalt.
- Bewijs blijft eerlijk: alleen `take_profit`/`stop_loss` tellen in R en curve (via `track_record.signal_r`/`live_net_r`), open en vervallen staan als aantal ernaast. Oefentrades doen niet mee (`repo.list_signals_for_quality_report` filtert ze al) en de rijen komen altijd uit `report_rows(user)` (CEO-only soorten blijven weg voor leerlingen).
- Telegram bestaat niet meer als verzendkanaal (verwijderd in Taak 11, alles loopt via `app/push_notify.py`). De pauze van F3 zit daarom in `push_notify.send_push` en `push_notify.send_kans_push`; het journaal (`journal_entries`) wordt nergens door de pauze geraakt.
- Dagbudget: `push_policy.DEFAULT_BUDGET` (6) is de bron, geen tweede constante in `config.py`.
- Versheidsgrens: `freshness.STALE_AFTER_S = 120` is de enige bron; de pagina leest hem uit een data-attribuut.
- Na elke taak groen: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
- Raak `app/setup_eval.py` en `app/smc_eval.py` niet aan.
- Elk gewijzigd JS-bestand: `node --check web/static/<bestand>.js` moet zonder uitvoer slagen.

### Controle-opzet tegen een scratch DB (voor de handmatige en Playwright-stappen)

Kies een map buiten de repo als `$SCRATCH` (bijvoorbeeld de scratchpad van je sessie). Eenmalig per taak die een UI-controle heeft:

```bash
export SCRATCH=${SCRATCH:-$(mktemp -d)}
rm -f "$SCRATCH/ui.db"*
DATABASE_PATH="$SCRATCH/ui.db" python3 - <<'EOF'
from datetime import datetime, timedelta, timezone
from app import db, repo, security
db.init_db()
repo.create_user("demo", security.hash_password("wachtwoord-123456"), 0, 1)
now = datetime.now(timezone.utc)
with db.session() as conn:
    for coin, lo, hi, sweep, target in (("BTC", 60000, 60500, 59500, 70000), ("ETH", 2480, 2520, 2450, 2700)):
        conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                        created_at, updated_at) VALUES (?, 'long', ?, ?, ?, ?, ?, 10, ?, ?)""",
                     (coin, lo, hi, hi * 1.01, sweep, target, now.isoformat(), now.isoformat()))
    for i in range(40):
        at = now - timedelta(hours=7 * i + 3)
        outcome = ("take_profit", "stop_loss", "stop_loss", None, "vervallen")[i % 5]
        conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                        take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                        VALUES (NULL, 'SOL', 'long', 'x', 'hoog', 1, 100, 99, 102, ?, ?, ?, ?)""",
                     ("smc" if i % 2 else "structuur", outcome, (at + timedelta(hours=1)).isoformat() if outcome else None, at.isoformat()))
EOF
```

Nagebootste beurs (de sandbox bereikt Binance niet altijd; `web/main.py` en `app/level_check.py` gebruiken `exchange.<functie>` op het moment van aanroepen, dus vervangen bij het importeren van dit bestand werkt). Sla op als `$SCRATCH/ui_fake.py`:

```python
import math
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, ".")
from app import exchange

PRICES = {"BTC": 60800.0, "ETH": 2500.0, "SOL": 150.0, "BNB": 600.0, "AVAX": 30.0, "DOGE": 0.2, "SUI": 3.0}


def fake_price(coin):
    return PRICES.get(coin, 100.0)


def fake_ohlcv(coin, timeframe="15m", limit=100, since=None):
    step = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}.get(timeframe, 15)
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base = PRICES.get(coin, 100.0)
    rows = []
    for i in range(limit):
        c = base * (1 + 0.01 * math.sin(i / 6))
        rows.append({"timestamp": pd.Timestamp(end - timedelta(minutes=step * (limit - i))), "open": c, "high": c * 1.002,
                     "low": c * 0.998, "close": c, "volume": 1.0})
    return pd.DataFrame(rows)


exchange.fetch_last_price = fake_price
exchange.fetch_ohlcv = fake_ohlcv
```

Server, sla op als `$SCRATCH/ui_server.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_fake  # noqa: F401,E402  (vervangt de beurs vóór web.main geladen wordt)
import uvicorn  # noqa: E402

from web import main  # noqa: E402

uvicorn.run(main.app, host="127.0.0.1", port=8765)
```

Starten vanuit de repo-root: `DATABASE_PATH="$SCRATCH/ui.db" python3 "$SCRATCH/ui_server.py" &` en na de controle `kill %1`.

Playwright-helper, sla op als `$SCRATCH/ui_login.py`:

```python
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def open_page(pw, path, mobile=True):
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 900}, has_touch=mobile)
    page = ctx.new_page()
    page.goto(BASE + "/login")
    page.fill("input[name=username]", "demo")
    page.fill("input[name=password]", "wachtwoord-123456")
    page.click("form[action='/login'] button[type=submit]")
    page.wait_for_load_state()
    page.goto(BASE + path)
    page.wait_for_load_state("networkidle")
    return browser, ctx, page
```

Elke controle hieronder is een los script `python3 $SCRATCH/check_<n>.py` dat begint met `import sys; sys.path.insert(0, "<$SCRATCH>"); from ui_login import open_page, BASE` en `from playwright.sync_api import sync_playwright`.

## Bestandsoverzicht

| Bestand | Verantwoordelijkheid in dit plan |
|---|---|
| `app/push_policy.py` | Pauzeduur en resterende minuten (F3) |
| `app/push_notify.py` | Pauze in het verzendpad (F3), `badge` in de payload (F6) |
| `app/price_alerts.py` (nieuw) | Kant van het alarm, eerste treffer, meldingstekst (F4) |
| `app/freshness.py` (nieuw) | Leeftijd van de oudste getoonde koers (F7) |
| `app/chance_steps.py` | `level_chips` voor kopieer- en alarmknoppen (F5, F4) |
| `app/radar.py` | `levels`, `in_zone_count`, `approach_pct`, `spark` (F5, F6, G2, G3) |
| `app/trade_plan.py` | `approach_pct` (G2) |
| `app/today.py` | `levels` per scenario, `budget_ring` (F5, G4) |
| `app/track_record.py` | `equity_curves`, `equity_svg`, `hour_grid` (G5, G6) |
| `app/notifications_view.py` | Label voor het type `prijsalarm` (F4) |
| `app/schema.sql`, `app/db.py`, `app/repo.py` | `users.push_paused_until`, tabel `price_alerts`, tellers |
| `app/level_check.py` | `check_price_alerts` (F4) |
| `app/market_scanner.py` | `badge` bij de zone-melding (F6) |
| `web/main.py` | Routes en context voor alle functies |
| `web/templates/base.html`, `_macros.html`, `smc.html`, `vandaag.html`, `bewijs.html`, `account.html` | Markup |
| `web/static/pause.js`, `copy.js`, `alarm.js`, `stale.js`, `push-banner.js`, `spark.js` (nieuw) | Gedrag per functie |
| `web/static/radar.js`, `vandaag.js`, `smooth.js`, `tabbar.js`, `levelchart.js`, `push-subscribe.js`, `service-worker.js`, `style.css` | Uitbreidingen |
| `tests/test_web_extras.py` (nieuw), `tests/test_price_alerts.py` (nieuw), `tests/test_freshness.py` (nieuw), `tests/test_static_js.py` (nieuw), `tests/js/*.js` (nieuw) | Tests |

---

### Task 1: Pauze voor meldingen, opslag en verzendpad (F3 backend)

**Files:**
- Modify: `app/schema.sql:25` (users, na `push_budget INTEGER,`)
- Modify: `app/db.py:192-193` (na de `push_budget`-migratie)
- Modify: `app/repo.py:1804-1806` (na `set_push_budget`)
- Modify: `app/push_policy.py`
- Modify: `app/push_notify.py:58-120`
- Test: `tests/test_push_policy.py`

**Interfaces:**
- Consumes: niets uit eerdere taken.
- Produces:
  - `push_policy.PAUSE_HOURS: int = 2`
  - `push_policy.pause_until(now: datetime) -> datetime`
  - `push_policy.pause_minutes_left(paused_until: Optional[str], now: datetime) -> int`
  - `push_policy.pause_text(minutes_left: int) -> str` ("Pauze" of "Stil 1:43")
  - `repo.set_push_pause(user_id: int, until: Optional[str]) -> None`
  - kolom `users.push_paused_until TEXT` (ISO, UTC)

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_push_policy.py` (boven `if __name__ == "__main__":`), en zet bovenaan bij de imports `from app import config, db, push_notify, push_policy, repo`:

```python
class PauseRuleTest(unittest.TestCase):
    def test_minutes_left_rounds_up_and_ends_at_zero(self):
        self.assertEqual(push_policy.pause_minutes_left(None, NOW), 0)
        self.assertEqual(push_policy.pause_minutes_left("", NOW), 0)
        self.assertEqual(push_policy.pause_minutes_left("onzin", NOW), 0)
        self.assertEqual(push_policy.pause_minutes_left(push_policy.pause_until(NOW).isoformat(), NOW), 120)
        self.assertEqual(push_policy.pause_minutes_left((NOW + timedelta(seconds=30)).isoformat(), NOW), 1)
        self.assertEqual(push_policy.pause_minutes_left((NOW - timedelta(minutes=1)).isoformat(), NOW), 0)
        naive = (NOW + timedelta(minutes=10)).replace(tzinfo=None).isoformat()          # oude rijen zonder tijdzone gelden als UTC
        self.assertEqual(push_policy.pause_minutes_left(naive, NOW), 10)

    def test_text(self):
        self.assertEqual(push_policy.pause_text(0), "Pauze")
        self.assertEqual(push_policy.pause_text(120), "Stil 2:00")
        self.assertEqual(push_policy.pause_text(43), "Stil 0:43")


class PauseSendTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        repo.upsert_push_subscription(self.uid, "https://push.test/1", "p256", "auth")
        self.sent = []
        for patcher in (mock.patch.object(config, "VAPID_PRIVATE_KEY", "sleutel"),
                        mock.patch.object(push_notify, "_send_one", lambda sub, payload: self.sent.append(payload))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def pause(self, minutes):
        repo.set_push_pause(self.uid, (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat())

    def test_pause_holds_back_every_push_until_it_ends(self):
        self.pause(120)
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(self.sent, [])
        repo.set_push_pause(self.uid, None)
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(len(self.sent), 1)

    def test_expired_pause_lets_pushes_through(self):
        self.pause(-1)
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(len(self.sent), 1)

    def test_paused_chance_becomes_quiet_notification_and_does_not_use_the_budget(self):
        self.pause(60)
        self.assertFalse(asyncio.run(push_notify.send_kans_push(self.uid, "BTC", "long", "BTC long", "body", "/kans/1")))
        self.assertEqual(self.sent, [])
        with db.session() as conn:
            body = conn.execute("SELECT body FROM notifications WHERE user_id = ?", (self.uid,)).fetchone()["body"]
        self.assertIn("pauze", body)
        self.assertEqual(repo.list_recent_pushes(self.uid, "2000-01-01T00:00:00+00:00"), [])

    def test_column_exists_and_migration_is_idempotent(self):
        with db.session() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        self.assertIn("push_paused_until", cols)
        db.init_db()                                                             # tweede keer: idempotent
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_push_policy -v`
Expected: FAIL/ERROR met `AttributeError: module 'app.push_policy' has no attribute 'pause_minutes_left'` en `'app.repo' has no attribute 'set_push_pause'`.

- [ ] **Step 3: Schema en migratie**

In `app/schema.sql`, in `CREATE TABLE IF NOT EXISTS users`, direct na `push_budget INTEGER,`:

```sql
    -- Pauzeknop (F3): tot dit moment (ISO, UTC) gaan er geen pushes naar deze gebruiker. NULL = geen pauze. Signalen en het journaal lopen gewoon door.
    push_paused_until TEXT,
```

In `app/db.py:_migrate`, direct na de `push_budget`-guard:

```python
    if "push_paused_until" not in existing_users:
        conn.execute("ALTER TABLE users ADD COLUMN push_paused_until TEXT")
```

- [ ] **Step 4: Repo-functie**

In `app/repo.py`, direct na `set_push_budget`:

```python
def set_push_pause(user_id: int, until: Optional[str]) -> None:
    with db.session() as conn:
        conn.execute("UPDATE users SET push_paused_until = ? WHERE id = ?", (until, user_id))
```

- [ ] **Step 5: Pauzeregel in `app/push_policy.py`**

Imports bovenaan worden:

```python
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
```

Onderaan toevoegen:

```python
PAUSE_HOURS = 2


def pause_until(now: datetime) -> datetime:
    return now + timedelta(hours=PAUSE_HOURS)


def pause_minutes_left(paused_until: Optional[str], now: datetime) -> int:
    """Hele minuten tot de pauze afloopt, naar boven afgerond, zodat de knop nooit "0" toont terwijl hij nog stil is."""
    if not paused_until:
        return 0
    try:
        until = datetime.fromisoformat(paused_until)
    except ValueError:
        return 0
    until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
    seconds = (until - now).total_seconds()
    return math.ceil(seconds / 60) if seconds > 0 else 0


def pause_text(minutes_left: int) -> str:
    if minutes_left <= 0:
        return "Pauze"
    return f"Stil {minutes_left // 60}:{minutes_left % 60:02d}"
```

- [ ] **Step 6: Pauze in het verzendpad**

In `app/push_notify.py`: verander `from datetime import datetime` in `from datetime import datetime, timedelta, timezone` en voeg `push_policy` toe aan `from app import config, push_policy, repo`. Haal de lokale imports `from datetime import timedelta, timezone` en `from app import push_policy` uit `send_kans_push` weg.

In `send_push`, direct na het `VAPID_PRIVATE_KEY`-blok:

```python
    user = repo.get_user(user_id) or {}
    if push_policy.pause_minutes_left(user.get("push_paused_until"), datetime.now(timezone.utc)):
        logger.info("Push voor gebruiker %s overgeslagen: meldingen staan op pauze", user_id)
        return
```

In `send_kans_push`, direct na `user = repo.get_user(user_id) or {}`:

```python
    if push_policy.pause_minutes_left(user.get("push_paused_until"), now):
        # Telt niet mee voor het dagbudget: wie pauzeert, heeft na de pauze zijn volle budget nog.
        repo.create_notification(user_id, "kans", title, f"{body}\nMeldingen stonden op pauze, daarom geen push.", url)
        return False
```

- [ ] **Step 7: Draai de tests**

Run: `python3 -m unittest tests.test_push_policy -v`
Expected: PASS (alle bestaande tests ook).

- [ ] **Step 8: Volledige suite en commit**

Run: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
Expected: OK

```bash
git add app/schema.sql app/db.py app/repo.py app/push_policy.py app/push_notify.py tests/test_push_policy.py
git commit -m "Pauze voor meldingen: twee uur geen pushes, per gebruiker opgeslagen"
```

---

### Task 2: Pauzeknop in de bovenbalk (F3 UI)

**Files:**
- Modify: `web/main.py` (imports regel 32; template-globals na regel 112; nieuwe routes na `api_push_subscribe`, rond regel 1186)
- Modify: `web/templates/base.html:255-256` (in `.topbar-right`, vóór `<span class="live-pill">`) en de scriptlijst onderaan (regel 918-928)
- Create: `web/static/pause.js`
- Modify: `web/static/style.css` (token `--amber` in `:root` na `--red-bg`, regels onderaan)
- Create: `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `push_policy.pause_until`, `pause_minutes_left`, `pause_text`, `repo.set_push_pause` (Task 1).
- Produces:
  - `GET /api/push/pauze` en `POST /api/push/pauze` -> `{"paused_until": str|None, "minutes_left": int, "label": str}` (POST schakelt om)
  - CSS-token `--amber: #f2b33d` (gebruikt door Task 7 en 13)
  - `tests/test_web_extras.py` met basisklasse `WebCase` (attributen `self.main`, `self.client`, `self.uid`; koers gemockt op 100.0) voor latere taken

- [ ] **Step 1: Schrijf de falende tests**

Create `tests/test_web_extras.py`:

```python
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import config, db, repo, security


class WebCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(config, "DATABASE_PATH", os.path.join(self.tmp.name, "w.db"))
        self.patch.start()
        db.init_db()
        from web import main
        self.main = main
        main._price_cache.clear()
        self.client = TestClient(main.app)
        self.uid = repo.create_user("tester", security.hash_password("wachtwoord-123456"), 1000.0, 1.0)
        self.client.cookies.set(main.SESSION_COOKIE, security.create_session_token(self.uid))
        self.prices = mock.patch.object(main.exchange, "fetch_last_price", side_effect=lambda coin: 100.0)
        self.prices.start()

    def tearDown(self):
        self.prices.stop()
        self.patch.stop()
        self.tmp.cleanup()


class PauseRouteTest(WebCase):
    def test_toggle_sets_two_hours_and_a_second_tap_ends_it(self):
        self.assertEqual(self.client.get("/api/push/pauze").json(), {"paused_until": None, "minutes_left": 0, "label": "Pauze"})
        on = self.client.post("/api/push/pauze").json()
        self.assertEqual(on["minutes_left"], 120)
        self.assertEqual(on["label"], "Stil 2:00")
        self.assertIsNotNone(repo.get_user(self.uid)["push_paused_until"])
        off = self.client.post("/api/push/pauze").json()
        self.assertEqual(off["minutes_left"], 0)
        self.assertIsNone(repo.get_user(self.uid)["push_paused_until"])

    def test_button_shows_remaining_time_on_every_page(self):
        r = self.client.get("/bewijs")
        self.assertIn('id="push-pause"', r.text)
        self.assertIn(">Pauze<", r.text)
        self.client.post("/api/push/pauze")
        r = self.client.get("/bewijs")
        self.assertIn("Stil 2:00", r.text)
        self.assertIn('aria-pressed="true"', r.text)
        self.assertIn("pause.js", r.text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_web_extras -v`
Expected: FAIL (404 op `/api/push/pauze`, `push-pause` niet in de pagina).

- [ ] **Step 3: Routes en template-globals in `web/main.py`**

Voeg `push_policy` toe aan de import op regel 32 (`from app import config, db, exchange, indicators, market_calendar, notifications_view, push_notify, push_policy, radar, repo, ...`).

Na `templates.env.globals["live_quote"] = ...`:

```python
templates.env.globals["pause_minutes_left"] = lambda u: push_policy.pause_minutes_left((u or {}).get("push_paused_until"), datetime.now(timezone.utc))
templates.env.globals["pause_text"] = push_policy.pause_text
```

Na `api_push_subscribe`:

```python
def _pause_state(user: dict) -> dict:
    left = push_policy.pause_minutes_left(user.get("push_paused_until"), datetime.now(timezone.utc))
    return {"paused_until": user.get("push_paused_until") if left else None, "minutes_left": left, "label": push_policy.pause_text(left)}


@app.get("/api/push/pauze")
async def api_push_pause_state(user: dict = Depends(require_login)):
    return _pause_state(user)


@app.post("/api/push/pauze")
async def api_push_pause_toggle(user: dict = Depends(require_login)):
    """Eén tik: twee uur geen pushes. Een tik tijdens de pauze heft hem op. Signalen en journaal lopen door (alleen push_notify kijkt hiernaar)."""
    now = datetime.now(timezone.utc)
    if push_policy.pause_minutes_left(user.get("push_paused_until"), now):
        repo.set_push_pause(user["id"], None)
    else:
        repo.set_push_pause(user["id"], push_policy.pause_until(now).isoformat())
    return _pause_state(repo.get_user(user["id"]))
```

- [ ] **Step 4: Knop in `web/templates/base.html`**

In `.topbar-right`, direct vóór `<span class="live-pill">`:

```html
      {% if user %}{% set pause_left = pause_minutes_left(user) %}
      <button type="button" id="push-pause" class="push-pause{% if pause_left %} is-paused{% endif %}" aria-pressed="{{ 'true' if pause_left else 'false' }}"
              title="{{ 'Tik om meldingen weer aan te zetten' if pause_left else 'Meldingen 2 uur stil' }}">
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>
        <span id="push-pause-label">{{ pause_text(pause_left) }}</span>
      </button>
      {% endif %}
```

In de scriptlijst onderaan, na `<script src="{{ asset('smooth.js') }}" defer></script>`:

```html
<script src="{{ asset('pause.js') }}" defer></script>
```

- [ ] **Step 5: `web/static/pause.js`**

```js
// Pauzeknop: een tik zet alle pushes twee uur stil, nog een tik heft de pauze op. De server bewaart de eindtijd (users.push_paused_until),
// zodat de pauze ook geldt voor meldingen die komen terwijl de app dicht is. De resterende tijd komt van de server, de klok van de telefoon telt niet.
(function () {
  var btn = document.getElementById("push-pause"), label = document.getElementById("push-pause-label");
  if (!btn || !label) return;
  var timer = null;

  function show(state) {
    var paused = state.minutes_left > 0;
    btn.classList.toggle("is-paused", paused);
    btn.setAttribute("aria-pressed", paused ? "true" : "false");
    btn.title = paused ? "Tik om meldingen weer aan te zetten" : "Meldingen 2 uur stil";
    label.textContent = state.label;
    clearTimeout(timer);
    if (paused) timer = setTimeout(poll, 60000);
  }

  function call(method) {
    return fetch("/api/push/pauze", { method: method, credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) show(s); })
      .catch(function () { /* geen verbinding: de knop houdt zijn laatste stand */ });
  }

  function poll() {
    if (document.hidden) { timer = setTimeout(poll, 60000); return; }
    call("GET");
  }

  btn.addEventListener("click", function () {
    btn.disabled = true;
    call("POST").then(function () { btn.disabled = false; });
  });
  if (btn.classList.contains("is-paused")) timer = setTimeout(poll, 60000);
})();
```

- [ ] **Step 6: CSS**

In `web/static/style.css`, in `:root` direct na `--red-bg: ...;`:

```css
  --amber: #f2b33d;
```

Onderaan het bestand:

```css
/* Pauzeknop voor meldingen (pause.js). Oranje zolang de pauze loopt: het is de enige stand waarin je meldingen mist. */
.push-pause { display: inline-flex; align-items: center; gap: var(--space-2); padding: 2px 8px; min-height: 28px; border: 1px solid var(--border-strong);
              border-radius: 999px; background: none; color: var(--muted); font: inherit; font-family: var(--mono); font-size: var(--text-xs); cursor: pointer; }
.push-pause.is-paused { color: var(--amber); border-color: var(--amber); }
.push-pause:disabled { opacity: 0.6; }
```

- [ ] **Step 7: Draai de tests en de JS-check**

Run: `python3 -m unittest tests.test_web_extras -v && node --check web/static/pause.js`
Expected: PASS, geen uitvoer van node.

- [ ] **Step 8: Playwright-controle**

Start de server volgens de controle-opzet. `$SCRATCH/check_2.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/vandaag")
    btn = page.locator("#push-pause")
    assert btn.is_visible(), "knop zichtbaar op 390px"
    assert btn.inner_text().strip() == "Pauze"
    btn.click()
    page.wait_for_function("document.getElementById('push-pause-label').textContent.startsWith('Stil')")
    page.reload()
    assert page.locator("#push-pause-label").inner_text().startswith("Stil 1:5") or page.locator("#push-pause-label").inner_text() == "Stil 2:00"
    btn = page.locator("#push-pause")
    btn.click()
    page.wait_for_function("document.getElementById('push-pause-label').textContent === 'Pauze'")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_2.py $SCRATCH`
Expected: `ok`

- [ ] **Step 9: Volledige suite en commit**

Run: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`

```bash
git add web/main.py web/templates/base.html web/static/pause.js web/static/style.css tests/test_web_extras.py
git commit -m "Pauzeknop in de bovenbalk met resterende tijd"
```

---

### Task 3: Prijsalarm, opslag en controle (F4 backend)

**Files:**
- Create: `app/price_alerts.py`
- Modify: `app/schema.sql` (onderaan, nieuwe tabel)
- Modify: `app/repo.py` (na `set_push_pause`)
- Modify: `app/level_check.py:26` (import), nieuwe functie vóór `run_all_checks` (regel 571), `run_all_checks`
- Modify: `app/notifications_view.py:8-13`
- Test: `tests/test_price_alerts.py` (nieuw)

**Interfaces:**
- Consumes: niets uit eerdere taken (gebruikt `push_notify.send_push`, dat sinds Task 1 de pauze respecteert).
- Produces:
  - `price_alerts.MAX_OPEN_PER_USER = 20`
  - `price_alerts.side_for(target: float, current: float) -> str` ("above" of "below")
  - `price_alerts.first_hit(side: str, target: float, bars: Iterable[tuple[float, float]]) -> Optional[float]`
  - `price_alerts.alert_text(coin: str, label: str, target: float, hit: float) -> tuple[str, str]`
  - `repo.create_price_alert(user_id: int, coin: str, price: float, side: str, label: str, url: Optional[str]) -> int`
  - `repo.list_price_alerts(user_id: int) -> list[dict]` (open, oudste eerst)
  - `repo.count_open_price_alerts(user_id: int) -> int`
  - `repo.delete_price_alert(alert_id: int, user_id: int) -> bool`
  - `repo.list_open_price_alerts() -> list[dict]`
  - `repo.mark_price_alert_sent(alert_id: int) -> bool` (True alleen voor wie hem als eerste markeert)
  - `level_check.check_price_alerts() -> None` (async)

- [ ] **Step 1: Schrijf de falende tests**

Create `tests/test_price_alerts.py`:

```python
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import db, level_check, notifications_view, price_alerts, repo
from tests.test_samenval import DbCase


class PureTest(unittest.TestCase):
    def test_side_is_fixed_by_the_price_at_creation(self):
        self.assertEqual(price_alerts.side_for(105.0, 100.0), "above")
        self.assertEqual(price_alerts.side_for(95.0, 100.0), "below")
        self.assertEqual(price_alerts.side_for(100.0, 100.0), "above")

    def test_first_hit_only_counts_a_move_towards_the_level(self):
        bars = [(101.0, 99.0), (104.0, 100.0), (106.0, 103.0)]
        self.assertEqual(price_alerts.first_hit("above", 105.0, bars), 106.0)
        self.assertIsNone(price_alerts.first_hit("above", 107.0, bars))
        self.assertEqual(price_alerts.first_hit("below", 99.5, bars), 99.0)
        self.assertIsNone(price_alerts.first_hit("below", 98.0, bars))
        self.assertIsNone(price_alerts.first_hit("above", 105.0, []))

    def test_text(self):
        title, body = price_alerts.alert_text("BTC", "Doel", 61000.0, 61012.5)
        self.assertEqual(title, "Prijsalarm BTC: doel 61000.00 bereikt")
        self.assertIn("61012.50", body)
        self.assertNotIn("—", title + body)

    def test_notification_chip(self):
        self.assertEqual(notifications_view.TYPE_CHIPS["prijsalarm"][0], "Alarm")


def frame(start, rows):
    return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(minutes=5 * i)), "open": c, "high": h, "low": l, "close": c, "volume": 1.0}
                         for i, (h, l, c) in enumerate(rows)])


class CheckTest(DbCase):
    def setUp(self):
        super().setUp()
        self.uid = repo.get_user_by_username("a")["id"]
        self.push = mock.patch("app.push_notify.send_push", new=mock.AsyncMock())
        self.sent = self.push.start()
        self.addCleanup(self.push.stop)

    def alert(self, price, side, minutes_ago):
        aid = repo.create_price_alert(self.uid, "BTC", price, side, "Doel", "/smc#radar-setup-1")
        with db.session() as conn:
            conn.execute("UPDATE price_alerts SET created_at = ? WHERE id = ?",
                         ((datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(), aid))
        return aid

    def run_check(self, df):
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: df):
            asyncio.run(level_check.check_price_alerts())

    def test_fires_once_with_push_and_notification(self):
        aid = self.alert(105.0, "above", 40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.run_check(frame(start, [(101, 99, 100), (106, 100, 105), (104, 102, 103)]))
        self.assertEqual(self.sent.await_count, 1)
        self.assertEqual(self.sent.await_args.args[3], "/smc#radar-setup-1")
        self.assertEqual(repo.list_price_alerts(self.uid), [])
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT type FROM notifications WHERE user_id = ?", (self.uid,)).fetchone()["type"], "prijsalarm")
        self.run_check(frame(start, [(106, 100, 105)]))
        self.assertEqual(self.sent.await_count, 1)                        # fire once
        self.assertIsNotNone(aid)

    def test_candles_from_before_the_alert_do_not_count(self):
        self.alert(105.0, "above", 5)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.run_check(frame(start, [(106, 100, 105)] + [(101, 99, 100)] * 5))       # alleen de oude candle raakte het niveau
        self.assertEqual(self.sent.await_count, 0)
        self.assertEqual(len(repo.list_price_alerts(self.uid)), 1)

    def test_a_failed_push_does_not_make_it_fire_again(self):
        self.sent.side_effect = RuntimeError("push stuk")
        self.alert(95.0, "below", 40)
        start = datetime.now(timezone.utc) - timedelta(minutes=30)
        self.run_check(frame(start, [(101, 94, 96)]))
        self.run_check(frame(start, [(101, 94, 96)]))
        self.assertEqual(self.sent.await_count, 1)

    def test_repo_cap_count_and_delete_are_per_user(self):
        aid = repo.create_price_alert(self.uid, "ETH", 2500.0, "below", "Stop", None)
        self.assertEqual(repo.count_open_price_alerts(self.uid), 1)
        self.assertFalse(repo.delete_price_alert(aid, self.uid + 1))
        self.assertTrue(repo.delete_price_alert(aid, self.uid))
        self.assertEqual(repo.count_open_price_alerts(self.uid), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_price_alerts -v`
Expected: ERROR `ModuleNotFoundError: No module named 'app.price_alerts'`.

- [ ] **Step 3: Pure module `app/price_alerts.py`**

```python
"""Prijsalarm vanaf een kaart: tik op een niveau, melding zodra de koers er is. Pure functies; repo bewaart, level_check toetst elke 15 minuten."""
from typing import Iterable, Optional

from app.chance_steps import fmt

MAX_OPEN_PER_USER = 20


def side_for(target: float, current: float) -> str:
    """De kant ligt vast bij het aanmaken. Zonder vaste kant zou een alarm onder de koers meteen afgaan op elke candle die erboven ligt."""
    return "above" if target >= current else "below"


def first_hit(side: str, target: float, bars: Iterable[tuple[float, float]]) -> Optional[float]:
    """bars: (hoog, laag) per candle, oudste eerst. De candle-hoog of -laag waarop het niveau geraakt werd, of None."""
    for high, low in bars:
        if side == "above" and high >= target:
            return float(high)
        if side == "below" and low <= target:
            return float(low)
    return None


def alert_text(coin: str, label: str, target: float, hit: float) -> tuple[str, str]:
    return f"Prijsalarm {coin}: {label.lower()} {fmt(target)} bereikt", f"Koers raakte {fmt(hit)}.\nTik voor de kaart."
```

- [ ] **Step 4: Tabel in `app/schema.sql`**

Onderaan:

```sql
-- Prijsalarm dat een gebruiker zelf op een niveau van een kaart zet (app/price_alerts.py). side ligt vast bij het aanmaken ('above' of
-- 'below' de koers van dat moment). sent_at gezet = afgegaan; een alarm gaat precies één keer af (level_check markeert vóór het versturen).
CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    coin TEXT NOT NULL,
    price REAL NOT NULL,
    side TEXT NOT NULL,
    label TEXT NOT NULL,
    url TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_price_alerts_open ON price_alerts(sent_at, coin);
```

- [ ] **Step 5: Repo-functies**

In `app/repo.py` na `set_push_pause`:

```python
def create_price_alert(user_id: int, coin: str, price: float, side: str, label: str, url: Optional[str]) -> int:
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO price_alerts (user_id, coin, price, side, label, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, coin, price, side, label, url, db.now_iso()))
        return cur.lastrowid


def list_price_alerts(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM price_alerts WHERE user_id = ? AND sent_at IS NULL ORDER BY created_at", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def count_open_price_alerts(user_id: int) -> int:
    with db.session() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM price_alerts WHERE user_id = ? AND sent_at IS NULL", (user_id,)).fetchone()["n"]


def delete_price_alert(alert_id: int, user_id: int) -> bool:
    with db.session() as conn:
        return conn.execute("DELETE FROM price_alerts WHERE id = ? AND user_id = ?", (alert_id, user_id)).rowcount == 1


def list_open_price_alerts() -> list[dict]:
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM price_alerts WHERE sent_at IS NULL ORDER BY coin, created_at").fetchall()]


def mark_price_alert_sent(alert_id: int) -> bool:
    """True alleen voor de aanroep die hem markeert: twee overlappende runs van level_check sturen zo nooit twee keer."""
    with db.session() as conn:
        return conn.execute("UPDATE price_alerts SET sent_at = ? WHERE id = ? AND sent_at IS NULL", (db.now_iso(), alert_id)).rowcount == 1
```

- [ ] **Step 6: Controle in `app/level_check.py`**

Import op regel 26 wordt `from app import db, exchange, indicators, price_alerts, push_notify, repo, rule_live`.

Vóór `run_all_checks`:

```python
async def check_price_alerts() -> None:
    """Prijsalarmen die gebruikers op een kaart zetten. Eerst markeren, dan versturen: een mislukte push mag nooit betekenen dat hetzelfde
    alarm elke 15 minuten opnieuw afgaat. De melding staat ook op de meldingenpagina, zodat een alarm tijdens een pauze niet verdwijnt."""
    by_coin: dict[str, list[dict]] = {}
    for alert in repo.list_open_price_alerts():
        by_coin.setdefault(alert["coin"], []).append(alert)
    for coin, alerts in by_coin.items():
        try:
            candles = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe=LEVEL_CHECK_CANDLE_TIMEFRAME, limit=LEVEL_CHECK_CANDLE_LOOKBACK)
        except Exception:
            logger.exception("Kon geen candles ophalen voor prijsalarm %s, sla over", coin)
            continue
        for alert in alerts:
            created = pd.Timestamp(_aware(datetime.fromisoformat(alert["created_at"])))
            # Een candle die vóór het alarm begon, bevat koersen van vóór het aanmaken; die tellen niet.
            after = candles[candles["timestamp"] >= created]
            hit = price_alerts.first_hit(alert["side"], alert["price"], zip(after["high"], after["low"]))
            if hit is None or not repo.mark_price_alert_sent(alert["id"]):
                continue
            title, body = price_alerts.alert_text(coin, alert["label"], alert["price"], hit)
            url = alert["url"] or "/smc"
            repo.create_notification(alert["user_id"], "prijsalarm", title, body, url)
            try:
                await push_notify.send_push(alert["user_id"], title, body, url, tag=f"prijsalarm-{alert['id']}")
            except Exception:
                logger.exception("Prijsalarm %s versturen mislukt", alert["id"])
```

In `run_all_checks`, na `await check_open_trades()`:

```python
    try:
        await check_price_alerts()
    except Exception:
        logger.exception("Prijsalarmen controleren is mislukt")
```

- [ ] **Step 7: Label op de meldingenpagina**

In `app/notifications_view.py`, in `TYPE_CHIPS`:

```python
    "prijsalarm": ("Alarm", "chip-new"),
```

- [ ] **Step 8: Draai de tests**

Run: `python3 -m unittest tests.test_price_alerts tests.test_signal_outcomes tests.test_notifications_view -v`
Expected: PASS

- [ ] **Step 9: Volledige suite en commit**

Run: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`

```bash
git add app/price_alerts.py app/schema.sql app/repo.py app/level_check.py app/notifications_view.py tests/test_price_alerts.py
git commit -m "Prijsalarm: tabel, controle elke 15 minuten, gaat precies een keer af"
```

---

### Task 4: Instap, stop en doel kopiëren met een tik (F5)

**Files:**
- Modify: `app/chance_steps.py` (onderaan)
- Modify: `app/radar.py:10-28` (`setup_card`), `:50-63` (`signal_card`)
- Modify: `app/today.py:96-113` (`scenario_view`)
- Modify: `web/templates/_macros.html` (nieuwe macro na `share_button`, regel 265)
- Modify: `web/templates/smc.html` (setup-kaart na `level_chart`, open trade na `level_chart`)
- Modify: `web/templates/vandaag.html:83` (na `steps_list` in een scenario)
- Create: `web/static/copy.js`
- Modify: `web/templates/base.html` (scriptlijst), `web/static/style.css`
- Test: `tests/test_chance_steps.py`, `tests/test_radar.py`, `tests/test_today.py`, `tests/test_web_radar.py`

**Interfaces:**
- Consumes: niets.
- Produces:
  - `chance_steps.level_chips(entry: float, stop: float, take: float) -> list[dict]` met per item `{"key": "entry"|"stop"|"take", "label": "Instap"|"Stop"|"Doel", "value": float, "text": str}`
  - kaartveld `levels` op `radar.setup_card` (leeg bij moot), `radar.signal_card` en `today.scenario_view`
  - macro `macros.level_chips(coin, levels, url="")` met wrapper `<div class="level-chips" data-chips-coin data-chips-url>` en per niveau `<span class="level-chip level-chip-{key}">` (Task 5 voegt daar een belknop aan toe)
  - `window.hesToast(text)` uit `copy.js` (gebruikt door Task 5)

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_chance_steps.py`, nieuwe testmethode in de bestaande testklasse (of een nieuwe klasse `LevelChipsTest(unittest.TestCase)`):

```python
class LevelChipsTest(unittest.TestCase):
    def test_three_chips_in_the_same_notation_as_the_steps(self):
        chips = chance_steps.level_chips(100.0, 97.0, 0.09571)
        self.assertEqual([c["key"] for c in chips], ["entry", "stop", "take"])
        self.assertEqual([c["label"] for c in chips], ["Instap", "Stop", "Doel"])
        self.assertEqual([c["text"] for c in chips], ["100.00", "97.0000", "0.09571"])
        self.assertEqual(chips[2]["value"], 0.09571)
```

`tests/test_radar.py`, in `RadarTests`:

```python
    def test_kaarten_hebben_kopieerbare_niveaus(self):
        card = radar.setup_card(SETUP, 102.0)
        self.assertEqual([c["text"] for c in card["levels"]], ["100.00", "97.0000", "106.00"])
        self.assertEqual(radar.setup_card(SETUP, 107.0)["levels"], [])           # doel al gehaald: niets meer te kopiëren
        self.assertEqual([c["value"] for c in radar.signal_card(SIGNAL, 99.0)["levels"]], [100.0, 103.0, 94.0])
```

`tests/test_today.py`, nieuwe methode in de klasse die `scenario_view` test (zoek `def test_numbers_and_distance`; gebruik dezelfde scenario-opbouw als die test):

```python
    def test_scenario_has_copyable_levels(self):
        now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
        s = {"id": 1, "direction": "long", "trigger_type": "close_above", "trigger_level": 101.0, "entry": 100.8, "stop_loss": 99.8,
             "take_profit": 103.0, "reason": "x", "state": "waiting", "expires_at": (now + timedelta(hours=3)).isoformat()}
        view = today.scenario_view(s, 100.0, now, "BTC")
        self.assertEqual([c["value"] for c in view["levels"]], [100.8, 99.8, 103.0])
```

(Zorg dat `timedelta` en `timezone` in `tests/test_today.py` geïmporteerd zijn: `from datetime import datetime, timedelta, timezone`.)

`tests/test_web_radar.py`, in `WebRadarTests`:

```python
    def test_niveaus_zijn_tikbaar_om_te_kopieren(self):
        r = self.client.get("/smc")
        self.assertIn('data-copy="100.00"', r.text)                      # limiet van de XRP-setup
        self.assertIn('data-chips-coin="XRP"', r.text)
        self.assertIn('data-copy="106.00"', r.text)                      # doel van de open ETH-trade
        self.assertIn("copy.js", r.text)
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_chance_steps tests.test_radar tests.test_today tests.test_web_radar -v`
Expected: FAIL (`level_chips` bestaat niet, `levels` ontbreekt).

- [ ] **Step 3: `chance_steps.level_chips`**

Onderaan `app/chance_steps.py`:

```python
def level_chips(entry: float, stop: float, take: float) -> list[dict]:
    """Instap, stop en doel als losse getallen voor de tik-om-te-kopiëren-knoppen. Zelfde notatie als in de stappen, met een punt als
    decimaalteken, want dat accepteert elk orderveld van een beurs."""
    return [{"key": key, "label": label, "value": value, "text": fmt(value)}
            for key, label, value in (("entry", "Instap", entry), ("stop", "Stop", stop), ("take", "Doel", take))]
```

- [ ] **Step 4: Kaartvelden**

`app/radar.py`, in de dict van `setup_card` (na `"steps": ...`):

```python
        "levels": [] if moot else chance_steps.level_chips(plan.limit, plan.stop, plan.take),
```

In `signal_card` (na `"rr": ...`):

```python
        "levels": chance_steps.level_chips(entry, stop, take),
```

`app/today.py`, in `scenario_view` direct na `view["steps"] = chance_steps.script_steps(view)`:

```python
    view["levels"] = chance_steps.level_chips(s["entry"], s["stop_loss"], s["take_profit"])
```

- [ ] **Step 5: Macro**

In `web/templates/_macros.html`, na de macro `share_button`:

```jinja
{# Instap, stop en doel als knoppen: een tik zet het getal op het klembord (web/static/copy.js). `levels` komt uit chance_steps.level_chips;
   `url` is waar een prijsalarm later naartoe linkt. #}
{% macro level_chips(coin, levels, url="") %}
{% if levels %}
<div class="level-chips" data-chips-coin="{{ coin }}" data-chips-url="{{ url }}">
  {% for l in levels %}
  <span class="level-chip level-chip-{{ l.key }}">
    <button type="button" class="level-copy" data-copy="{{ l.text }}" aria-label="Kopieer {{ l.label|lower }} {{ l.text }}"><span class="level-chip-label">{{ l.label }}</span> {{ l.text }}</button>
  </span>
  {% endfor %}
</div>
{% endif %}
{% endmacro %}
```

- [ ] **Step 6: Templates**

`web/templates/smc.html`, bouwende setup, direct na `{% if c.chart %}{{ macros.level_chart(c.coin, c.chart) }}{% endif %}` in de eerste lus:

```jinja
      {{ macros.level_chips(c.coin, c.levels, "/smc#radar-" ~ c.key|replace(':', '-')) }}
```

Open trades, direct na `{% if c.chart %}{{ macros.level_chart(c.coin, c.chart) }}{% endif %}` in de lus over `signal_cards`:

```jinja
      {{ macros.level_chips(c.coin, c.levels, "/smc#radar-" ~ c.key|replace(':', '-')) }}
```

`web/templates/vandaag.html`, direct na `{{ macros.steps_list(sc.steps, user.risk_per_trade_eur) }}`:

```jinja
          {{ macros.level_chips(s.coin, sc.levels, "/vandaag") }}
```

`web/templates/base.html`, scriptlijst na `pause.js`:

```html
<script src="{{ asset('copy.js') }}" defer></script>
```

- [ ] **Step 7: `web/static/copy.js`**

```js
// Tik op instap, stop of doel: het getal staat op het klembord. De bevestiging is nodig omdat je op een telefoon het klembord niet ziet.
// navigator.clipboard bestaat alleen op https en localhost; daarbuiten valt het terug op een verborgen tekstveld.
(function () {
  var toast = null, timer = null;

  function show(text) {
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "copy-toast";
      toast.setAttribute("role", "status");
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.add("is-on");
    clearTimeout(timer);
    timer = setTimeout(function () { toast.classList.remove("is-on"); }, 1800);
  }
  window.hesToast = show;

  function fallback(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-copy]");
    if (!btn) return;
    var text = btn.getAttribute("data-copy");
    var done = function (ok) { show(ok ? "Gekopieerd: " + text : "Kopiëren lukte niet"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallback(text)); });
    } else {
      done(fallback(text));
    }
  });
})();
```

- [ ] **Step 8: CSS**

Onderaan `web/static/style.css`:

```css
/* Kopieerbare niveaus op een kaart (copy.js). Minstens 32px hoog: het is een tikdoel op een telefoon. */
.level-chips { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.level-chip { display: inline-flex; align-items: stretch; border: 1px solid var(--border-strong); border-radius: 999px; overflow: hidden; }
.level-chip-stop { border-color: rgba(242, 104, 92, 0.45); }
.level-chip-take { border-color: rgba(51, 214, 159, 0.45); }
.level-copy { min-height: 32px; padding: 4px 10px; background: none; border: 0; color: var(--text); font-family: var(--mono); font-size: var(--text-sm); cursor: pointer; }
.level-copy:active { background: var(--panel-hover); }
.level-chip-label { color: var(--muted); font-family: var(--sans); font-size: var(--text-xs); }
.copy-toast { position: fixed; left: 50%; bottom: calc(100px + env(safe-area-inset-bottom)); transform: translateX(-50%); z-index: 700; padding: 8px 14px;
              border-radius: 999px; background: var(--panel); border: 1px solid var(--border-strong); color: var(--text); font-size: var(--text-sm);
              opacity: 0; pointer-events: none; transition: opacity 0.15s ease; }
.copy-toast.is-on { opacity: 1; }
@media (prefers-reduced-motion: reduce) { .copy-toast { transition: none; } }
```

- [ ] **Step 9: Draai de tests en de JS-check**

Run: `python3 -m unittest tests.test_chance_steps tests.test_radar tests.test_today tests.test_web_radar -v && node --check web/static/copy.js`
Expected: PASS

- [ ] **Step 10: Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_4.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page, BASE

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/smc")
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
    btn = page.locator(".level-copy").first
    expected = btn.get_attribute("data-copy")
    btn.click()
    page.wait_for_selector(".copy-toast.is-on")
    assert page.locator(".copy-toast").inner_text() == "Gekopieerd: " + expected
    assert page.evaluate("navigator.clipboard.readText()") == expected
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "geen horizontale scroll"
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_4.py $SCRATCH`
Expected: `ok`

- [ ] **Step 11: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/chance_steps.py app/radar.py app/today.py web/templates/_macros.html web/templates/smc.html web/templates/vandaag.html web/templates/base.html web/static/copy.js web/static/style.css tests/test_chance_steps.py tests/test_radar.py tests/test_today.py tests/test_web_radar.py
git commit -m "Instap, stop en doel kopieren met een tik"
```

---

### Task 5: Prijsalarm vanaf een kaart (F4 UI)

**Files:**
- Modify: `web/main.py` (import `price_alerts`, nieuwe routes na de pauzeroutes; `import math` bovenaan)
- Modify: `web/templates/_macros.html` (macro `level_chips`)
- Create: `web/static/alarm.js`
- Modify: `web/templates/base.html` (scriptlijst), `web/static/style.css`
- Test: `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `price_alerts.side_for`, `MAX_OPEN_PER_USER`, de repo-functies (Task 3); macro `level_chips` en `window.hesToast` (Task 4); `WebCase` (Task 2).
- Produces:
  - `GET /api/prijsalarm` -> `{"alerts": [{"id", "coin", "price", "label"}]}`
  - `POST /api/prijsalarm` body `{"coin", "price", "label", "url"}` -> `{"id", "side", "message"}`; 400 ongeldig, 409 te veel open, 503 geen koers
  - `DELETE /api/prijsalarm/{id}` -> `{"ok": true}` of 404

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_web_extras.py` (vóór `if __name__`):

```python
class PriceAlertRouteTest(WebCase):
    def post(self, **body):
        return self.client.post("/api/prijsalarm", json={"coin": "BTC", "price": 105.0, "label": "Doel", "url": "/smc#radar-setup-1", **body})

    def test_create_list_and_delete(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["side"], "above")                       # koers 100, niveau 105
        self.assertIn("15 minuten", r.json()["message"])
        alerts = self.client.get("/api/prijsalarm").json()["alerts"]
        self.assertEqual([(a["coin"], a["price"]) for a in alerts], [("BTC", 105.0)])
        self.assertEqual(self.client.delete(f"/api/prijsalarm/{alerts[0]['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/prijsalarm").json()["alerts"], [])
        self.assertEqual(self.client.delete(f"/api/prijsalarm/{alerts[0]['id']}").status_code, 404)

    def test_rejects_unknown_coin_bad_price_and_foreign_url(self):
        self.assertEqual(self.post(coin="NOPE").status_code, 400)
        self.assertEqual(self.post(price="abc").status_code, 400)
        self.assertEqual(self.post(price=-1).status_code, 400)
        r = self.post(url="https://evil.test/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(repo.list_price_alerts(self.uid)[0]["url"], "/smc")

    def test_cap_on_open_alerts(self):
        from app import price_alerts
        for i in range(price_alerts.MAX_OPEN_PER_USER):
            self.assertEqual(self.post(price=101.0 + i).status_code, 200)
        self.assertEqual(self.post(price=200.0).status_code, 409)

    def test_radar_card_has_a_bell_per_level(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('BTC', 'long', 99.0, 100.0, 101.0, 98.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))
        r = self.client.get("/smc")
        self.assertIn('class="level-bell"', r.text)
        self.assertIn('data-alarm-price="100.0"', r.text)
        self.assertIn("alarm.js", r.text)
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_web_extras.PriceAlertRouteTest -v`
Expected: FAIL (404/405 op `/api/prijsalarm`, geen `level-bell`).

- [ ] **Step 3: Routes in `web/main.py`**

Voeg `import math` toe aan de stdlib-imports en `price_alerts` aan `from app import ... push_policy, price_alerts, radar, ...`.

Na de pauzeroutes:

```python
@app.get("/api/prijsalarm")
async def api_price_alerts(user: dict = Depends(require_login)):
    return {"alerts": [{"id": a["id"], "coin": a["coin"], "price": a["price"], "label": a["label"]} for a in repo.list_price_alerts(user["id"])]}


@app.post("/api/prijsalarm")
async def api_price_alert_create(request: Request, user: dict = Depends(require_login)):
    """Alarm op een niveau van een kaart. De kant (boven of onder de koers) ligt vast bij het aanmaken; level_check toetst elke 15 minuten."""
    data = await request.json()
    coin = str(data.get("coin", "")).upper()
    try:
        price = float(data.get("price"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Ongeldige prijs"}, status_code=400)
    if coin not in {c["symbol"] for c in repo.list_coins()} or not math.isfinite(price) or price <= 0:
        return JSONResponse({"error": "Ongeldig alarm"}, status_code=400)
    if repo.count_open_price_alerts(user["id"]) >= price_alerts.MAX_OPEN_PER_USER:
        return JSONResponse({"error": f"Maximaal {price_alerts.MAX_OPEN_PER_USER} alarmen tegelijk"}, status_code=409)
    current = (await _cached_prices({coin})).get(coin)
    if current is None:
        return JSONResponse({"error": "Geen koers, probeer het zo opnieuw"}, status_code=503)
    raw_url = str(data.get("url") or "")
    url = raw_url if raw_url.startswith("/") and not raw_url.startswith("//") else "/smc"
    side = price_alerts.side_for(price, current)
    alert_id = repo.create_price_alert(user["id"], coin, price, side, str(data.get("label") or "Niveau")[:20], url)
    return {"id": alert_id, "side": side, "message": f"Alarm staat op {chance_steps.fmt(price)}. Melding binnen 15 minuten na het raken."}


@app.delete("/api/prijsalarm/{alert_id}")
async def api_price_alert_delete(alert_id: int, user: dict = Depends(require_login)):
    if not repo.delete_price_alert(alert_id, user["id"]):
        raise HTTPException(status_code=404)
    return {"ok": True}
```

- [ ] **Step 4: Bel in de macro**

In `web/templates/_macros.html`, macro `level_chips`, direct na de `</button>` van `level-copy` (binnen de `<span class="level-chip ...">`):

```jinja
    <button type="button" class="level-bell" data-alarm-price="{{ l.value }}" data-alarm-label="{{ l.label }}" aria-pressed="false" aria-label="Prijsalarm op {{ l.label|lower }} {{ l.text }}"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg></button>
```

`web/templates/base.html`, scriptlijst na `copy.js`:

```html
<script src="{{ asset('alarm.js') }}" defer></script>
```

- [ ] **Step 5: `web/static/alarm.js`**

```js
// Prijsalarm vanaf een kaart: een tik op de bel naast een niveau zet een alarm, nog een tik haalt het weg. De controle draait op de server
// (app/level_check.py, elke 15 minuten), dus de melding komt ook als de app dicht is.
(function () {
  var groups = document.querySelectorAll("[data-chips-coin]");
  if (!groups.length) return;
  var byKey = {};

  function key(coin, price) { return coin + "|" + Number(price).toPrecision(10); }
  function toast(text) { if (window.hesToast) window.hesToast(text); }

  function mark() {
    groups.forEach(function (g) {
      var coin = g.getAttribute("data-chips-coin");
      g.querySelectorAll(".level-bell").forEach(function (b) {
        var on = !!byKey[key(coin, b.getAttribute("data-alarm-price"))];
        b.setAttribute("aria-pressed", on ? "true" : "false");
        b.classList.toggle("is-on", on);
      });
    });
  }

  fetch("/api/prijsalarm", { credentials: "same-origin", cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      d.alerts.forEach(function (a) { byKey[key(a.coin, a.price)] = a.id; });
      mark();
    })
    .catch(function () {});

  function create(b, g, k) {
    return fetch("/api/prijsalarm", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coin: g.getAttribute("data-chips-coin"), price: Number(b.getAttribute("data-alarm-price")),
                             label: b.getAttribute("data-alarm-label"), url: g.getAttribute("data-chips-url") }),
    }).then(function (r) {
      return r.json().then(function (d) {
        if (r.ok) { byKey[k] = d.id; toast(d.message); } else { toast(d.error || "Alarm zetten lukte niet"); }
      });
    });
  }

  function remove(k) {
    return fetch("/api/prijsalarm/" + byKey[k], { method: "DELETE", credentials: "same-origin" }).then(function (r) {
      if (r.ok || r.status === 404) { delete byKey[k]; toast("Alarm weg"); }
    });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".level-bell");
    if (!b) return;
    var g = b.closest("[data-chips-coin]"), k = key(g.getAttribute("data-chips-coin"), b.getAttribute("data-alarm-price"));
    b.disabled = true;
    (byKey[k] ? remove(k) : create(b, g, k))
      .catch(function () { toast("Geen verbinding"); })
      .then(function () { b.disabled = false; mark(); });
  });
})();
```

- [ ] **Step 6: CSS**

Onderaan `web/static/style.css`:

```css
/* Bel naast een niveau (alarm.js): gevuld zodra er een alarm op staat. */
.level-bell { min-width: 32px; min-height: 32px; display: inline-flex; align-items: center; justify-content: center; background: none; border: 0;
              border-left: 1px solid var(--border); color: var(--muted); cursor: pointer; }
.level-bell.is-on { color: var(--accent); }
.level-bell.is-on svg { fill: currentColor; }
.level-bell:disabled { opacity: 0.5; }
```

- [ ] **Step 7: Draai de tests en de JS-check**

Run: `python3 -m unittest tests.test_web_extras -v && node --check web/static/alarm.js`
Expected: PASS

- [ ] **Step 8: Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_5.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/smc")
    bell = page.locator(".level-bell").first
    bell.click()
    page.wait_for_selector(".level-bell.is-on")
    assert "Alarm staat op" in page.locator(".copy-toast").inner_text()
    page.reload(); page.wait_for_selector(".level-bell.is-on")          # overleeft een herlaadslag
    page.locator(".level-bell.is-on").first.click()
    page.wait_for_function("!document.querySelector('.level-bell.is-on')")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_5.py $SCRATCH`
Expected: `ok`

Daarna een echte afgaande controle tegen dezelfde scratch DB met de nagebootste beurs (level_check haalt 6 candles van 5m op; de eerste heeft slot 60800 en laag 60678, dus 60700 wordt geraakt):

```bash
DATABASE_PATH="$SCRATCH/ui.db" python3 -c "
import sys, asyncio; sys.path.insert(0, '$SCRATCH'); import ui_fake
from app import repo, db, level_check
uid = repo.get_user_by_username('demo')['id']
aid = repo.create_price_alert(uid, 'BTC', 60700.0, 'below', 'Stop', '/smc')
with db.session() as c: c.execute(\"UPDATE price_alerts SET created_at = '2000-01-01T00:00:00+00:00' WHERE id = ?\", (aid,))
asyncio.run(level_check.check_price_alerts())
print([a['id'] for a in repo.list_price_alerts(uid)])"
```

Expected: de lijst bevat `aid` niet meer, en `/meldingen` toont een melding met het label Alarm.

- [ ] **Step 9: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add web/main.py web/templates/_macros.html web/templates/base.html web/static/alarm.js web/static/style.css tests/test_web_extras.py
git commit -m "Prijsalarm vanaf een kaart: bel naast instap, stop en doel"
```

---

### Task 6: Appicoon-badge met kansen in de zone (F6)

**Files:**
- Modify: `app/radar.py` (na `waiting_count`)
- Modify: `app/repo.py` (na `mark_smc_zone_alert_sent`, regel 2417-2419)
- Modify: `app/push_notify.py` (`send_push`, `send_kans_push`)
- Modify: `app/market_scanner.py:796-805` (`_notify_zone_touches`)
- Modify: `web/main.py:1133-1165` (`api_system_status`)
- Modify: `web/templates/base.html:801-808` (badge-blok in de systeemstatus-JS)
- Modify: `web/static/service-worker.js:60-75` (push-handler)
- Create: `tests/js/sw_push_harness.js`
- Test: `tests/test_radar.py`, `tests/test_push_policy.py`, `tests/test_smc_alerts.py`, `tests/test_service_worker.py`, `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `PauseSendTest`-opzet in `tests/test_push_policy.py` (Task 1), `WebCase` (Task 2).
- Produces:
  - `radar.in_zone_count(setups: list[dict], prices: dict) -> int` (setups met `preview_stop_loss`/`preview_take_profit`, zie `web/main._with_preview`)
  - `repo.count_zone_alerted_setups() -> int`
  - `push_notify.send_push(..., badge: Optional[int] = None)` en `send_kans_push(..., badge: Optional[int] = None)`; payloadveld `badge` alleen als niet None
  - `/api/system_status` krijgt veld `in_zone: int`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_radar.py`, in `RadarTests`:

```python
    def test_in_zone_count_telt_alleen_setups_met_koers_in_de_zone(self):
        other = {**SETUP, "id": 8, "coin": "ETH"}
        self.assertEqual(radar.in_zone_count([SETUP, other], {"XRP": 99.5, "ETH": 102.0}), 1)
        self.assertEqual(radar.in_zone_count([SETUP], {}), 0)                    # zonder koers niets beloven
```

`tests/test_push_policy.py`, in `PauseSendTest`:

```python
    def test_badge_travels_in_the_payload_only_when_given(self):
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x", badge=3))
        asyncio.run(push_notify.send_push(self.uid, "t", "b", "/x"))
        self.assertEqual(self.sent[0]["badge"], 3)
        self.assertNotIn("badge", self.sent[1])
```

`tests/test_smc_alerts.py`, in de klasse met `run_touch`:

```python
    def test_zone_melding_zet_het_getal_op_het_appicoon(self):
        self.run_touch("XRP", 99.5)
        self.assertEqual(self.send.await_args_list[0].kwargs.get("badge"), 1)
```

`tests/test_service_worker.py`, nieuwe klasse onderaan (vóór `if __name__`):

```python
@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class PushBadgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", str(ROOT / "tests/js/sw_push_harness.js"), str(ROOT / "web/static/service-worker.js")],
                             capture_output=True, text=True, check=True)
        cls.result = json.loads(out.stdout)

    def test_badge_number_is_set_and_zero_clears_it(self):
        self.assertEqual(self.result["three"]["badge"], [["set", 3]])
        self.assertEqual(self.result["zero"]["badge"], [["clear"]])

    def test_without_badge_or_without_api_only_the_notification_is_shown(self):
        self.assertEqual(self.result["none"]["badge"], [])
        self.assertEqual(self.result["noApi"]["shown"], 1)
        for scenario in ("three", "zero", "none"):
            self.assertEqual(self.result[scenario]["shown"], 1)
```

Create `tests/js/sw_push_harness.js`:

```js
// Draait de push-regel van de service worker met nagebootste browserobjecten: toont hij de melding en zet hij het getal op het appicoon.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");

async function scenario(payload, withApi) {
  const listeners = {}, log = { shown: 0, badge: [] };
  const nav = withApi ? { setAppBadge: async (n) => { log.badge.push(["set", n]); }, clearAppBadge: async () => { log.badge.push(["clear"]); } } : {};
  const fakeSelf = {
    addEventListener: (n, f) => { listeners[n] = f; }, location: { origin: "https://hespulse.test" }, skipWaiting() {}, clients: { claim() {} },
    registration: { showNotification: async () => { log.shown += 1; } }, navigator: nav,
  };
  const fakeCaches = { open: async () => ({ put: async () => {}, match: async () => null }), keys: async () => [], delete: async () => true };
  new Function("self", "caches", "clients", "Response", "URL", "fetch", src)(
    fakeSelf, fakeCaches, { matchAll: async () => [], openWindow: async () => {}, claim() {} }, Response, URL, async () => { throw new Error("offline"); });
  const event = { data: { json: () => payload }, waitUntil(p) { this.p = p; } };
  listeners.push(event);
  await event.p;
  return log;
}

(async () => {
  const base = { title: "t", body: "b", url: "/smc" };
  console.log(JSON.stringify({
    three: await scenario({ ...base, badge: 3 }, true),
    zero: await scenario({ ...base, badge: 0 }, true),
    none: await scenario(base, true),
    noApi: await scenario({ ...base, badge: 2 }, false),
  }));
})();
```

`tests/test_web_extras.py`:

```python
class SystemStatusBadgeTest(WebCase):
    def test_in_zone_counts_forming_setups_with_the_price_in_the_zone(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('XRP', 'long', 99.0, 101.0, 102.0, 97.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))
        self.assertEqual(self.client.get("/api/system_status").json()["in_zone"], 1)       # koers 100 ligt in 99-101
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_radar tests.test_push_policy tests.test_smc_alerts tests.test_service_worker tests.test_web_extras -v`
Expected: FAIL (`in_zone_count` ontbreekt, `badge` onbekend argument, harness ziet geen badge, `in_zone` ontbreekt).

- [ ] **Step 3: `radar.in_zone_count`**

In `app/radar.py`, na `waiting_count`:

```python
def in_zone_count(setups: list[dict], prices: dict) -> int:
    """Bouwende setups waarvan de koers nu in de zone staat, voor het getal op het appicoon. Zonder koers telt een setup niet mee:
    het icoon zou anders iets beloven wat niet gemeten is."""
    return sum(1 for s in setups if setup_state(s, prices.get(s["coin"])) == "in_zone")
```

- [ ] **Step 4: Repo-teller**

In `app/repo.py`, na `mark_smc_zone_alert_sent`:

```python
def count_zone_alerted_setups() -> int:
    """Bouwende setups waarvoor de zone-melding al uitging: het getal op het appicoon terwijl de app dicht is. Een setup die daarna weer
    uit de zone liep telt hier nog mee; de pagina zet het exacte getal (radar.in_zone_count) zodra de app opent."""
    with db.session() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM smc_setups WHERE signal_id IS NULL AND invalidated_at IS NULL AND zone_alert_sent = 1").fetchone()["n"]
```

- [ ] **Step 5: `badge` in het verzendpad**

`app/push_notify.py`, `send_push`-signatuur:

```python
async def send_push(user_id: int, title: str, body: str, url: str, silent: bool = False, tag: Optional[str] = None,
                    badge: Optional[int] = None) -> None:
```

Direct na de regel `payload = {...}`:

```python
    if badge is not None:
        payload["badge"] = badge
```

`send_kans_push`-signatuur:

```python
async def send_kans_push(user_id: int, coin: str, direction: str, title: str, body: str, url: str, silent: bool = False,
                         tag: Optional[str] = None, badge: Optional[int] = None) -> bool:
```

en de verzendregel wordt:

```python
    await send_push(user_id, title, body, url, silent=silent, **({"tag": tag} if tag else {}), **({"badge": badge} if badge is not None else {}))
```

`app/market_scanner.py`, in `_notify_zone_touches`, direct na `repo.mark_smc_zone_alert_sent(setup["id"])`:

```python
        badge = repo.count_zone_alerted_setups()
```

en de `send_kans_push`-aanroep krijgt `badge=badge` erbij:

```python
                await push_notify.send_kans_push(user["id"], coin, direction, title, body, f"/smc#radar-setup-{setup['id']}", silent=quiet, tag=f"smc-zone-{coin}", badge=badge)
```

- [ ] **Step 6: Service worker**

In `web/static/service-worker.js`, vervang de hele `push`-listener door:

```js
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  const tasks = [
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      silent: !!data.silent,
      // Een nieuwere melding voor dezelfde coin en soort vervangt de vorige in plaats van te stapelen.
      tag: data.tag || undefined,
      renotify: !!data.tag && !data.silent,
      data: { url: data.url },
    }),
  ];
  // Het getal op het appicoon (kansen in de zone) komt alleen mee bij een zone-melding. Zonder Badging API (oudere browsers, iOS buiten
  // een geïnstalleerde app) blijft het bij de melding.
  const nav = self.navigator;
  if (typeof data.badge === "number" && nav && "setAppBadge" in nav) {
    tasks.push((data.badge > 0 ? nav.setAppBadge(data.badge) : nav.clearAppBadge()).catch(() => {}));
  }
  event.waitUntil(Promise.all(tasks));
});
```

- [ ] **Step 7: Systeemstatus en pagina-badge**

`web/main.py`, in `api_system_status`, vóór `return {`:

```python
    forming = [_with_preview(s) for s in repo.list_forming_smc_setups()]
    zone_prices = await _cached_prices({s["coin"] for s in forming}) if forming else {}
```

en in de returned dict:

```python
        "in_zone": radar.in_zone_count(forming, zone_prices),
```

`web/templates/base.html`, vervang het blok vanaf `// App-icoon badge: aantal meldingen dat nog op een keuze wacht.` tot en met de sluitende `}` van `if ("setAppBadge" in navigator) {...}` door:

```js
          // App-icoon: aantal kansen waarvan de koers nu in de zone staat (radar.in_zone_count). De service worker zet een benadering bij
          // een zone-melding als de app dicht is; deze pagina zet het exacte getal zodra hij open is.
          if ("setAppBadge" in navigator) {
            if (s.in_zone > 0) navigator.setAppBadge(s.in_zone).catch(function () {});
            else navigator.clearAppBadge().catch(function () {});
          }
```

- [ ] **Step 8: Draai de tests en de JS-check**

Run: `python3 -m unittest tests.test_radar tests.test_push_policy tests.test_smc_alerts tests.test_service_worker tests.test_web_extras -v && node --check web/static/service-worker.js`
Expected: PASS

- [ ] **Step 9: Handmatige controle**

Server volgens de controle-opzet (ETH-setup 2480-2520 met koers 2500 staat in de zone). `$SCRATCH/check_6.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/vandaag")
    page.add_init_script("window.__badge = []; navigator.setAppBadge = function (n) { window.__badge.push(n); return Promise.resolve(); };"
                         "navigator.clearAppBadge = function () { window.__badge.push(0); return Promise.resolve(); };")
    page.reload(); page.wait_for_function("window.__badge.length > 0", timeout=15000)
    assert page.evaluate("window.__badge[window.__badge.length - 1]") == 1, page.evaluate("window.__badge")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_6.py $SCRATCH`
Expected: `ok`. Op een iPhone (iOS 16.4 of nieuwer, app op het beginscherm, meldingen toegestaan) verschijnt het getal op het icoon; in Safari zonder installatie gebeurt niets en dat is de bedoelde terugval.

- [ ] **Step 10: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/radar.py app/repo.py app/push_notify.py app/market_scanner.py web/main.py web/templates/base.html web/static/service-worker.js tests/js/sw_push_harness.js tests/test_radar.py tests/test_push_policy.py tests/test_smc_alerts.py tests/test_service_worker.py tests/test_web_extras.py
git commit -m "Appicoon toont het aantal kansen in de zone, ook via de pushmelding"
```

---

### Task 7: Stip bij verouderde koersen (F7)

**Files:**
- Create: `app/freshness.py`
- Modify: `web/main.py` (`_price_fetched_at` naast `_price_cache` regel 347; `_cached_prices`; `api_radar` regel 588-591; `api_vandaag` regel 525-537; template-global)
- Modify: `web/templates/base.html` (stip in `.topbar-right`, scriptlijst)
- Create: `web/static/stale.js`
- Modify: `web/static/radar.js:46-55`, `web/static/vandaag.js:36-45` (refresh)
- Modify: `web/static/style.css`
- Create: `tests/test_freshness.py`, `tests/js/stale_harness.js`, `tests/test_static_js.py`
- Test: `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `WebCase` (Task 2), token `--amber` (Task 2).
- Produces:
  - `freshness.STALE_AFTER_S = 120`, `freshness.oldest_age(fetched_at: dict[str, float], coins: Iterable[str], now: float) -> Optional[int]`
  - response-header `X-Price-Age` (hele seconden) op `/api/radar` en `/api/vandaag`, afwezig als er geen meting is
  - `window.hesPriceSeen(ageSeconds)` en `window.hesStaleState(freshestAt, now, staleMs) -> "unknown"|"fresh"|"stale"` uit `stale.js`
  - `refresh(force)` in `radar.js` en `vandaag.js` geeft een Promise<boolean> terug (Task 9 gebruikt dit)
  - `tests/test_static_js.py` met helper `run_node(harness, target) -> dict` (Task 10 voegt een klasse toe)

- [ ] **Step 1: Schrijf de falende tests**

Create `tests/test_freshness.py`:

```python
import unittest

from app import freshness


class FreshnessTest(unittest.TestCase):
    def test_oldest_age_over_the_shown_coins(self):
        fetched = {"BTC": 1000.0, "ETH": 900.0, "SOL": 10.0}
        self.assertEqual(freshness.oldest_age(fetched, ["BTC", "ETH"], 1030.5), 130)
        self.assertEqual(freshness.oldest_age(fetched, ["BTC"], 1030.5), 30)

    def test_no_measurement_is_none_not_zero(self):
        self.assertIsNone(freshness.oldest_age({}, ["BTC"], 5.0))
        self.assertIsNone(freshness.oldest_age({"BTC": 1.0}, [], 5.0))

    def test_threshold_is_two_minutes(self):
        self.assertEqual(freshness.STALE_AFTER_S, 120)
```

Create `tests/js/stale_harness.js`:

```js
// Laadt stale.js zonder DOM en toetst de pure toestandsfunctie.
const fs = require("fs"), vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const s = ctx.hesStaleState;
console.log(JSON.stringify({ unknown: s(null, 1000, 120000), fresh: s(0, 120000, 120000), stale: s(0, 120001, 120000) }));
```

Create `tests/test_static_js.py`:

```python
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_node(harness: str, target: str) -> dict:
    out = subprocess.run(["node", str(ROOT / "tests/js" / harness), str(ROOT / "web/static" / target)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class StaleDotTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(run_node("stale_harness.js", "stale.js"), {"unknown": "unknown", "fresh": "fresh", "stale": "stale"})


if __name__ == "__main__":
    unittest.main()
```

`tests/test_web_extras.py`:

```python
class PriceAgeTest(WebCase):
    def setUp(self):
        super().setUp()
        self.main._price_fetched_at.clear()
        with db.session() as conn:
            conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr,
                            created_at, updated_at) VALUES ('XRP', 'long', 99.0, 101.0, 102.0, 97.0, 110.0, 1.0, ?, ?)""", (db.now_iso(), db.now_iso()))

    def test_fresh_fetch_gives_a_small_age(self):
        r = self.client.get("/api/radar")
        self.assertLessEqual(int(r.headers["X-Price-Age"]), 1)

    def test_failed_fetch_keeps_the_old_price_but_the_age_grows(self):
        import time
        self.client.get("/api/radar")
        self.main._price_fetched_at["XRP"] = time.time() - 300
        self.main._price_cache["XRP"] = (0.0, 100.0)                         # verlopen: er wordt opnieuw opgehaald
        with mock.patch.object(self.main.exchange, "fetch_last_price", side_effect=RuntimeError("storing")):
            r = self.client.get("/api/radar")
        self.assertGreaterEqual(int(r.headers["X-Price-Age"]), 300)

    def test_dot_carries_the_threshold(self):
        self.assertIn('data-stale-after="120"', self.client.get("/smc").text)
        self.assertIn("X-Price-Age", self.client.get("/api/vandaag").headers)
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_freshness tests.test_static_js tests.test_web_extras -v`
Expected: ERROR (`app.freshness` ontbreekt, `stale.js` ontbreekt, geen header).

- [ ] **Step 3: `app/freshness.py`**

```python
"""Hoe oud een getoonde koers is. web/main.py houdt per coin bij wanneer een koers voor het laatst echt van de beurs kwam: een mislukte
ophaal laat de oude koers staan (_cached_prices), dus zonder deze aparte tijd zou een koers van een uur oud er vers uitzien."""
from typing import Iterable, Optional

STALE_AFTER_S = 120


def oldest_age(fetched_at: dict[str, float], coins: Iterable[str], now: float) -> Optional[int]:
    """Leeftijd in hele seconden van de oudste koers onder `coins`; None als geen van die coins ooit een koers had."""
    ages = [now - fetched_at[c] for c in set(coins) if c in fetched_at]
    return int(max(ages)) if ages else None
```

- [ ] **Step 4: `web/main.py`**

Voeg `freshness` toe aan `from app import ...`. Direct onder `_price_cache: dict[...] = {}`:

```python
_price_fetched_at: dict[str, float] = {}       # wandklok (time.time) van de laatste geslaagde ophaal per coin, zie app/freshness.py
```

In `_cached_prices`, in de lus `for coin, price in zip(stale, ...)`, als eerste regel van de lus:

```python
        if price is not None:
            _price_fetched_at[coin] = time.time()
```

Na `templates.env.globals["pause_text"] = ...`:

```python
templates.env.globals["stale_after_s"] = freshness.STALE_AFTER_S
```

Hulpfunctie vlak boven `api_radar`:

```python
def _age_header(coins) -> dict:
    age = freshness.oldest_age(_price_fetched_at, coins, time.time())
    return {} if age is None else {"X-Price-Age": str(age)}
```

`api_radar` wordt:

```python
@app.get("/api/radar")
async def api_radar(user: dict = Depends(require_login)):
    """Live status per radar-kaart, voor radar.js: nieuwe koers, afstand tot de limietorder, live R en de niveaus voor de grafiek.
    De leeftijd van de oudste koers staat in de header X-Price-Age, zodat de vorm van de payload per kaart gelijk blijft."""
    cards = await _radar_cards()
    return JSONResponse(radar.live_payload(cards), headers=_age_header({c["coin"] for c in cards}))
```

`api_vandaag` wordt:

```python
@app.get("/api/vandaag")
async def api_vandaag(user: dict = Depends(require_login)):
    """Live koersen en afstand tot de voorwaarde per scenario, voor vandaag.js."""
    ctx = await _vandaag_context(user)
    payload = {
        "prices": ctx["prices"],
        "scenarios": {str(sc["id"]): {"state": sc["state"], "label": sc["state_label"], "to_trigger_pct": sc["to_trigger_pct"],
                                       "hours_left": sc["hours_left"], "chart": sc["chart"]}
                      for s in ctx["scripts"] for sc in s["scenarios"]},
    }
    return JSONResponse(payload, headers=_age_header(ctx["prices"].keys()))
```

- [ ] **Step 5: Stip en script in `base.html`**

In `.topbar-right`, direct vóór `<span class="live-pill">` (na de pauzeknop):

```html
      <span id="price-dot" class="price-dot" data-stale-after="{{ stale_after_s }}" hidden role="img" aria-label="Koersen zijn actueel" title="Koersen zijn actueel"></span>
```

Scriptlijst, na `alarm.js`:

```html
<script src="{{ asset('stale.js') }}" defer></script>
```

- [ ] **Step 6: `web/static/stale.js`**

```js
// Stip in de bovenbalk: groen zolang de getoonde koersen vers zijn, oranje als de nieuwste koers ouder is dan data-stale-after seconden
// (freshness.STALE_AFTER_S). Bron is de koersstroom van de beurs (live.js zet window.__liveAt) of de leeftijd die de server bij een poll
// meestuurt (X-Price-Age). Op pagina's zonder koersen blijft de stip verborgen.
(function (root) {
  function state(freshestAt, now, staleMs) {
    if (freshestAt === null || freshestAt === undefined) return "unknown";
    return now - freshestAt > staleMs ? "stale" : "fresh";
  }
  root.hesStaleState = state;
  if (typeof document === "undefined") return;
  var dot = document.getElementById("price-dot");
  if (!dot) return;
  var staleMs = (parseInt(dot.getAttribute("data-stale-after"), 10) || 120) * 1000, polledAt = null;

  function tick() {
    var freshest = polledAt;
    if (root.__liveAt && (freshest === null || root.__liveAt > freshest)) freshest = root.__liveAt;
    var s = state(freshest, Date.now(), staleMs);
    dot.hidden = s === "unknown";
    dot.classList.toggle("is-stale", s === "stale");
    var text = s === "stale" ? "Koersen zijn ouder dan " + Math.round(staleMs / 60000) + " minuten" : "Koersen zijn actueel";
    dot.setAttribute("aria-label", text);
    dot.title = text;
  }

  root.hesPriceSeen = function (ageSeconds) {
    var age = parseFloat(ageSeconds);
    if (isNaN(age)) return;
    polledAt = Date.now() - age * 1000;
    tick();
  };
  setInterval(tick, 5000);
})(typeof window !== "undefined" ? window : globalThis);
```

- [ ] **Step 7: Polls lezen de leeftijd**

`web/static/radar.js`: vervang de functie `refresh` en de regels eronder (tot het einde van de IIFE) door:

```js
  function refresh(force) {
    if (document.hidden && !force) return Promise.resolve(false);
    return fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (resp) {
        if (!resp.ok) return false;
        var age = resp.headers.get("X-Price-Age");
        if (age !== null && window.hesPriceSeen) window.hesPriceSeen(age);
        return resp.json().then(function (payload) { apply(payload); return true; });
      })
      .catch(function () { return false; /* een mislukte verversing laat de laatste stand staan */ });
  }

  refresh();
  setInterval(refresh, INTERVAL_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
```

`web/static/vandaag.js`: vervang `refresh` en de regels eronder op dezelfde manier, met `/api/vandaag`:

```js
  function refresh(force) {
    if (document.hidden && !force) return Promise.resolve(false);
    return fetch("/api/vandaag", { cache: "no-store", credentials: "same-origin" })
      .then(function (resp) {
        if (!resp.ok) return false;
        var age = resp.headers.get("X-Price-Age");
        if (age !== null && window.hesPriceSeen) window.hesPriceSeen(age);
        return resp.json().then(function (payload) { apply(payload); return true; });
      })
      .catch(function () { return false; /* een mislukte verversing laat de laatste stand staan */ });
  }

  refresh();
  setInterval(refresh, INTERVAL_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
```

- [ ] **Step 8: CSS**

Onderaan `web/static/style.css`:

```css
/* Versheid van de koersen (stale.js): groen is gemeten en vers, oranje betekent dat je naar een oude koers kijkt. Geen animatie. */
.price-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); flex: none; }
.price-dot[hidden] { display: none; }
.price-dot.is-stale { background: var(--amber); }
```

- [ ] **Step 9: Draai de tests en de JS-checks**

Run: `python3 -m unittest tests.test_freshness tests.test_static_js tests.test_web_extras tests.test_web_radar tests.test_web_vandaag -v && node --check web/static/stale.js && node --check web/static/radar.js && node --check web/static/vandaag.js`
Expected: PASS

- [ ] **Step 10: Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_7.py` (de pagina zet de stip na de eerste poll; daarna doen we alsof de laatste koers 3 minuten oud is):

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/smc")
    page.wait_for_selector("#price-dot:not([hidden])", timeout=10000)
    assert "is-stale" not in page.get_attribute("#price-dot", "class")
    page.evaluate("window.__liveAt = 0; window.hesPriceSeen(180)")
    assert "is-stale" in page.get_attribute("#price-dot", "class")
    assert "ouder dan 2 minuten" in page.get_attribute("#price-dot", "aria-label")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_7.py $SCRATCH`
Expected: `ok`

- [ ] **Step 11: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/freshness.py web/main.py web/templates/base.html web/static/stale.js web/static/radar.js web/static/vandaag.js web/static/style.css tests/test_freshness.py tests/js/stale_harness.js tests/test_static_js.py tests/test_web_extras.py
git commit -m "Stip bij verouderde koersen: oranje na twee minuten zonder verse koers"
```

---

### Task 8: Banner 'Meldingen staan uit op dit apparaat' (F8)

**Files:**
- Modify: `web/static/push-subscribe.js` (hele bestand)
- Create: `web/static/push-banner.js`
- Modify: `web/templates/base.html` (banner na `#offline-banner`, regel 38; scriptlijst)
- Modify: `web/templates/account.html:220` (scriptregel weg)
- Modify: `web/static/style.css`
- Test: `tests/test_web_extras.py`

**Interfaces:**
- Consumes: niets uit eerdere taken.
- Produces: `window.hesPushSubscribe(onStatus?: (text) => void) -> Promise<boolean>` (true als het abonnement is opgeslagen).

- [ ] **Step 1: Schrijf de falende test**

`tests/test_web_extras.py`:

```python
class PushBannerTest(WebCase):
    def test_banner_is_on_every_page_and_subscribe_code_loads_once(self):
        r = self.client.get("/vandaag")
        self.assertIn('id="push-banner"', r.text)
        self.assertIn("Meldingen staan uit op dit apparaat.", r.text)
        self.assertIn("push-banner.js", r.text)
        account = self.client.get("/account").text
        self.assertEqual(account.count("push-subscribe.js"), 1)            # anders koppelt de knop twee keer
```

- [ ] **Step 2: Draai de test en zie hem falen**

Run: `python3 -m unittest tests.test_web_extras.PushBannerTest -v`
Expected: FAIL

- [ ] **Step 3: `web/static/push-subscribe.js` herschrijven tot herbruikbare functie**

Volledige nieuwe inhoud:

```js
(function () {
  "use strict";

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; i++) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
  }

  // Tijdelijk: op iOS is er geen console te zien zonder Mac + Safari Web
  // Inspector, dus rapporteert elke stap hierheen in plaats van er alleen
  // op te vertrouwen dat de gebruiker de tekst onder de knop leest.
  // Belandt in journalctl -u crypto-web. Weer verwijderen zodra de bug
  // gevonden is.
  function report(message) {
    try {
      fetch("/api/push/debug-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message }),
      }).catch(function () {});
    } catch (e) {}
  }

  // Ook gebruikt door de banner (push-banner.js): één aanmeldroute, zodat een fix voor iOS op beide plekken tegelijk geldt.
  async function subscribe(onStatus) {
    const showStatus = function (text) {
      if (onStatus) onStatus(text);
      report(text);
    };

    report("subscribe() gestart, klik geregistreerd");

    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        showStatus("Pushmeldingen vereisen een geïnstalleerde app (voeg toe aan beginscherm).");
        return false;
      }
      report("serviceWorker + PushManager aanwezig");

      const permission = await Notification.requestPermission();
      report("Notification.requestPermission() -> " + permission);
      if (permission !== "granted") {
        showStatus("Toestemming niet gegeven, geen pushmeldingen mogelijk.");
        return false;
      }

      const reg = await navigator.serviceWorker.ready;
      report("serviceWorker.ready opgelost, scope: " + reg.scope);

      const keyResp = await fetch("/api/push/vapid-public-key");
      report("vapid-public-key response status: " + keyResp.status);
      const { key } = await keyResp.json();
      report("vapid key ontvangen, lengte: " + (key ? key.length : 0));

      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      report("pushManager.subscribe() gelukt, endpoint: " + subscription.endpoint.slice(0, 60));

      const subResp = await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign(subscription.toJSON(), { device_label: navigator.userAgent.slice(0, 60) })),
      });
      report("api/push/subscribe response status: " + subResp.status);
      if (!subResp.ok) {
        showStatus("Kon meldingen niet opslaan, probeer het opnieuw.");
        return false;
      }

      showStatus("Meldingen staan aan op dit apparaat.");
      return true;
    } catch (err) {
      showStatus("Kon meldingen niet aanzetten: " + err.name + ": " + err.message);
      return false;
    }
  }

  window.hesPushSubscribe = subscribe;

  const btn = document.getElementById("push-subscribe-btn");
  if (btn) {
    const statusEl = document.getElementById("push-subscribe-status");
    btn.addEventListener("click", function () {
      subscribe(function (text) {
        if (statusEl) {
          statusEl.hidden = false;
          statusEl.textContent = text;
        }
      });
    });
    report("push-subscribe.js geladen, knop-listener gekoppeld");
  }
})();
```

- [ ] **Step 4: `web/static/push-banner.js`**

```js
// Banner bovenaan als dit apparaat geen meldingen krijgt. Zonder PushManager (Safari op iOS buiten een geïnstalleerde app) kan de knop
// niets, dus dan blijft de banner weg; staat de toestemming op geblokkeerd, dan kan alleen de telefoon zelf het herstellen.
// Wegtikken onthoudt dit apparaat 7 dagen.
(function () {
  var banner = document.getElementById("push-banner");
  if (!banner) return;
  var text = document.getElementById("push-banner-text"), btn = document.getElementById("push-banner-btn"), close = document.getElementById("push-banner-close");
  var KEY = "hespulse_push_banner_until", HIDE_MS = 7 * 24 * 3600 * 1000;

  function hiddenByUser() {
    try { return Number(localStorage.getItem(KEY) || 0) > Date.now(); } catch (e) { return false; }
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window) || hiddenByUser()) return;

  close.addEventListener("click", function () {
    banner.hidden = true;
    try { localStorage.setItem(KEY, String(Date.now() + HIDE_MS)); } catch (e) { /* privévenster: alleen voor nu weg */ }
  });
  btn.addEventListener("click", function () {
    if (!window.hesPushSubscribe) return;
    btn.disabled = true;
    window.hesPushSubscribe(function (t) { text.textContent = t; }).then(function (ok) {
      btn.disabled = false;
      if (ok) setTimeout(function () { banner.hidden = true; }, 1500);
    });
  });

  navigator.serviceWorker.ready
    .then(function (reg) { return reg.pushManager.getSubscription(); })
    .then(function (sub) {
      if (sub && Notification.permission === "granted") return;
      if (Notification.permission === "denied") {
        text.textContent = "Meldingen zijn geblokkeerd. Zet ze aan in de instellingen van je telefoon.";
        btn.hidden = true;
      }
      banner.hidden = false;
    })
    .catch(function () {});
})();
```

- [ ] **Step 5: Markup en scripts**

`web/templates/base.html`, direct na de regel met `id="offline-banner"`:

```html
{% if user %}
<div id="push-banner" class="push-banner" hidden role="status">
  <span id="push-banner-text">Meldingen staan uit op dit apparaat.</span>
  <button type="button" id="push-banner-btn">Zet aan</button>
  <button type="button" id="push-banner-close" class="push-banner-close" aria-label="Banner verbergen">&times;</button>
</div>
{% endif %}
```

Scriptlijst, na `stale.js`:

```html
{% if user %}<script src="{{ asset('push-subscribe.js') }}" defer></script>
<script src="{{ asset('push-banner.js') }}" defer></script>{% endif %}
```

`web/templates/account.html`: verwijder de regel `<script src="{{ asset('push-subscribe.js') }}" defer></script>`.

- [ ] **Step 6: CSS**

Onderaan `web/static/style.css`:

```css
/* Banner als dit apparaat geen meldingen krijgt (push-banner.js). */
.push-banner { display: flex; align-items: center; gap: var(--space-5); flex-wrap: wrap; margin: var(--space-4) 16px 0; padding: var(--space-5) var(--space-6);
               background: var(--accent-bg); border: 1px solid var(--accent); border-radius: var(--radius); color: var(--text); font-size: var(--text-sm); }
.push-banner[hidden] { display: none; }
.push-banner span { flex: 1 1 200px; }
.push-banner-close { background: none; border: 0; color: var(--muted); font-size: var(--text-lg); min-width: 32px; min-height: 32px; cursor: pointer; }
```

- [ ] **Step 7: Draai de tests en de JS-checks**

Run: `python3 -m unittest tests.test_web_extras -v && node --check web/static/push-subscribe.js && node --check web/static/push-banner.js`
Expected: PASS

- [ ] **Step 8: Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_8.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/vandaag")
    page.wait_for_selector("#push-banner:not([hidden])", timeout=10000)
    if page.evaluate("Notification.permission") == "denied":
        assert "geblokkeerd" in page.locator("#push-banner-text").inner_text() and page.locator("#push-banner-btn").is_hidden()
    else:
        assert page.locator("#push-banner-text").inner_text() == "Meldingen staan uit op dit apparaat."
        page.click("#push-banner-btn")
        page.wait_for_function("document.getElementById('push-banner-text').textContent !== 'Meldingen staan uit op dit apparaat.'")
        print("na tik:", page.locator("#push-banner-text").inner_text())
    page.click("#push-banner-close")
    page.reload(); page.wait_for_timeout(1500)
    assert page.locator("#push-banner").is_hidden(), "7 dagen verborgen na wegtikken"
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_8.py $SCRATCH`
Expected: een statusregel (headless Chromium geeft meestal "Toestemming niet gegeven..." of "Kon meldingen niet aanzetten...") en daarna `ok`. Controleer ook op `/account` dat de bestaande knop "Meldingen aanzetten" nog een status toont.

- [ ] **Step 9: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add web/static/push-subscribe.js web/static/push-banner.js web/templates/base.html web/templates/account.html web/static/style.css tests/test_web_extras.py
git commit -m "Banner als meldingen uit staan op dit apparaat, met knop om ze aan te zetten"
```

---

### Task 9: Verversen door te trekken en tik op de actieve tab (F1, F2)

**Files:**
- Modify: `web/static/smooth.js:48-53` (touchend)
- Modify: `web/static/radar.js`, `web/static/vandaag.js` (na `refresh`)
- Modify: `web/static/tabbar.js` (onderaan)
- Modify: `web/templates/base.html:120-128` (klik-listener van de voortgangsbalk)

**Interfaces:**
- Consumes: `refresh(force)` die een Promise<boolean> teruggeeft (Task 7).
- Produces: `window.hesRefresh() -> Promise<boolean>` op Radar en Vandaag.

Deze taak is alleen JS; de testcyclus is `node --check` plus Playwright.

- [ ] **Step 1: Schrijf de falende Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_9.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

PULL = """async () => {
  const t = (y) => new Touch({ identifier: 1, target: document.body, clientX: 100, clientY: y });
  document.dispatchEvent(new TouchEvent('touchstart', { touches: [t(10)], bubbles: true }));
  document.dispatchEvent(new TouchEvent('touchmove', { touches: [t(140)], bubbles: true }));
  document.dispatchEvent(new TouchEvent('touchend', { touches: [], bubbles: true }));
}"""

with sync_playwright() as pw:
    for path, api in (("/smc", "/api/radar"), ("/vandaag", "/api/vandaag")):
        browser, ctx, page = open_page(pw, path)
        page.evaluate("window.__marker = 1")
        with page.expect_request(lambda r: r.url.endswith(api)):
            page.evaluate(PULL)
        page.wait_for_function("document.querySelector('.pull-hint') && document.querySelector('.pull-hint').textContent === 'Bijgewerkt'")
        assert page.evaluate("window.__marker") == 1, "geen volledige herlaadslag"
        page.evaluate("window.scrollTo(0, 1500)")
        page.wait_for_timeout(300)
        page.evaluate("window.scrollTo(0, 1400)")                      # omhoog scrollen: de tabbalk komt terug
        page.wait_for_timeout(300)
        page.click(".tabbar a.tab[aria-current='page']")
        page.wait_for_function("window.scrollY === 0")
        assert page.url.endswith(path) and page.evaluate("window.__marker") == 1
        assert not page.evaluate("document.documentElement.classList.contains('page-transition-out')"), "pagina mag niet uitfaden"
        browser.close()
    print("ok")
```

Run: `python3 $SCRATCH/check_9.py $SCRATCH`
Expected: FAIL (de pagina herlaadt, `__marker` is weg, of de tik navigeert opnieuw).

- [ ] **Step 2: `window.hesRefresh` op Radar en Vandaag**

In `web/static/radar.js` en in `web/static/vandaag.js`, direct onder de functie `refresh`:

```js
  window.hesRefresh = function () { return refresh(true); };
```

- [ ] **Step 3: Trekken ververst gegevens in `smooth.js`**

Vervang de `touchend`-listener door:

```js
  document.addEventListener("touchend", function () {
    var go = startY !== null && pulled >= THRESHOLD && window.scrollY <= 0;
    startY = null;
    if (!go) {
      if (hint) { hint.style.opacity = "0"; hint.style.transform = "translate(-50%, 0)"; }
      return;
    }
    var h = ensureHint();
    h.textContent = "Verversen";
    // Radar en Vandaag halen alleen hun gegevens opnieuw op (window.hesRefresh): scrollpositie en open grafieken blijven staan.
    if (typeof window.hesRefresh !== "function") { location.reload(); return; }
    Promise.resolve(window.hesRefresh()).then(function (ok) {
      h.textContent = ok ? "Bijgewerkt" : "Verversen lukte niet";
      setTimeout(function () { h.style.opacity = "0"; h.style.transform = "translate(-50%, 0)"; }, 900);
    });
  }, { passive: true });
```

Pas ook de kopcommentaarregel (3) van `smooth.js` aan naar: `// (3) trek de pagina bovenaan omlaag om te verversen, zoals in een app (Radar en Vandaag zonder herlaadslag), en de tabtitel toont de dichtstbijzijnde kans.`

- [ ] **Step 4: Tik op de actieve tab in `tabbar.js`**

Onderaan:

```js
// Een tik op de tab van de pagina waar je al bent brengt je naar boven, zoals in elke telefoon-app. aria-current komt van de server;
// smooth.js zet is-active al bij pointerdown, dus daar kun je hier niet op vertrouwen.
(function () {
  var bar = document.querySelector(".tabbar");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var tab = e.target.closest && e.target.closest("a.tab[aria-current='page']");
    if (!tab) return;
    e.preventDefault();
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
  });
})();
```

- [ ] **Step 5: Voortgangsbalk negeert een afgevangen klik**

De klik-listener van de voortgangsbalk in `base.html` start bij elke link-klik `HP.progressStart()`, die de pagina 4 seconden laat uitfaden. Een tik op de actieve tab navigeert niet meer, dus die klik moet hij overslaan. In `base.html`, in `document.addEventListener("click", function (e) {` van de voortgangsbalk, als eerste regel:

```js
      if (e.defaultPrevented) return;      // tabbar.js vangt een tik op de actieve tab af: geen navigatie, dus geen uitfade
```

(De listener van `tabbar.js` zit op `.tabbar` en draait in de bubbelfase vóór deze listener op `document`.)

- [ ] **Step 6: JS-checks en Playwright**

Run: `node --check web/static/smooth.js && node --check web/static/radar.js && node --check web/static/vandaag.js && node --check web/static/tabbar.js && python3 $SCRATCH/check_9.py $SCRATCH`
Expected: geen uitvoer van node, daarna `ok`.

- [ ] **Step 7: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add web/static/smooth.js web/static/radar.js web/static/vandaag.js web/static/tabbar.js web/templates/base.html
git commit -m "Trekken ververst Radar en Vandaag zonder herladen, tik op de actieve tab gaat naar boven"
```

---

### Task 10: Risico- en beloningsvlak op de candlegrafiek (G1)

**Files:**
- Modify: `web/static/levelchart.js`
- Create: `tests/js/levelchart_harness.js`
- Test: `tests/test_static_js.py`

**Interfaces:**
- Consumes: `tests/test_static_js.py:run_node` (Task 7). Spec-velden van `trade_plan.chart_spec` (`stop`, `take`, `limit`, `entry`).
- Produces: `window.hesLevelChart.areas(spec) -> [{key: "risk"|"reward", base: number, value: number}]`.

- [ ] **Step 1: Schrijf de falende test**

Create `tests/js/levelchart_harness.js`:

```js
// Laadt levelchart.js zonder grafiekbibliotheek en zonder kaarten en toetst de pure functie die de vlakken bepaalt.
const fs = require("fs"), vm = require("vm");
const ctx = { window: {}, document: { querySelectorAll: () => [], documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => "" }) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const areas = ctx.window.hesLevelChart.areas;
console.log(JSON.stringify({
  open: areas({ entry: 100, limit: 100, stop: 97, take: 106 }),
  setup: areas({ entry: null, limit: 100, stop: 97, take: 106 }),
  short: areas({ entry: null, limit: 100, stop: 103, take: 94 }),
  noStop: areas({ entry: null, limit: 100, stop: null, take: 106 }),
  nothing: areas({ entry: null, limit: null, stop: 97, take: 106 }),
}));
```

In `tests/test_static_js.py`, nieuwe klasse:

```python
@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class LevelChartAreasTest(unittest.TestCase):
    def test_risk_between_entry_and_stop_reward_between_entry_and_take(self):
        out = run_node("levelchart_harness.js", "levelchart.js")
        self.assertEqual(out["open"], [{"key": "risk", "base": 100, "value": 97}, {"key": "reward", "base": 100, "value": 106}])
        self.assertEqual(out["setup"], out["open"])                         # zonder entry geldt de limiet
        self.assertEqual(out["short"], [{"key": "risk", "base": 100, "value": 103}, {"key": "reward", "base": 100, "value": 94}])
        self.assertEqual(out["noStop"], [{"key": "reward", "base": 100, "value": 106}])
        self.assertEqual(out["nothing"], [])
```

- [ ] **Step 2: Draai de test en zie hem falen**

Run: `python3 -m unittest tests.test_static_js -v`
Expected: ERROR (`areas` is undefined, `TypeError` in node).

- [ ] **Step 3: Pure functie en API in `levelchart.js`**

Direct na `window.hesLevelChart = api;`:

```js
  api.areas = areas;
```

Bij de andere hulpfuncties (na `precision`):

```js
  // Risico en beloning van het plan zelf: van instap (of limiet) tot stop, en van instap tot doel. Geen schatting, alleen de niveaus.
  function areas(s) {
    var base = typeof s.entry === "number" && isFinite(s.entry) ? s.entry : s.limit;
    if (typeof base !== "number" || !isFinite(base)) return [];
    var out = [];
    if (typeof s.stop === "number" && isFinite(s.stop) && s.stop !== base) out.push({ key: "risk", base: base, value: s.stop });
    if (typeof s.take === "number" && isFinite(s.take) && s.take !== base) out.push({ key: "reward", base: base, value: s.take });
    return out;
  }

  function rgba(hex, a) {
    var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex).trim());
    return m ? "rgba(" + parseInt(m[1], 16) + "," + parseInt(m[2], 16) + "," + parseInt(m[3], 16) + "," + a + ")" : hex;
  }

  function areaSeries(chart, color) {
    var fill = rgba(color, 0.1), none = "rgba(0,0,0,0)";
    return chart.addBaselineSeries({
      baseValue: { type: "price", price: 0 },
      topLineColor: none, bottomLineColor: none,
      topFillColor1: fill, topFillColor2: fill, bottomFillColor1: fill, bottomFillColor2: fill,
      lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      autoscaleInfoProvider: function () { return null; },
    });
  }

  function syncAreas(lc) {
    var s = spec(lc.el), wanted = {};
    (s ? areas(s) : []).forEach(function (a) { wanted[a.key] = a; });
    ["risk", "reward"].forEach(function (k) {
      var a = wanted[k], series = lc.areas[k];
      if (!a || !lc.candles.length) { series.setData([]); return; }
      series.applyOptions({ baseValue: { type: "price", price: a.base } });
      series.setData(lc.candles.map(function (c) { return { time: c.time, value: a.value }; }));
    });
  }
```

- [ ] **Step 4: Vlakken in de grafiek**

In `create`, vervang `var lc = { el: el, chart: chart, lines: {}, candles: [], dead: false };` door:

```js
    var lc = { el: el, chart: chart, lines: {}, candles: [], dead: false, areas: {} };
    // Eerst toegevoegd, dus onderop: zone en candles blijven er leesbaar overheen.
    lc.areas.risk = areaSeries(chart, red);
    lc.areas.reward = areaSeries(chart, green);
```

In `load`, na `syncBand(lc);`:

```js
      syncAreas(lc);
```

In `api.update`, na `syncBand(lc);`:

```js
    syncAreas(lc);
```

Werk de kopcommentaar bij met één regel onder "- Live: ...": `   - Rood vlak van instap (of limiet) tot stop, groen van instap tot doel (areas): de niveaus van het plan, geen schatting.`

- [ ] **Step 5: Draai de test en de JS-check**

Run: `python3 -m unittest tests.test_static_js -v && node --check web/static/levelchart.js`
Expected: PASS

- [ ] **Step 6: Playwright-controle (beeld)**

Server volgens de controle-opzet. `$SCRATCH/check_10.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/smc")
    chart = page.locator("[data-levelchart]").first
    chart.scroll_into_view_if_needed()
    page.wait_for_selector("[data-levelchart] canvas", timeout=10000)
    page.wait_for_timeout(800)
    chart.screenshot(path=sys.argv[1] + "/g1.png")
    print("ok", sys.argv[1] + "/g1.png")
    browser.close()
```

Run: `python3 $SCRATCH/check_10.py $SCRATCH`
Expected: `ok`; open `g1.png` en zie een lichtrood vlak van de limiet tot de stop en een lichtgroen vlak van de limiet tot het doel, onder de candles.

- [ ] **Step 7: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add web/static/levelchart.js tests/js/levelchart_harness.js tests/test_static_js.py
git commit -m "Grafiek: rood vlak tot de stop, groen vlak tot het doel"
```

---

### Task 11: Afstandsbalk op elke Radar-kaart (G2)

**Files:**
- Modify: `app/trade_plan.py` (na `distance_to_limit_pct`)
- Modify: `app/radar.py` (`setup_card`, `signal_card`, `live_payload`)
- Modify: `web/templates/smc.html` (bouwende setup, na de `radar-state`-regel)
- Modify: `web/static/radar.js` (`apply`)
- Modify: `web/static/style.css`
- Test: `tests/test_trade_plan.py`, `tests/test_radar.py`, `tests/test_web_radar.py`

**Interfaces:**
- Consumes: `radar.js` `apply(payload)` (bestaand), refresh uit Task 7.
- Produces:
  - `trade_plan.APPROACH_SCALE_PCT = 3.0`, `trade_plan.approach_pct(distance_pct: Optional[float], scale_pct: float = APPROACH_SCALE_PCT) -> Optional[float]`
  - kaartveld en payloadveld `approach_pct` (None bij een open trade of zonder koers)

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_trade_plan.py` (nieuwe klasse):

```python
class ApproachTest(unittest.TestCase):
    def test_position_from_far_to_at_the_entry(self):
        self.assertIsNone(tp.approach_pct(None))
        self.assertEqual(tp.approach_pct(0.0), 100.0)
        self.assertEqual(tp.approach_pct(-0.4), 100.0)                       # al voorbij de limiet: vol
        self.assertAlmostEqual(tp.approach_pct(1.5), 50.0)
        self.assertEqual(tp.approach_pct(3.0), 0.0)
        self.assertEqual(tp.approach_pct(8.0), 0.0)
```

(Gebruik de import die het bestand al heeft voor `app.trade_plan`; heet die anders dan `tp`, pas de naam aan.)

`tests/test_radar.py`, in `RadarTests`:

```python
    def test_afstandsbalk_volgt_de_afstand_tot_de_limiet(self):
        card = radar.setup_card(SETUP, 102.0)                                # 2% van de limiet 100
        self.assertAlmostEqual(card["approach_pct"], 100 - 2 / 3 * 100)
        self.assertIsNone(radar.setup_card(SETUP, None)["approach_pct"])
        self.assertIsNone(radar.signal_card(SIGNAL, 99.0)["approach_pct"])
        payload = radar.live_payload([card])
        self.assertAlmostEqual(payload["setup:7"]["approach_pct"], card["approach_pct"])
```

`tests/test_web_radar.py`, in `WebRadarTests`:

```python
    def test_afstandsbalk_op_de_kaart(self):
        r = self.client.get("/smc")
        self.assertIn('data-radar="approach"', r.text)
        self.assertIn("left: 33.3%", r.text)                                 # XRP: koers 102, limiet 100, 2% van 3%
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_trade_plan tests.test_radar tests.test_web_radar -v`
Expected: FAIL (`approach_pct` ontbreekt).

- [ ] **Step 3: `trade_plan.approach_pct`**

Na `distance_to_limit_pct`:

```python
APPROACH_SCALE_PCT = 3.0


def approach_pct(distance_pct: Optional[float], scale_pct: float = APPROACH_SCALE_PCT) -> Optional[float]:
    """Plek van de koers op de afstandsbalk: 0 (scale_pct of verder weg) tot 100 (op de instap). Zelfde schaal als de afstandsring op de
    Setups-kaarten (ring.js, RING_SCALE_PCT = 3), zodat ring en balk hetzelfde zeggen. Voorbij de limiet is vol."""
    if distance_pct is None:
        return None
    if distance_pct <= 0:
        return 100.0
    return max(0.0, 100.0 - distance_pct / scale_pct * 100.0)
```

- [ ] **Step 4: Kaart en payload**

`app/radar.py`, `setup_card`-dict, na `"distance_pct": distance,`:

```python
        "approach_pct": tp.approach_pct(distance),
```

`signal_card`-dict, na `"distance_pct": None,`:

```python
        "approach_pct": None,
```

`live_payload`, in de binnenste dict na `"distance_pct": c["distance_pct"],`:

```python
            "approach_pct": c["approach_pct"],
```

- [ ] **Step 5: Template**

`web/templates/smc.html`, in de lus over `setup_cards`, direct na `<div class="radar-state ..." data-radar="state">...</div>`:

```jinja
      <div class="approach" role="img" aria-label="Afstand van de koers tot je instap"{% if c.approach_pct is none %} hidden{% endif %}>
        <span class="approach-track"></span>
        <span class="approach-dot" data-radar="approach" style="left: {{ "%.1f"|format(c.approach_pct or 0) }}%"></span>
        <span class="approach-end">Instap</span>
      </div>
```

- [ ] **Step 6: Live bijwerken in `radar.js`**

In `apply`, na het blok dat `distance` zet:

```js
      var approach = card.querySelector(".approach"), dot = card.querySelector('[data-radar="approach"]');
      if (approach && dot) {
        var has = data.approach_pct !== null && data.approach_pct !== undefined;
        approach.hidden = !has;
        if (has) dot.style.left = data.approach_pct.toFixed(1) + "%";
      }
```

- [ ] **Step 7: CSS**

Onderaan `web/static/style.css`:

```css
/* Afstandsbalk (radar.approach_pct): rechts is de instap, de stip is de koers. Zelfde schaal van 3% als de afstandsring. */
.approach { position: relative; height: 16px; margin-right: 46px; }
.approach-track { position: absolute; left: 0; right: 0; top: 7px; height: 2px; border-radius: 1px; background: linear-gradient(90deg, var(--border-strong), var(--accent)); }
.approach-dot { position: absolute; top: 3px; width: 10px; height: 10px; margin-left: -5px; border-radius: 50%; background: var(--text);
                box-shadow: 0 0 0 2px var(--bg-elevated); transition: left 0.6s ease-out; }
.approach-end { position: absolute; left: 100%; top: 1px; margin-left: 6px; font-family: var(--mono); font-size: var(--text-2xs); color: var(--accent); }
@media (prefers-reduced-motion: reduce) { .approach-dot { transition: none; } }
```

- [ ] **Step 8: Draai de tests en de JS-check**

Run: `python3 -m unittest tests.test_trade_plan tests.test_radar tests.test_web_radar -v && node --check web/static/radar.js`
Expected: PASS

- [ ] **Step 9: Playwright-controle**

Server volgens de controle-opzet (BTC-setup: limiet 60500, koers 60800, afstand 0,50%, dus de stip op 83,5%). `$SCRATCH/check_11.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/smc")
    styles = [el.get_attribute("style") for el in page.locator('[data-radar="approach"]').all()]
    print(styles)
    assert any("left: 83.5%" in st for st in styles), "BTC: 0,50% van de limiet"
    assert any("left: 100.0%" in st for st in styles), "ETH staat al in de zone: vol"
    page.locator(".approach").first.screenshot(path=sys.argv[1] + "/g2.png")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_11.py $SCRATCH`
Expected: de lijst bevat `left: 83.5%` en `left: 100.0%`, daarna `ok`.

- [ ] **Step 10: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/trade_plan.py app/radar.py web/templates/smc.html web/static/radar.js web/static/style.css tests/test_trade_plan.py tests/test_radar.py tests/test_web_radar.py
git commit -m "Afstandsbalk op elke Radar-kaart: stip voor de koers richting de instap"
```

---

### Task 12: Minigrafiek van 24 uur per kaart (G3)

**Files:**
- Modify: `app/radar.py` (onderaan)
- Modify: `web/main.py:594-619` (candle-cache naar hulpfunctie, nieuwe route `/api/sparklines`)
- Modify: `web/templates/smc.html` (`radar-head` in beide kaartlussen)
- Create: `web/static/spark.js`
- Modify: `web/static/style.css`
- Test: `tests/test_radar.py`, `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `WebCase` (Task 2).
- Produces:
  - `radar.SPARK_HOURS = 24`, `radar.spark_path(closes: list[float], width: float = 120, height: float = 28) -> str`, `radar.spark(closes: list[float]) -> Optional[dict]` met `{"path", "change_pct", "change_text"}`
  - `web.main._cached_candles(coin: str, tf: str) -> Optional[list]` (async)
  - `GET /api/sparklines?coins=BTC,ETH` -> `{coin: {"path", "change_pct", "change_text"}}`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_radar.py`:

```python
class SparkTests(unittest.TestCase):
    def test_path_spans_the_box_oldest_left(self):
        path = radar.spark_path([1.0, 3.0, 2.0], width=104, height=24)
        self.assertEqual(path, "M2.0,22.0 L52.0,2.0 L102.0,12.0")

    def test_flat_series_is_a_middle_line_and_short_series_is_empty(self):
        self.assertEqual(radar.spark_path([5.0, 5.0], width=104, height=24), "M2.0,12.0 L102.0,12.0")
        self.assertEqual(radar.spark_path([5.0]), "")

    def test_spark_has_change_over_the_period(self):
        s = radar.spark([100.0, 103.0, 102.0])
        self.assertAlmostEqual(s["change_pct"], 2.0)
        self.assertEqual(s["change_text"], "+2,0% 24u")
        self.assertIsNone(radar.spark([100.0]))
        self.assertIsNone(radar.spark([0.0, 1.0]))
```

`tests/test_web_extras.py`:

```python
class SparklineRouteTest(WebCase):
    def frame(self):
        import pandas as pd
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        return pd.DataFrame([{"timestamp": pd.Timestamp(start + timedelta(hours=i)), "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
                              "close": 100.0 + i, "volume": 1.0} for i in range(200)])

    def test_one_fetch_per_coin_and_unknown_coins_are_ignored(self):
        self.main._candle_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", return_value=self.frame()) as fetch:
            data = self.client.get("/api/sparklines?coins=BTC,ETH,BTC,NOPE").json()
            self.client.get("/api/sparklines?coins=BTC")
        self.assertEqual(set(data), {"BTC", "ETH"})
        self.assertEqual(fetch.call_count, 2)                                 # de tweede aanroep komt uit de cache
        self.assertTrue(data["BTC"]["path"].startswith("M"))
        self.assertAlmostEqual(data["BTC"]["change_pct"], (299.0 - 276.0) / 276.0 * 100)     # laatste 24 slotkoersen

    def test_candle_route_still_works_from_the_shared_cache(self):
        self.main._candle_cache.clear()
        with mock.patch.object(self.main.exchange, "fetch_ohlcv", return_value=self.frame()):
            body = self.client.get("/api/radar_candles/BTC?tf=1h&limit=10").json()
        self.assertEqual(len(body["candles"]), 10)
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_radar tests.test_web_extras -v`
Expected: FAIL (`spark_path` ontbreekt, 404 op `/api/sparklines`).

- [ ] **Step 3: Pure functies in `app/radar.py`**

Onderaan:

```python
SPARK_HOURS = 24


def spark_path(closes: list[float], width: float = 120, height: float = 28) -> str:
    """SVG-pad van de slotkoersen (oudste eerst) in een vak van width bij height, met 2px marge. Leeg onder twee punten."""
    if len(closes) < 2:
        return ""
    pad = 2.0
    lo, hi = min(closes), max(closes)
    step = (width - 2 * pad) / (len(closes) - 1)

    def y(v: float) -> float:
        return height / 2 if hi == lo else pad + (hi - v) / (hi - lo) * (height - 2 * pad)

    return "M" + " L".join(f"{pad + i * step:.1f},{y(v):.1f}" for i, v in enumerate(closes))


def spark(closes: list[float]) -> Optional[dict]:
    """Wat spark.js per coin invult: het pad en de verandering over de periode."""
    if len(closes) < 2 or not closes[0]:
        return None
    change = (closes[-1] - closes[0]) / closes[0] * 100
    return {"path": spark_path(closes), "change_pct": change, "change_text": f"{change:+.1f}".replace(".", ",") + "% 24u"}
```

- [ ] **Step 4: Gedeelde candle-cache en route in `web/main.py`**

Vervang `api_radar_candles` (en zet de hulpfunctie erboven) door:

```python
async def _cached_candles(coin: str, tf: str) -> Optional[list]:
    """Candles per (coin, tf) uit de minuutcache, [[unix_s, open, high, low, close], ...] oudste eerst. Mislukt het ophalen, dan geldt de
    laatste goede stand (ook al is die verlopen); None als er nog nooit een goede ophaal was."""
    hit = _candle_cache.get((coin, tf))
    if not hit or time.monotonic() - hit[0] >= RADAR_CANDLE_TTL_SECONDS:
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, tf, RADAR_CANDLE_FETCH)
            rows = [[int(r.timestamp.timestamp()), float(r.open), float(r.high), float(r.low), float(r.close)] for r in df.itertuples()]
            hit = (time.monotonic(), rows)
            _candle_cache[(coin, tf)] = hit
        except Exception:
            if not hit:
                return None
    return hit[1]


@app.get("/api/radar_candles/{coin}")
async def api_radar_candles(coin: str, tf: str = "15m", limit: int = 96, user: dict = Depends(require_login)):
    """Compacte candles voor de grafiek op een radar-kaart: {"coin", "tf", "candles": [[unix_s, open, high, low, close], ...]},
    oudste eerst. Per (coin, tf) een minuut onthouden (_cached_candles): elke kaart en elke ingelogde gebruiker vraagt erom."""
    coin = coin.upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", coin) or tf not in RADAR_TIMEFRAMES:
        raise HTTPException(status_code=422)
    limit = max(10, min(limit, RADAR_CANDLE_FETCH))
    rows = await _cached_candles(coin, tf)
    if rows is None:
        raise HTTPException(status_code=503, detail="candles niet beschikbaar")
    return {"coin": coin, "tf": tf, "candles": rows[-limit:]}


@app.get("/api/sparklines")
async def api_sparklines(coins: str = "", user: dict = Depends(require_login)):
    """Minigrafiek van de laatste 24 uur per coin, voor spark.js: één aanroep voor alle kaarten, uit dezelfde candlecache als de grafieken
    (1u-candles), dus nooit een beursaanroep per kaart."""
    active = {c["symbol"] for c in repo.list_coins()}
    wanted = [c for c in dict.fromkeys(x.strip().upper() for x in coins.split(",")) if c in active]
    out = {}
    for coin, rows in zip(wanted, await asyncio.gather(*[_cached_candles(c, "1h") for c in wanted])):
        item = radar.spark([r[4] for r in rows[-radar.SPARK_HOURS:]]) if rows else None
        if item:
            out[coin] = item
    return out
```

- [ ] **Step 5: Template**

`web/templates/smc.html`, in de `radar-head` van de bouwende setups én van de open trades, direct na `<span class="radar-dir ...">...</span>`:

```jinja
        <svg class="radar-spark" data-spark-coin="{{ c.coin }}" viewBox="0 0 120 28" preserveAspectRatio="none" role="img" aria-label="Koers {{ c.coin }}, laatste 24 uur"><path d=""/></svg>
        <span class="radar-spark-chg" data-spark-chg="{{ c.coin }}"></span>
```

Onderaan `smc.html`, na `<script defer src="/static/radar.js"></script>`:

```html
<script defer src="{{ asset('spark.js') }}"></script>
```

- [ ] **Step 6: `web/static/spark.js`**

```js
// Minigrafiek per kaart: de koers van de laatste 24 uur (1u-candles). Eén aanroep voor alle coins op de pagina, elke 5 minuten opnieuw.
// De server rekent het pad uit (radar.spark), hier wordt het alleen ingevuld.
(function () {
  var svgs = document.querySelectorAll("[data-spark-coin]");
  if (!svgs.length) return;
  var coins = {};
  svgs.forEach(function (s) { coins[s.getAttribute("data-spark-coin")] = 1; });

  function apply(data) {
    svgs.forEach(function (svg) {
      var d = data[svg.getAttribute("data-spark-coin")], path = svg.querySelector("path");
      if (!d || !path) return;
      path.setAttribute("d", d.path);
      svg.classList.toggle("is-up", d.change_pct >= 0);
      svg.classList.toggle("is-down", d.change_pct < 0);
    });
    document.querySelectorAll("[data-spark-chg]").forEach(function (el) {
      var d = data[el.getAttribute("data-spark-chg")];
      if (d) el.textContent = d.change_text;
    });
  }

  function load() {
    if (document.hidden) return;
    fetch("/api/sparklines?coins=" + encodeURIComponent(Object.keys(coins).join(",")), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) apply(d); })
      .catch(function () { /* geen minigrafiek is beter dan een foute */ });
  }

  load();
  setInterval(load, 300000);
})();
```

- [ ] **Step 7: CSS**

Onderaan `web/static/style.css`:

```css
/* Minigrafiek van 24 uur in de kop van een radar-kaart (spark.js). */
.radar-spark { width: 72px; height: 22px; margin-left: auto; flex: none; }
.radar-spark path { fill: none; stroke: var(--muted); stroke-width: 1.5; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.radar-spark.is-up path { stroke: var(--green); }
.radar-spark.is-down path { stroke: var(--red); }
.radar-spark-chg { font-family: var(--mono); font-size: var(--text-2xs); color: var(--muted); }
```

- [ ] **Step 8: Draai de tests en de JS-check**

Run: `python3 -m unittest tests.test_radar tests.test_web_extras tests.test_web_radar -v && node --check web/static/spark.js`
Expected: PASS

- [ ] **Step 9: Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_12.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/smc")
    calls = []
    page.on("request", lambda r: calls.append(r.url) if "/api/sparklines" in r.url else None)
    page.reload(); page.wait_for_load_state("networkidle")
    assert len(calls) == 1, calls                                   # één batch voor alle kaarten
    page.wait_for_function("document.querySelector('.radar-spark path').getAttribute('d').startsWith('M')")
    assert page.locator(".radar-spark-chg").first.inner_text().endswith("% 24u")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_12.py $SCRATCH`
Expected: `ok`

- [ ] **Step 10: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/radar.py web/main.py web/templates/smc.html web/static/spark.js web/static/style.css tests/test_radar.py tests/test_web_extras.py
git commit -m "Minigrafiek van 24 uur per Radar-kaart uit de gedeelde candlecache"
```

---

### Task 13: Budgetring op Vandaag (G4)

**Files:**
- Modify: `app/today.py` (import en nieuwe functie)
- Modify: `web/main.py:484-513` (`_vandaag_context`)
- Modify: `web/templates/vandaag.html:18-19` (begin van `.vd-board-side`)
- Modify: `web/static/style.css`
- Test: `tests/test_today.py`, `tests/test_web_vandaag.py`

**Interfaces:**
- Consumes: `push_policy.DEFAULT_BUDGET` (bestaand), `repo.list_recent_pushes` (bestaand), token `--amber` (Task 2).
- Produces: `today.budget_ring(sent: int, budget: Optional[int], default: int = push_policy.DEFAULT_BUDGET) -> dict` met `sent`, `limit`, `off`, `offset` (0 tot 100, voor `stroke-dashoffset`), `full`, `label`; contextveld `budget`.

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_today.py`, nieuwe klasse:

```python
class BudgetRingTest(unittest.TestCase):
    def test_default_budget_is_six(self):
        ring = today.budget_ring(3, None)
        self.assertEqual((ring["limit"], ring["offset"], ring["full"], ring["off"]), (6, 50.0, False, False))
        self.assertEqual(ring["label"], "3 van 6 meldingen in 24 uur")

    def test_full_and_over_budget_stays_a_full_ring(self):
        ring = today.budget_ring(8, 6)
        self.assertEqual((ring["offset"], ring["full"]), (0.0, True))

    def test_zero_switches_the_budget_off(self):
        ring = today.budget_ring(1, 0)
        self.assertTrue(ring["off"])
        self.assertEqual(ring["label"], "1 melding in 24 uur, geen budget")
```

`tests/test_web_vandaag.py`, in `WebVandaagTests`:

```python
    def test_ring_counts_chance_pushes_of_the_last_24_hours(self):
        uid = repo.get_user_by_username("tester")["id"]
        now = datetime.now(timezone.utc)
        repo.record_push(uid, "BTC", "long", now.isoformat())
        repo.record_push(uid, "ETH", "long", (now - timedelta(hours=30)).isoformat())     # buiten het venster
        r = self.client.get("/vandaag")
        self.assertIn("1 van 6 meldingen in 24 uur", r.text)
        self.assertIn('stroke-dashoffset="83.3"', r.text)
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_today tests.test_web_vandaag -v`
Expected: FAIL (`budget_ring` ontbreekt).

- [ ] **Step 3: `today.budget_ring`**

In `app/today.py`, imports: `from app import push_policy` toevoegen naast de andere `from app import ...`-regels. Onderaan:

```python
def budget_ring(sent: int, budget: Optional[int], default: int = push_policy.DEFAULT_BUDGET) -> dict:
    """Pushes voor nieuwe kansen in de laatste 24 uur tegenover het dagbudget. Zelfde venster en zelfde telling als push_policy.decide,
    zodat de ring vol is precies wanneer nieuwe kansen alleen nog op de meldingenpagina komen. budget None = standaard, 0 = geen budget."""
    limit = default if budget is None else budget
    noun = "melding" if sent == 1 else "meldingen"
    if limit <= 0:
        return {"sent": sent, "limit": 0, "off": True, "offset": 100.0, "full": False, "label": f"{sent} {noun} in 24 uur, geen budget"}
    share = min(1.0, sent / limit)
    return {"sent": sent, "limit": limit, "off": False, "offset": round(100 - share * 100, 1), "full": sent >= limit,
            "label": f"{sent} van {limit} meldingen in 24 uur"}
```

- [ ] **Step 4: Context**

`web/main.py`, `_vandaag_context`, in de returned dict:

```python
        "budget": today.budget_ring(len(repo.list_recent_pushes(user["id"], (now - timedelta(hours=24)).isoformat())), user.get("push_budget")),
```

- [ ] **Step 5: Template**

`web/templates/vandaag.html`, direct na `<div class="vd-board-side">`:

```jinja
    <a class="vd-budget{% if budget.full %} is-full{% endif %}" href="/account" title="Dagbudget aanpassen">
      {% if not budget.off %}<svg class="vd-budget-ring" viewBox="0 0 40 40" aria-hidden="true"><circle class="vd-budget-bg" cx="20" cy="20" r="17"/><circle class="vd-budget-fill" cx="20" cy="20" r="17" pathLength="100" stroke-dasharray="100" stroke-dashoffset="{{ budget.offset }}"/></svg>{% endif %}
      <span>{{ budget.label }}</span>
    </a>
```

- [ ] **Step 6: CSS**

Onderaan `web/static/style.css`:

```css
/* Budgetring op Vandaag (today.budget_ring): vol = het dagbudget is op, nieuwe kansen komen dan alleen op de meldingenpagina. */
.vd-budget { display: inline-flex; align-items: center; gap: var(--space-4); color: var(--text-dim); font-size: var(--text-sm); text-decoration: none; }
.vd-budget-ring { width: 30px; height: 30px; flex: none; transform: rotate(-90deg); }
.vd-budget-ring circle { fill: none; stroke-width: 4; }
.vd-budget-bg { stroke: var(--border-strong); }
.vd-budget-fill { stroke: var(--accent); stroke-linecap: round; }
.vd-budget.is-full .vd-budget-fill { stroke: var(--amber); }
```

- [ ] **Step 7: Draai de tests**

Run: `python3 -m unittest tests.test_today tests.test_web_vandaag -v`
Expected: PASS

- [ ] **Step 8: Playwright-controle**

Server volgens de controle-opzet. Zet eerst twee pushes in de scratch DB:

```bash
DATABASE_PATH="$SCRATCH/ui.db" python3 -c "
from datetime import datetime, timezone
from app import repo
uid = repo.get_user_by_username('demo')['id']
for c in ('BTC', 'ETH'): repo.record_push(uid, c, 'long', datetime.now(timezone.utc).isoformat())"
```

`$SCRATCH/check_13.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/vandaag")
    assert page.locator(".vd-budget").inner_text().strip() == "2 van 6 meldingen in 24 uur"
    page.locator(".vd-budget").screenshot(path=sys.argv[1] + "/g4.png")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_13.py $SCRATCH`
Expected: `ok`; `g4.png` toont een ring die voor een derde gevuld is.

- [ ] **Step 9: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/today.py web/main.py web/templates/vandaag.html web/static/style.css tests/test_today.py tests/test_web_vandaag.py
git commit -m "Vandaag: ring met meldingen tegenover het dagbudget"
```

---

### Task 14: Resultaatcurve per soort op Bewijs (G5)

**Files:**
- Modify: `app/track_record.py` (na `live_net_r`)
- Modify: `web/main.py:622-643` (`bewijs_page`)
- Modify: `web/templates/bewijs.html` (nieuwe sectie vóór `{% if not summary %}`)
- Modify: `web/static/style.css`
- Test: `tests/test_track_record.py`, `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `track_record.live_net_r`, `fmt_r`, `TYPE_LABELS` (bestaand), `WebCase` (Task 2).
- Produces:
  - `track_record.equity_curves(rows: list[dict], round_trip_cost_pct: float) -> list[dict]` met per soort `trade_type`, `label`, `n`, `cumulative`, `drawdown`, `max_drawdown`, `total`, `excluded`, `total_text`, `dd_text`
  - `track_record.equity_svg(cumulative: list[float], drawdown: list[float], width: int = 320, height: int = 90) -> str`
  - contextveld `curves` op `/bewijs` (elk met extra `svg`)

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_track_record.py`, nieuwe klasse (gebruikt de bestaande helper `row`):

```python
class EquityTests(unittest.TestCase):
    def rows(self):
        return [
            row(outcome="take_profit", done="2026-09-20T10:00:00+00:00"),            # +2R
            row(outcome="stop_loss", done="2026-09-21T10:00:00+00:00"),              # -1R
            row(outcome="stop_loss", done="2026-09-22T10:00:00+00:00"),              # -1R
            row(outcome="take_profit", done="2026-09-23T10:00:00+00:00"),            # +2R
            row(outcome="vervallen"), row(outcome=None),
            row(trade_type="structuur", outcome="stop_loss"),
        ]

    def test_curve_counts_only_take_and_stop_in_order_of_outcome(self):
        curves = tr.equity_curves(list(reversed(self.rows())), 0.0)
        smc = curves[0]
        self.assertEqual(smc["trade_type"], "smc")
        self.assertEqual(smc["cumulative"], [2.0, 1.0, 0.0, 2.0])
        self.assertEqual(smc["drawdown"], [0.0, -1.0, -2.0, 0.0])
        self.assertEqual(smc["max_drawdown"], -2.0)
        self.assertEqual((smc["n"], smc["excluded"]), (4, 2))
        self.assertEqual(smc["total_text"], "+2,00R")
        self.assertEqual(curves[1]["drawdown"], [-1.0])                         # een eerste verlies is al terugval vanaf 0

    def test_costs_come_off_every_trade(self):
        smc = tr.equity_curves(self.rows()[:1], 0.1)[0]
        self.assertAlmostEqual(smc["cumulative"][0], 2.0 - 0.1 / 1.0)            # stop op 1% afstand: 0,1R kosten

    def test_type_without_resolved_trades_has_no_curve(self):
        self.assertEqual(tr.equity_curves([row(outcome=None)], 0.0), [])

    def test_svg_has_line_and_drawdown_shade(self):
        svg = tr.equity_svg([2.0, 1.0, 0.0, 2.0], [0.0, -1.0, -2.0, 0.0], width=108, height=40)
        self.assertIn('class="equity-dd"', svg)
        self.assertIn('class="equity-line"', svg)
        self.assertEqual(svg.count(",", svg.index('class="equity-line" points="')), 5)       # 0 plus vier trades
        self.assertEqual(tr.equity_svg([], []), "")
```

`tests/test_web_extras.py`:

```python
class BewijsCurveTest(WebCase):
    def test_curve_section_shows_per_type_with_excluded_count(self):
        with db.session() as conn:
            for outcome in ("take_profit", "stop_loss", None):
                conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                                take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                                VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', ?, ?, ?)""",
                             (outcome, db.now_iso() if outcome else None, db.now_iso()))
        r = self.client.get("/bewijs")
        self.assertIn("Resultaatcurve per soort", r.text)
        self.assertIn('class="equity-dd"', r.text)
        self.assertIn("1 open of vervallen, niet meegeteld", r.text)
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_track_record tests.test_web_extras -v`
Expected: FAIL (`equity_curves` ontbreekt).

- [ ] **Step 3: Pure functies in `app/track_record.py`**

Na `live_net_r`:

```python
def equity_curves(rows: list[dict], round_trip_cost_pct: float) -> list[dict]:
    """Per soort de cumulatieve netto R na elke afgeronde trade (take of stop), oudste afronding eerst, met de terugval vanaf de hoogste
    stand tot dan (start is 0, dus een eerste verlies telt als terugval). Open en vervallen tellen niet mee maar staan als aantal ernaast."""
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["trade_type"]].append(r)
    out = []
    for trade_type, items in by_type.items():
        net = live_net_r(items, trade_type, round_trip_cost_pct)
        if not net:
            continue
        cumulative, drawdown, running, peak = [], [], 0.0, 0.0
        for n in net:
            running += n
            peak = max(peak, running)
            cumulative.append(running)
            drawdown.append(running - peak)
        out.append({"trade_type": trade_type, "label": TYPE_LABELS.get(trade_type, trade_type), "n": len(net), "cumulative": cumulative,
                    "drawdown": drawdown, "max_drawdown": min(drawdown), "total": running, "excluded": len(items) - len(net),
                    "total_text": fmt_r(running), "dd_text": fmt_r(min(drawdown))})
    out.sort(key=lambda c: -c["n"])
    return out


def equity_svg(cumulative: list[float], drawdown: list[float], width: int = 320, height: int = 90) -> str:
    """Lijn van de cumulatieve R vanaf 0, met als schaduw het vlak tussen de hoogste stand tot dan en de lijn (de terugval)."""
    if not cumulative:
        return ""
    values = [0.0] + list(cumulative)
    peaks = [0.0] + [c - d for c, d in zip(cumulative, drawdown)]
    lo, hi = min(min(values), 0.0), max(max(peaks), 0.0)
    span = hi - lo or 1.0
    pad = 4
    step = (width - 2 * pad) / max(1, len(values) - 1)

    def pt(i: int, v: float) -> str:
        return f"{pad + i * step:.1f},{pad + (hi - v) / span * (height - 2 * pad):.1f}"

    line = " ".join(pt(i, v) for i, v in enumerate(values))
    shade = " ".join([pt(i, p) for i, p in enumerate(peaks)] + [pt(i, values[i]) for i in range(len(values) - 1, -1, -1)])
    zero = pad + hi / span * (height - 2 * pad)
    trend = "up" if values[-1] >= 0 else "down"
    return (f'<svg class="equity equity-{trend}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
            f'aria-label="Cumulatief resultaat in R per afgeronde trade, met terugval">'
            f'<polygon class="equity-dd" points="{shade}"/>'
            f'<line class="equity-zero" x1="{pad}" x2="{width - pad}" y1="{zero:.1f}" y2="{zero:.1f}"/>'
            f'<polyline class="equity-line" points="{line}"/></svg>')
```

- [ ] **Step 4: Route**

`web/main.py`, `bewijs_page`, vóór `return templates.TemplateResponse(...)`:

```python
    curves = track_record.equity_curves(rows, config.TRACK_RECORD_COST_PCT)
    for c in curves:
        c["svg"] = Markup(track_record.equity_svg(c["cumulative"], c["drawdown"]))
```

en voeg `"curves": curves,` toe aan de context-dict.

- [ ] **Step 5: Template**

`web/templates/bewijs.html`, direct vóór `{% if not summary %}`:

```jinja
{% if curves %}
<section class="card" style="--i: 0">
  <h3>Resultaatcurve per soort</h3>
  <p class="muted">Elke afgeronde trade (doel of stop) schuift de lijn op, in R na kosten. De schaduw is de terugval vanaf de hoogste stand. Open en vervallen signalen tellen niet mee en staan ernaast.</p>
  <div class="equity-grid">
    {% for c in curves %}
    <figure class="equity-card">
      <figcaption><strong>{{ c.label }}</strong><span class="muted">{{ c.n }} afgerond, {{ c.total_text }}, grootste terugval {{ c.dd_text }}. {{ c.excluded }} open of vervallen, niet meegeteld.</span></figcaption>
      {{ c.svg }}
    </figure>
    {% endfor %}
  </div>
</section>
{% endif %}
```

- [ ] **Step 6: CSS**

Onderaan `web/static/style.css`:

```css
/* Resultaatcurve op Bewijs (track_record.equity_svg). De schaduw is de gemeten terugval, geen versiering. */
.equity-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr)); gap: var(--space-7); }
.equity-card { margin: 0; display: flex; flex-direction: column; gap: var(--space-4); }
.equity-card figcaption { display: flex; flex-direction: column; gap: var(--space-2); font-size: var(--text-sm); }
.equity { width: 100%; height: 90px; display: block; }
.equity-line { fill: none; stroke-width: 2; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.equity-up .equity-line { stroke: var(--green); }
.equity-down .equity-line { stroke: var(--red); }
.equity-dd { fill: var(--red-bg); stroke: none; }
.equity-zero { stroke: var(--border-strong); stroke-width: 1; stroke-dasharray: 3 3; vector-effect: non-scaling-stroke; }
```

- [ ] **Step 7: Draai de tests**

Run: `python3 -m unittest tests.test_track_record tests.test_web_extras -v`
Expected: PASS

- [ ] **Step 8: Playwright-controle**

Server volgens de controle-opzet (40 seed-signalen met take, stop, open en vervallen). `$SCRATCH/check_14.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/bewijs")
    cards = page.locator(".equity-card")
    assert cards.count() == 2
    for i in range(2):
        assert "12 afgerond" in cards.nth(i).inner_text() and "8 open of vervallen" in cards.nth(i).inner_text()   # seed: per soort 12 afgerond, 8 niet
    page.locator(".equity-grid").screenshot(path=sys.argv[1] + "/g5.png")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_14.py $SCRATCH`
Expected: `ok`; `g5.png` toont per soort een lijn met rode schaduw onder de hoogste stand.

- [ ] **Step 9: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/track_record.py web/main.py web/templates/bewijs.html web/static/style.css tests/test_track_record.py tests/test_web_extras.py
git commit -m "Bewijs: resultaatcurve per soort met terugval, alleen doel en stop tellen"
```

---

### Task 15: Uurkaart op Bewijs (G6)

**Files:**
- Modify: `app/track_record.py` (import `ZoneInfo`, nieuwe functies na `equity_svg`)
- Modify: `web/main.py` (`bewijs_page`)
- Modify: `web/templates/bewijs.html` (na de resultaatcurve-sectie)
- Modify: `web/static/style.css`
- Test: `tests/test_track_record.py`, `tests/test_web_extras.py`

**Interfaces:**
- Consumes: `track_record.net_signal_r`, `fmt_r`, `_parse` (bestaand), `BewijsCurveTest`-stijl uit Task 14, `WebCase` (Task 2).
- Produces:
  - `track_record.HOUR_GRID_MIN_N = 5`, `track_record.WEEKDAYS_SHORT`
  - `track_record.hour_grid(rows: list[dict], round_trip_cost_pct: float, tz=None, min_n: int = HOUR_GRID_MIN_N) -> dict` met `rows` (7 x `{"day", "cells": 24 x {"hour", "n", "avg", "weak", "heat", "avg_short", "title"}}`), `min_n`, `total`
  - contextveld `hours` op `/bewijs`

- [ ] **Step 1: Schrijf de falende tests**

`tests/test_track_record.py`:

```python
class HourGridTests(unittest.TestCase):
    def test_cells_by_local_weekday_and_hour_with_weak_cells(self):
        monday_14 = "2026-10-05T12:10:00+00:00"                                  # maandag 14:10 in Amsterdam (zomertijd)
        tuesday_9 = "2026-10-06T07:00:00+00:00"
        rows = [row(outcome="take_profit", created=monday_14)] * 4 + [row(outcome="stop_loss", created=monday_14)] \
            + [row(outcome="stop_loss", created=tuesday_9)] * 2 + [row(outcome=None, created=tuesday_9)]
        grid = tr.hour_grid(rows, 0.0)
        mon = grid["rows"][0]["cells"][14]
        self.assertEqual((grid["rows"][0]["day"], mon["n"], mon["weak"]), ("ma", 5, False))
        self.assertAlmostEqual(mon["avg"], (4 * 2.0 - 1.0) / 5)
        self.assertEqual(mon["heat"], "pos2")
        self.assertEqual(mon["avg_short"], "+1,4")
        tue = grid["rows"][1]["cells"][9]
        self.assertEqual((tue["n"], tue["weak"], tue["heat"]), (2, True, "zwak"))     # open signaal telt niet, te weinig voor kleur
        self.assertIn("2 trades", tue["title"])
        self.assertEqual(grid["total"], 7)
        self.assertEqual(grid["rows"][2]["cells"][0]["n"], 0)

    def test_heat_levels(self):
        self.assertEqual([tr._heat(v) for v in (0.6, 0.1, 0.0, -0.1, -0.7)], ["pos2", "pos1", "nul", "neg1", "neg2"])
```

`tests/test_web_extras.py`:

```python
class BewijsHourGridTest(WebCase):
    def test_hour_grid_section(self):
        with db.session() as conn:
            conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, technical_confirmed, price, stop_loss,
                            take_profit, trade_type, auto_outcome, auto_outcome_at, created_at)
                            VALUES (NULL, 'BTC', 'long', 'x', 'hoog', 1, 100, 99, 102, 'smc', 'take_profit', ?, ?)""", (db.now_iso(), db.now_iso()))
        r = self.client.get("/bewijs")
        self.assertIn("Uurkaart", r.text)
        self.assertIn('class="hourmap"', r.text)
        self.assertIn("is-weak", r.text)                                       # één trade is te weinig voor kleur
```

- [ ] **Step 2: Draai de tests en zie ze falen**

Run: `python3 -m unittest tests.test_track_record tests.test_web_extras -v`
Expected: FAIL (`hour_grid` ontbreekt).

- [ ] **Step 3: Pure functies**

In `app/track_record.py`, imports: `from zoneinfo import ZoneInfo`. Na `equity_svg`:

```python
HOUR_GRID_MIN_N = 5
WEEKDAYS_SHORT = ("ma", "di", "wo", "do", "vr", "za", "zo")


def _heat(avg: float) -> str:
    if avg >= 0.5:
        return "pos2"
    if avg > 0:
        return "pos1"
    if avg <= -0.5:
        return "neg2"
    return "neg1" if avg < 0 else "nul"


def hour_grid(rows: list[dict], round_trip_cost_pct: float, tz=None, min_n: int = HOUR_GRID_MIN_N) -> dict:
    """Gemiddelde netto R per weekdag en uur van de melding (Nederlandse tijd), alleen afgeronde trades (take of stop). Een vak met minder
    dan min_n trades krijgt geen kleur: een paar trades per uur zeggen niets, en een fel vak zou dat wel suggereren."""
    tz = tz or ZoneInfo("Europe/Amsterdam")
    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    for r in rows:
        net = net_signal_r(r, round_trip_cost_pct)
        if net is None:
            continue
        at = _parse(r["created_at"]).astimezone(tz)
        cells[(at.weekday(), at.hour)].append(net)
    out_rows = []
    for d, day in enumerate(WEEKDAYS_SHORT):
        row_cells = []
        for h in range(24):
            vals = cells.get((d, h), [])
            avg = sum(vals) / len(vals) if vals else None
            weak = len(vals) < min_n
            title = f"{day} {h:02d}:00, {len(vals)} {'trade' if len(vals) == 1 else 'trades'}" + (f", gemiddeld {fmt_r(avg)}" if avg is not None else "")
            row_cells.append({"hour": h, "n": len(vals), "avg": avg, "weak": weak,
                              "heat": "zwak" if weak or avg is None else _heat(avg),
                              "avg_short": f"{avg:+.1f}".replace(".", ",") if avg is not None else "", "title": title})
        out_rows.append({"day": day, "cells": row_cells})
    return {"rows": out_rows, "min_n": min_n, "total": sum(len(v) for v in cells.values())}
```

- [ ] **Step 4: Route**

`web/main.py`, `bewijs_page`, na het `curves`-blok: voeg `"hours": track_record.hour_grid(rows, config.TRACK_RECORD_COST_PCT),` toe aan de context-dict.

- [ ] **Step 5: Template**

`web/templates/bewijs.html`, direct na de `{% endif %}` van de resultaatcurve-sectie:

```jinja
{% if hours.total %}
<section class="card" style="--i: 1">
  <h3>Uurkaart</h3>
  <p class="muted">Gemiddelde R na kosten per weekdag en uur van de melding, Nederlandse tijd. Het kleine getal is het aantal afgeronde trades. Onder {{ hours.min_n }} trades blijft een vak grijs: te weinig om iets te zeggen.</p>
  <div class="hourmap-wrap">
    <table class="hourmap">
      <thead><tr><th></th>{% for h in range(24) %}<th scope="col">{{ "%02d"|format(h) }}</th>{% endfor %}</tr></thead>
      <tbody>
        {% for r in hours.rows %}
        <tr><th scope="row">{{ r.day }}</th>{% for c in r.cells %}<td class="hm hm-{{ c.heat }}{% if c.weak %} is-weak{% endif %}" title="{{ c.title }}">{% if c.n %}{% if not c.weak %}<span class="hm-avg">{{ c.avg_short }}</span>{% endif %}<span class="hm-n">{{ c.n }}</span>{% endif %}</td>{% endfor %}</tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endif %}
```

- [ ] **Step 6: CSS**

Onderaan `web/static/style.css`:

```css
/* Uurkaart op Bewijs (track_record.hour_grid). Scrolt binnen zijn kader, nooit de pagina. Kleur alleen vanaf het minimum aantal trades. */
.hourmap-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.hourmap { border-collapse: separate; border-spacing: 2px; font-family: var(--mono); font-size: var(--text-2xs); }
.hourmap th { color: var(--muted); font-weight: 500; padding: 0 2px; }
.hm { width: 30px; height: 30px; padding: 0; text-align: center; vertical-align: middle; border-radius: var(--radius-sm); background: var(--panel); color: var(--text-dim); line-height: 1.1; }
.hm span { display: block; }
.hm-n { color: var(--muted); font-size: 9px; }
.hm-pos1 { background: rgba(51, 214, 159, 0.18); }
.hm-pos2 { background: rgba(51, 214, 159, 0.38); color: var(--text); }
.hm-neg1 { background: rgba(242, 104, 92, 0.18); }
.hm-neg2 { background: rgba(242, 104, 92, 0.38); color: var(--text); }
.hm.is-weak { background: var(--panel); opacity: 0.6; }
```

- [ ] **Step 7: Draai de tests**

Run: `python3 -m unittest tests.test_track_record tests.test_web_extras -v`
Expected: PASS

- [ ] **Step 8: Playwright-controle**

Server volgens de controle-opzet. `$SCRATCH/check_15.py`:

```python
import sys; sys.path.insert(0, sys.argv[1])
from playwright.sync_api import sync_playwright
from ui_login import open_page

with sync_playwright() as pw:
    browser, ctx, page = open_page(pw, "/bewijs")
    assert page.locator(".hourmap tbody tr").count() == 7
    assert page.locator(".hourmap tbody tr").first.locator("td").count() == 24
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "de kaart scrolt binnen zijn kader"
    page.locator(".hourmap-wrap").screenshot(path=sys.argv[1] + "/g6.png")
    print("ok")
    browser.close()
```

Run: `python3 $SCRATCH/check_15.py $SCRATCH`
Expected: `ok`

- [ ] **Step 9: Volledige suite en commit**

```bash
SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .
git add app/track_record.py web/main.py web/templates/bewijs.html web/static/style.css tests/test_track_record.py tests/test_web_extras.py
git commit -m "Bewijs: uurkaart met gemiddelde R per uur en weekdag"
```

---

## Overzicht: volgorde en gedeelde bestanden

| # | Taak | Functie | Hoofdbestanden |
|---|---|---|---|
| 1 | Pauze, opslag en verzendpad | F3 | schema.sql, db.py, repo.py, push_policy.py, push_notify.py |
| 2 | Pauzeknop | F3 | web/main.py, base.html, pause.js, style.css, test_web_extras.py (nieuw) |
| 3 | Prijsalarm, opslag en controle | F4 | price_alerts.py (nieuw), schema.sql, repo.py, level_check.py, notifications_view.py |
| 4 | Kopieer met een tik | F5 | chance_steps.py, radar.py, today.py, _macros.html, smc.html, vandaag.html, base.html, copy.js, style.css |
| 5 | Prijsalarm vanaf een kaart | F4 | web/main.py, _macros.html, base.html, alarm.js, style.css |
| 6 | Appicoon-badge | F6 | radar.py, repo.py, push_notify.py, market_scanner.py, web/main.py, base.html, service-worker.js |
| 7 | Versheidsstip | F7 | freshness.py (nieuw), web/main.py, base.html, stale.js, radar.js, vandaag.js, style.css |
| 8 | Meldingenbanner | F8 | push-subscribe.js, push-banner.js, base.html, account.html, style.css |
| 9 | Trekken en tab naar boven | F1, F2 | smooth.js, radar.js, vandaag.js, tabbar.js, base.html |
| 10 | Risico- en beloningsvlak | G1 | levelchart.js, tests/test_static_js.py |
| 11 | Afstandsbalk | G2 | trade_plan.py, radar.py, smc.html, radar.js, style.css |
| 12 | Minigrafiek | G3 | radar.py, web/main.py, smc.html, spark.js, style.css |
| 13 | Budgetring | G4 | today.py, web/main.py, vandaag.html, style.css |
| 14 | Resultaatcurve | G5 | track_record.py, web/main.py, bewijs.html, style.css |
| 15 | Uurkaart | G6 | track_record.py, web/main.py, bewijs.html, style.css |

**Volgorde:** 1 tot en met 15 in deze volgorde. Afhankelijkheden die de volgorde vastleggen: 1 voor 2 (pauzefuncties), 2 voor alle taken die `WebCase` of `--amber` gebruiken (5, 6, 7, 12, 13, 14, 15), 3 voor 5 (repo-functies), 4 voor 5 (macro en `hesToast`), 7 voor 9 (`refresh(force)` als Promise) en voor 10 (`tests/test_static_js.py`), 14 voor 15 (zelfde sectie in `bewijs.html`).

**Niet parallel draaien (gedeelde bestanden):**
- `web/main.py`: 2, 5, 6, 7, 12, 13, 14, 15
- `web/templates/base.html`: 2, 4, 5, 6, 7, 8, 9
- `web/static/style.css`: 2, 4, 5, 7, 8, 11, 12, 13, 14, 15
- `tests/test_web_extras.py`: 2, 5, 6, 7, 8, 12, 14, 15
- `app/radar.py`: 4, 6, 11, 12; `app/repo.py`: 1, 3, 6; `app/push_notify.py`: 1, 6; `app/schema.sql`: 1, 3
- `web/static/radar.js`: 7, 9, 11; `web/static/vandaag.js`: 7, 9
- `web/templates/smc.html`: 4, 11, 12; `web/templates/_macros.html`: 4, 5; `web/templates/bewijs.html`: 14, 15
- `app/track_record.py`: 14, 15; `app/today.py`: 4, 13

**Wel parallel mogelijk:** Taak 10 (alleen `levelchart.js` en een eigen testklasse) kan naast elke andere taak lopen zodra Taak 7 `tests/test_static_js.py` heeft aangemaakt; Taak 3 kan naast Taak 2 lopen (geen gedeelde bestanden).

## Self-review

- Spec-dekking: F1 en F2 in Taak 9, F3 in 1 en 2, F4 in 3 en 5, F5 in 4, F6 in 6, F7 in 7, F8 in 8, G1 in 10, G2 in 11, G3 in 12, G4 in 13, G5 in 14, G6 in 15. "Telegram" uit F3 bestaat niet meer als kanaal; de pauze zit in het enige verzendpad (`push_notify`).
- Namen gecontroleerd tussen taken: `pause_minutes_left`, `pause_text`, `set_push_pause`, `level_chips`, `hesToast`, `refresh(force)`, `hesRefresh`, `hesPriceSeen`, `run_node`, `approach_pct`, `in_zone_count`, `count_zone_alerted_setups`, `equity_curves`, `equity_svg`, `hour_grid`, `_heat`.
- Eerlijkheid: curve en uurkaart gebruiken `live_net_r`/`net_signal_r` (alleen take/stop), open en vervallen staan als aantal; het appicoon telt geen setup zonder koers; de versheidsstip gebruikt de echte ophaaltijd, niet de cachetijd.
