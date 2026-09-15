# Push-meldingen via de HesPulse-app Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telegram vervangen door echte pushmeldingen vanuit de HesPulse-app zelf (Web Push, eigen VAPID-sleutels), met een scherp onderscheid tussen tijdkritische pushmeldingen en een rustige in-app meldingenlijst voor de rest.

**Architecture:** Twee nieuwe tabellen (`push_subscriptions`, `notifications`). Nieuwe module `app/push_notify.py` (Web Push via `pywebpush`) vervangt `app/telegram_notify.py` op de zeven tijdkritische call sites; de overige zes call sites schrijven voortaan naar `notifications` in plaats van te verzenden. Nieuwe pagina `/meldingen` toont die rustige lijst. Telegram wordt pas in de laatste taak volledig verwijderd, nadat de nieuwe weg bevestigd werkt.

**Tech Stack:** Python (FastAPI, sqlite3), `pywebpush` (nieuw), vanilla JS + service worker (bestaande PWA-schil).

**Spec:** `docs/superpowers/specs/2026-09-15-push-meldingen-design.md`

## Global Constraints

- Geen pytest-suite in dit project (zie CLAUDE.md). Verificatie via scratch-scripts tegen `DATABASE_PATH=/tmp/scratch.db`.
- Database-toegang centraal via `app/repo.py`, nooit losse SQL elders (CLAUDE.md).
- Schema-wijzigingen: een nieuwe tabel volstaat met `CREATE TABLE IF NOT EXISTS` in `app/schema.sql` (dat script draait via `executescript()` bij elke `init_db()`-aanroep, ook op een bestaande database — zie `app/db.py:36-39`). Alleen een NIEUWE KOLOM op een tabel die al bestaat heeft ook een idempotente `ALTER TABLE` in `app/db.py:_migrate()` nodig (`PRAGMA table_info`-check eerst). Dit plan voegt alleen nieuwe tabellen toe, geen kolommen op bestaande tabellen — dus geen `_migrate()`-wijziging nodig.
- Elke fan-out naar meerdere gebruikers/apparaten blijft per-item in zijn eigen `try/except`: één mislukte melding blokkeert nooit de rest (bestaand patroon, zie `telegram_notify.send_signal`-aanroepers).
- De gebruiker werkt via SSH op een VPS (Windows/PowerShell client) en wil op elk verificatiemoment het exacte shell-commando, nooit "test dit zelf maar".
- Telegram blijft volledig functioneren tot en met Taak 10; Taak 11 is de enige plek waar het verwijderd wordt.

---

### Task 1: Schema + repo.py CRUD voor meldingen

**Files:**
- Modify: `app/schema.sql`
- Modify: `app/repo.py`

**Interfaces:**
- Produces: `repo.upsert_push_subscription(user_id: int, endpoint: str, p256dh: str, auth: str, device_label: Optional[str]) -> None`, `repo.list_push_subscriptions(user_id: int) -> list[dict]`, `repo.delete_push_subscription(endpoint: str) -> None`, `repo.create_notification(user_id: Optional[int], type: str, title: str, body: str, url: Optional[str] = None) -> int`, `repo.list_notifications(user_id: int, limit: int = 50) -> list[dict]`, `repo.list_admin_notifications(limit: int = 50) -> list[dict]`, `repo.count_unread_notifications(user_id: int) -> int`, `repo.mark_notification_read(notification_id: int, user_id: int) -> None`

- [ ] **Step 1: Tabellen toevoegen aan `app/schema.sql`**

Ergens na de bestaande `journal_entries`-tabel invoegen (buurt van andere per-gebruiker tabellen):

```sql
-- Eén rij per (browser × apparaat)-abonnement op Web Push. Eén gebruiker
-- kan meerdere rijen hebben (telefoon + PC). endpoint is uniek: een nieuw
-- abonnement van hetzelfde apparaat overschrijft de bestaande rij i.p.v.
-- een duplicaat aan te maken.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    device_label TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (endpoint)
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id);

-- Rustige, niet-tijdkritische meldingen die NIET pushen: vervallen
-- pending signalen, lange-termijn-verhaal-updates, weekoverzichten,
-- systeemgezondheid. user_id is NULL voor admin-only rijen
-- (systeemgezondheid, herhaalde API-fouten) — zie
-- docs/superpowers/specs/2026-09-15-push-meldingen-design.md.
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
```

- [ ] **Step 2: CRUD-functies toevoegen aan `app/repo.py`**

Ergens bij de andere per-gebruiker CRUD-functies (buurt van `upsert_narrative_notification`, die als stijlvoorbeeld dient):

```python
def upsert_push_subscription(
    user_id: int, endpoint: str, p256dh: str, auth: str, device_label: Optional[str] = None,
) -> None:
    """Slaat een Web Push-abonnement op. endpoint is uniek: hetzelfde
    apparaat dat opnieuw abonneert (bijvoorbeeld na het wissen van
    browserdata) overschrijft de bestaande rij i.p.v. een duplicaat aan
    te maken."""
    with db.session() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, device_label, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET
                   user_id = excluded.user_id,
                   p256dh = excluded.p256dh,
                   auth = excluded.auth,
                   device_label = excluded.device_label""",
            (user_id, endpoint, p256dh, auth, device_label, db.now_iso()),
        )


def list_push_subscriptions(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_push_subscription(endpoint: str) -> None:
    """Aangeroepen zodra pywebpush een 404/410 teruggeeft: de browser/OS
    kent dit abonnement niet meer, verder blijven proberen vervuilt de
    tabel alleen maar."""
    with db.session() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def create_notification(
    user_id: Optional[int], type: str, title: str, body: str, url: Optional[str] = None,
) -> int:
    """Rustige melding, geen push. user_id=None is een admin-only rij
    (systeemgezondheid, herhaalde API-fouten), alleen zichtbaar op de
    admin-pagina/sectie, nooit op de gewone /meldingen-lijst van een
    normale gebruiker."""
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO notifications (user_id, type, title, body, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, type, title, body, url, db.now_iso()),
        )
        return cur.lastrowid


def list_notifications(user_id: int, limit: int = 50) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_admin_notifications(limit: int = 50) -> list[dict]:
    """Systeemgezondheid en herhaalde-API-fouten: user_id IS NULL, alleen
    voor de admin-pagina, nooit gemengd met een normale gebruiker se
    eigen lijst."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id IS NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_unread_notifications(user_id: int) -> int:
    with db.session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
        return row["n"]


def mark_notification_read(notification_id: int, user_id: int) -> None:
    """user_id in de WHERE, niet alleen notification_id: een gebruiker
    mag nooit andermans meldingsrij als gelezen markeren via een geraden
    ID (zelfde ownership-check-patroon als update_journal_status)."""
    with db.session() as conn:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )
```

`Optional` is al geïmporteerd bovenaan `repo.py` (gebruikt door bestaande functies) — geen nieuwe import nodig.

- [ ] **Step 3: Scratch-test**

```bash
cd /home/user/Trade
DATABASE_PATH=/tmp/scratch_push.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser_push', 'wachtwoord123')['id'] if hasattr(repo, 'create_user') else None
"
```

Als `repo.create_user` niet exact zo heet (check eerst met `grep -n 'def create_user' app/repo.py`), gebruik de bestaande gebruikersaanmaakfunctie of maak handmatig een rij aan via `db.session()`. Vervolgens:

```bash
DATABASE_PATH=/tmp/scratch_push.db python3 -c "
from app import db, repo
db.init_db()
with db.session() as conn:
    conn.execute(
        \"INSERT INTO users (username, password_hash, created_at) VALUES ('t', 'x', ?)\",
        (db.now_iso(),),
    )
    uid = conn.execute('SELECT id FROM users WHERE username = ?', ('t',)).fetchone()['id']

repo.upsert_push_subscription(uid, 'https://fcm.googleapis.com/test1', 'p256dh-key', 'auth-key', 'iPhone')
subs = repo.list_push_subscriptions(uid)
assert len(subs) == 1 and subs[0]['endpoint'] == 'https://fcm.googleapis.com/test1', subs

repo.upsert_push_subscription(uid, 'https://fcm.googleapis.com/test1', 'nieuwe-key', 'auth-key', 'iPhone')
subs = repo.list_push_subscriptions(uid)
assert len(subs) == 1 and subs[0]['p256dh'] == 'nieuwe-key', 'upsert moet overschrijven, niet dupliceren'

repo.delete_push_subscription('https://fcm.googleapis.com/test1')
assert repo.list_push_subscriptions(uid) == []

nid = repo.create_notification(uid, 'test', 'Titel', 'Body', '/coins/BTC')
assert repo.count_unread_notifications(uid) == 1
repo.mark_notification_read(nid, uid)
assert repo.count_unread_notifications(uid) == 0

admin_id = repo.create_notification(None, 'system_health', 'Zelfcheck', 'probleem', None)
assert len(repo.list_admin_notifications()) == 1
assert repo.list_notifications(uid) != [] and all(n['user_id'] == uid for n in repo.list_notifications(uid))
print('OK: push_subscriptions en notifications CRUD werkt')
"
```

Expected: `OK: push_subscriptions en notifications CRUD werkt`, geen AssertionError.

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add app/schema.sql app/repo.py
git commit -m "Schema en repo-CRUD voor push-abonnementen en rustige meldingen"
```

---

### Task 2: VAPID-sleutels + configuratie

**Files:**
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `config.VAPID_PUBLIC_KEY: str`, `config.VAPID_PRIVATE_KEY: str`, `config.VAPID_CLAIM_EMAIL: str`, `config.ADMIN_USERNAME: str`

- [ ] **Step 1: `pywebpush` toevoegen aan `requirements.txt`**

```
pywebpush>=2.0
```

- [ ] **Step 2: VAPID-sleutelpaar genereren (lokaal, éénmalig)**

```bash
cd /home/user/Trade
pip install pywebpush  # als nog niet lokaal geïnstalleerd
python3 -c "
from py_vapid import Vapid02
v = Vapid02()
v.generate_keys()
print('VAPID_PUBLIC_KEY=' + v.public_key_str())
print('VAPID_PRIVATE_KEY=' + v.private_key_str())
"
```

`py_vapid` is een dependency van `pywebpush`, geen aparte install nodig. Dit commando draait één keer (lokaal of op de VPS), de output gaat in `.env` — nooit in git.

- [ ] **Step 3: `app/config.py` uitbreiden**

Toevoegen na `ADMIN_TELEGRAM_CHAT_ID` (blijft nog even staan, verdwijnt pas in Taak 11):

```python
# Web Push: eigen VAPID-sleutelpaar, één keer gegenereerd (zie het plan
# voor het genereercommando), bewijst aan Apple/Google dat een melding
# echt van HesPulse komt. VAPID_CLAIM_EMAIL is het contactadres dat de
# pushdienst mag gebruiken bij misbruik-signalen, vereist door de Web
# Push-standaard (RFC 8292).
VAPID_PUBLIC_KEY = _get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = _get("VAPID_PRIVATE_KEY")
VAPID_CLAIM_EMAIL = _get("VAPID_CLAIM_EMAIL", "mailto:admin@hespulse.duckdns.org")

# Gebruikersnaam van het admin-account (jijzelf): bepaalt wie de
# systeemgezondheid-sectie op /meldingen mag zien. Vervangt de oude
# ADMIN_TELEGRAM_CHAT_ID-vergelijking zodra Telegram weg is (Taak 8/11).
ADMIN_USERNAME = _get("ADMIN_USERNAME")
```

- [ ] **Step 4: `.env.example` uitbreiden**

Toevoegen na de `ADMIN_TELEGRAM_CHAT_ID`-sectie:

```
# Web Push VAPID-sleutelpaar, genereer met (zie implementatieplan push-
# meldingen voor het volledige commando):
#   python3 -c "from py_vapid import Vapid02; v = Vapid02(); v.generate_keys(); print(v.public_key_str()); print(v.private_key_str())"
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_CLAIM_EMAIL=mailto:admin@hespulse.duckdns.org

# Gebruikersnaam van jouw eigen admin-account, bepaalt wie de
# systeemgezondheid-sectie op /meldingen ziet.
ADMIN_USERNAME=
```

- [ ] **Step 5: Verifiëren dat config laadt zonder crash**

```bash
cd /home/user/Trade
python3 -c "from app import config; print(config.VAPID_PUBLIC_KEY, config.ADMIN_USERNAME)"
```

Expected: twee lege strings (leeg `.env` lokaal is prima, geen crash), geen `ImportError`/`AttributeError`.

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add app/config.py .env.example requirements.txt
git commit -m "VAPID-configuratie en ADMIN_USERNAME toevoegen"
```

---

### Task 3: Abonneerflow (subscribe-knop + route)

**Files:**
- Modify: `web/main.py`
- Modify: `web/templates/base.html` (of `dashboard.html`, zie Step 2)
- Create: `web/static/push-subscribe.js`

**Interfaces:**
- Consumes: `repo.upsert_push_subscription` (Task 1), `config.VAPID_PUBLIC_KEY` (Task 2)
- Produces: route `GET /api/push/vapid-public-key`, route `POST /api/push/subscribe`

- [ ] **Step 1: Routes toevoegen aan `web/main.py`**

Bij de andere `/api/`-routes invoegen (buurt van `api_system_status`):

```python
@app.get("/api/push/vapid-public-key")
async def api_push_vapid_public_key(user: dict = Depends(require_login)):
    return {"key": config.VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request, user: dict = Depends(require_login)):
    """Slaat een Web Push-abonnement op vanaf de browser. Het
    subscription-object van de browser heeft altijd deze vorm:
    {endpoint, keys: {p256dh, auth}}."""
    data = await request.json()
    endpoint = data.get("endpoint")
    keys = data.get("keys", {})
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return JSONResponse({"error": "ongeldig abonnement"}, status_code=400)
    repo.upsert_push_subscription(
        user["id"], endpoint, keys["p256dh"], keys["auth"], data.get("device_label"),
    )
    return {"ok": True}
```

Check bovenaan `web/main.py` of `JSONResponse` al geïmporteerd is (`grep -n "JSONResponse" web/main.py`); zo niet, toevoegen aan de bestaande `from fastapi.responses import ...`-regel.

- [ ] **Step 2: Knop op het dashboard**

Zoek de plek in `web/templates/dashboard.html` waar de instellingen-sectie staat (buurt van de stille-uren-instelling, `grep -n "quiet_hours" web/templates/dashboard.html`) en voeg ernaast toe:

```html
<div id="push-subscribe-block">
  <button id="push-subscribe-btn" type="button" class="btn-secondary">Meldingen aanzetten</button>
  <p id="push-subscribe-status" class="hint" hidden></p>
</div>
<script src="/static/push-subscribe.js" defer></script>
```

- [ ] **Step 3: `web/static/push-subscribe.js` schrijven**

```javascript
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

  async function subscribe() {
    const statusEl = document.getElementById("push-subscribe-status");
    const showStatus = function (text) {
      statusEl.hidden = false;
      statusEl.textContent = text;
    };

    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      showStatus("Pushmeldingen vereisen een geïnstalleerde app (voeg toe aan beginscherm).");
      return;
    }

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      showStatus("Toestemming niet gegeven, geen pushmeldingen mogelijk.");
      return;
    }

    try {
      const reg = await navigator.serviceWorker.ready;
      const keyResp = await fetch("/api/push/vapid-public-key");
      const { key } = await keyResp.json();
      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign(subscription.toJSON(), { device_label: navigator.userAgent.slice(0, 60) })),
      });
      showStatus("Meldingen staan aan op dit apparaat.");
    } catch (err) {
      showStatus("Kon meldingen niet aanzetten: " + err.message);
    }
  }

  const btn = document.getElementById("push-subscribe-btn");
  if (btn) btn.addEventListener("click", subscribe);
})();
```

- [ ] **Step 4: Handmatige verificatie (server draaien, browser testen)**

```bash
cd /home/user/Trade
source .venv/bin/activate
DATABASE_PATH=/tmp/scratch_push.db uvicorn web.main:app --reload
```

Open `http://127.0.0.1:8000/dashboard` in een browser, log in met een testaccount, klik "Meldingen aanzetten". Zonder geldige VAPID-sleutel in `.env` faalt `pushManager.subscribe` met een duidelijke foutmelding in `push-subscribe-status` — dat is verwacht als `.env` nog leeg is; met een echt sleutelpaar (Task 2) moet de knop tekst "Meldingen staan aan op dit apparaat." tonen en moet er een rij in `push_subscriptions` staan:

```bash
sqlite3 /tmp/scratch_push.db "SELECT id, user_id, device_label FROM push_subscriptions;"
```

- [ ] **Step 5: Commit**

```bash
cd /home/user/Trade
git add web/main.py web/templates/dashboard.html web/static/push-subscribe.js
git commit -m "Abonneerflow voor Web Push: knop, route, opslag"
```

---

### Task 4: `app/push_notify.py` (verzendlogica)

**Files:**
- Create: `app/push_notify.py`

**Interfaces:**
- Consumes: `repo.list_push_subscriptions`, `repo.delete_push_subscription` (Task 1), `config.VAPID_PRIVATE_KEY`, `config.VAPID_CLAIM_EMAIL` (Task 2)
- Produces: `async def send_push(user_id: int, title: str, body: str, url: str, silent: bool = False) -> None`

- [ ] **Step 1: Module schrijven**

```python
"""Web Push-meldingen naar de HesPulse-app, vervangt telegram_notify.py.
Eigen VAPID-sleutelpaar (app/config.py), geen externe pushdienst: het
abonnement zelf loopt via Apple/Google's eigen infrastructuur (dat is
hoe Web Push werkt), maar wij bouwen en versturen de payload zelf."""
import asyncio
import json
import logging

from pywebpush import WebPushException, webpush

from app import config, repo

logger = logging.getLogger("push_notify")


def _send_one(subscription: dict, payload: dict) -> None:
    webpush(
        subscription_info={
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        },
        data=json.dumps(payload),
        vapid_private_key=config.VAPID_PRIVATE_KEY,
        vapid_claims={"sub": config.VAPID_CLAIM_EMAIL},
    )


async def send_push(user_id: int, title: str, body: str, url: str, silent: bool = False) -> None:
    """Stuurt naar elk geregistreerd apparaat van deze gebruiker. Een
    apparaat dat de browser/OS niet meer kent (404/410 terug) wordt
    meteen verwijderd, anders blijft push_subscriptions vervuild raken
    met dode abonnementen. Eén mislukt apparaat blokkeert de andere
    apparaten van dezelfde gebruiker niet (zelfde patroon als
    telegram_notify.send_signal nu al per gebruiker in zijn eigen
    try/except draait)."""
    if not config.VAPID_PRIVATE_KEY:
        logger.warning("VAPID_PRIVATE_KEY ontbreekt, pushmelding niet verstuurd")
        return

    subscriptions = repo.list_push_subscriptions(user_id)
    if not subscriptions:
        return

    payload = {"title": title, "body": body, "url": url, "icon": "/static/icon-192.png", "silent": silent}
    for sub in subscriptions:
        try:
            await asyncio.to_thread(_send_one, sub, payload)
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                repo.delete_push_subscription(sub["endpoint"])
                logger.info("Dood push-abonnement verwijderd (status %s): %s", status, sub["endpoint"])
            else:
                logger.exception("Pushmelding naar abonnement %s mislukt (status %s)", sub["id"], status)
        except Exception:
            logger.exception("Pushmelding naar abonnement %s mislukt", sub["id"])
```

- [ ] **Step 2: Scratch-test met gemockte `webpush`**

```bash
cd /home/user/Trade
DATABASE_PATH=/tmp/scratch_push2.db python3 -c "
from unittest.mock import patch
from pywebpush import WebPushException
from app import config, db, repo, push_notify
import asyncio, json

db.init_db()
config.VAPID_PRIVATE_KEY = 'dummy-key'
config.VAPID_CLAIM_EMAIL = 'mailto:test@example.com'

with db.session() as conn:
    conn.execute(\"INSERT INTO users (username, password_hash, created_at) VALUES ('t2', 'x', ?)\", (db.now_iso(),))
    uid = conn.execute('SELECT id FROM users WHERE username = ?', ('t2',)).fetchone()['id']

repo.upsert_push_subscription(uid, 'https://example.com/ep1', 'p1', 'a1')
repo.upsert_push_subscription(uid, 'https://example.com/ep2', 'p2', 'a2')

captured = []
def fake_webpush(subscription_info, data, vapid_private_key, vapid_claims):
    captured.append(json.loads(data))
    if subscription_info['endpoint'].endswith('ep2'):
        raise WebPushException('gone', response=type('R', (), {'status_code': 410})())

with patch('app.push_notify.webpush', fake_webpush):
    asyncio.run(push_notify.send_push(uid, 'Titel', 'Body', '/coins/ETH'))

assert len(captured) == 2, captured
assert captured[0]['title'] == 'Titel' and captured[0]['url'] == '/coins/ETH'
remaining = repo.list_push_subscriptions(uid)
assert len(remaining) == 1 and remaining[0]['endpoint'].endswith('ep1'), remaining
print('OK: send_push verstuurt naar alle apparaten en ruimt 410 op')
"
```

Expected: `OK: send_push verstuurt naar alle apparaten en ruimt 410 op`.

- [ ] **Step 3: Commit**

```bash
cd /home/user/Trade
git add app/push_notify.py
git commit -m "app/push_notify.py: Web Push-verzendlogica met 404/410-opruiming"
```

---

### Task 5: Push-wiring in `signal_processor.py`

**Files:**
- Modify: `app/signal_processor.py`

**Interfaces:**
- Consumes: `push_notify.send_push(user_id, title, body, url, silent)` (Task 4)

Drie call sites in dit bestand worden push: nieuw signaal (`send_signal`, regel 927), SL/TP-update (`send_signal_update`, regel 1050), en swing-signaal vanuit een bewaakt niveau (`send_swing_signal`, regel 513). De `send_signal_chart`-aanroep (regel 951) vervalt zonder vervanging.

- [ ] **Step 1: Import bovenaan toevoegen**

```python
from app import push_notify
```

(naast de bestaande `from app import ... telegram_notify` — die regel blijft nog staan, andere functies in dit bestand gebruiken hem nog tot Taak 7/11).

- [ ] **Step 2: `send_signal`-aanroep (rond regel 924-944) vervangen**

Huidige code (context, niet letterlijk kopiëren — de exacte variabelenamen in dit blok, `force_silent`, `stop_was_capped`, `effective_stop_loss` etc. staan al goed, alleen de verzendaanroep zelf en de chart-aanroep veranderen):

```python
        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            stop_was_capped = effective_stop_loss != stop_take.stop_loss
            confidence = signal_data["confidence"].upper()
            title = f"{_coin_symbol(interp.coin)} {interp.coin} {interp.direction}, {confidence.lower()} vertrouwen"
            body = f"Entry {effective_stop_loss and signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            await push_notify.send_push(
                user["id"], title, body, f"/coins/{interp.coin}", silent=force_silent,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Pushmelding voor gebruiker %s, signaal %s is mislukt",
                              user["username"], signal_id)
            continue
```

`_coin_symbol` bestaat al in `telegram_notify.py` als privé-helper (`_coin_label`/richting-emoji) — die logica hoort hier niet opnieuw uitgevonden te worden. Voeg een kleine, publieke `coin_symbol(coin: str) -> str`-functie toe aan `app/push_notify.py` (Task 4 was daar nog niet op gebouwd, dus dit is een kleine aanvulling nu):

```python
_COIN_SYMBOLS = {"BTC": "₿", "ETH": "Ξ"}


def coin_symbol(coin: str) -> str:
    return _COIN_SYMBOLS.get(coin.upper(), "")
```

en gebruik in `signal_processor.py`: `push_notify.coin_symbol(interp.coin)`.

Verwijder de hele `if chart_bytes and not stop_was_capped:`-blok eronder (de `send_signal_chart`-aanroep) — de coin-pagina waar de push naartoe wijst toont de grafiek al, geen apart plaatje meer.

Fix de f-string hierboven: `effective_stop_loss and signal_data['price']:.4f` is een tikfout in dit voorbeeld voor de entry-prijs, moet gewoon `signal_data['price']:.4f` zijn:

```python
            body = f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
```

- [ ] **Step 3: `send_signal_update`-aanroep (rond regel 1048-1052) vervangen**

```python
        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            title = f"{'Take profit' if update_kind == 'tp_hit' else 'Stop loss'} geraakt op {interp.coin}"
            body = f"Resultaat: {result_eur:+.2f} EUR" if result_eur is not None else "Bekijk de trade in de app."
            await push_notify.send_push(user["id"], title, body, f"/coins/{interp.coin}", silent=force_silent)
        except Exception:
            logger.exception("Pushmelding (update) voor gebruiker %s mislukt", user["username"])
```

Zoek de exacte variabelenamen op rond regel 1030-1052 (`grep -n "update_kind\|result_eur" app/signal_processor.py`) — dit blok gebruikt waarschijnlijk andere lokale namen dan hierboven aangenomen; pas de f-strings aan op wat daar al berekend wordt, de payload-vorm (title/body/url/silent) blijft hetzelfde.

- [ ] **Step 4: `send_swing_signal`-aanroep (rond regel 501-518) vervangen**

Zelfde patroon: `force_silent` blijft, `push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=force_silent)` in plaats van de Telegram-aanroep. Titel/body naar dezelfde stijl als Step 2 (coin, richting, "vanuit bewaakt niveau" in de body i.p.v. entry/stop/take, want een swing-signaal heeft die structuur niet 1-op-1 — check de exacte velden die `send_swing_signal` nu meekrijgt met `grep -n "def send_swing_signal" -A 20 app/telegram_notify.py` en gebruik dezelfde brongegevens).

- [ ] **Step 5: Scratch-verificatie**

Er is geen geïsoleerde testhaak voor deze drie call sites zonder de volledige pijplijn te draaien (ze zitten diep in `_process_one_coin`/`process_day_trading_signal`). Verifieer in plaats daarvan met een statische check dat er geen `telegram_notify.send_signal(`, `telegram_notify.send_signal_update(`, `telegram_notify.send_swing_signal(` of `telegram_notify.send_signal_chart(` meer voorkomt in dit bestand:

```bash
cd /home/user/Trade
grep -n "telegram_notify.send_signal\|telegram_notify.send_swing_signal" app/signal_processor.py
```

Expected: geen output (lege grep = geslaagd). En dat de module zonder syntaxfout importeert:

```bash
python3 -c "from app import signal_processor"
```

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add app/signal_processor.py app/push_notify.py
git commit -m "signal_processor.py: nieuw signaal, SL/TP-update en swing-signaal naar push"
```

---

### Task 6: Push-wiring in `market_scanner.py` en `web/main.py`

**Files:**
- Modify: `app/market_scanner.py`
- Modify: `web/main.py`

**Interfaces:**
- Consumes: `push_notify.send_push`, `push_notify.coin_symbol` (Task 4/5)

- [ ] **Step 1: Import in `app/market_scanner.py`**

```python
from app import push_notify
```

- [ ] **Step 2: `send_breakout_retest_alert` (regel 96-100) en `send_trendline_retest_alert` (regel 180-184) vervangen**

Beide zelfgedetecteerde signalen, zelfde `force_silent`/`is_quiet_now`-logica blijft. Vervang:

```python
        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, zelf gedetecteerd"
            body = f"Entry {ind.price:.4f} · Stop {stop_take.stop_loss:.4f} · Take profit {stop_take.take_profit:.4f}"
            await push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=force_silent)
        except Exception:
            logger.exception(
                "Pushmelding (uitbraak-terugtest) voor %s naar gebruiker %s is mislukt", coin, user["username"],
            )
```

Zelfde vorm voor de trendline-variant, met "trendlijn-terugtest" in plaats van "uitbraak-terugtest" in de logregel. `telegram_notify` blijft geïmporteerd in dit bestand voor `is_quiet_now` — dat blijft zo tot Taak 11 (zie note in Taak 7).

- [ ] **Step 3: `send_eval_danger_alert` in `web/main.py` (regel 946-948) vervangen**

Dit is de 85%-drempel-waarschuwing op een actieve Kraken-evaluatie — expliciet als push behandelen, niet als quiet, ongeacht dat het over risicobeheer gaat in plaats van een nieuw signaal:

```python
    title = f"Evaluatie: {pct_type} op {pct_value:.0f}%"
    body = f"Nog {remaining_eur:.0f} EUR ruimte over van {active_eval['tier_amount']:.0f} EUR tier."
    await push_notify.send_push(user_id, title, body, "/evaluatie", silent=False)
```

Let op: `_check_eval_danger_alert` heeft nu `chat_id` als parameter (voor Telegram), maar heeft ook `evaluation_id`/`active_eval` al in scope — vervang de parameter door `user_id: int` (de aanroeper geeft dat al door of kan het makkelijk meegeven, check de aanroepende functie van `_check_eval_danger_alert`). Voeg `from app import push_notify` toe bovenaan `web/main.py` als dat er nog niet staat.

- [ ] **Step 4: `send_demo_signal_message` (regel 876-883) wordt een testpush**

```python
@app.post("/telegram/voorbeeld")
async def send_demo_push_message(user: dict = Depends(require_login)):
    """Stuurt een testpush naar elk apparaat van de ingelogde gebruiker:
    laat zien hoe een echte melding eruitziet, én bevestigt meteen dat
    het abonnement van dit apparaat werkt."""
    await push_notify.send_push(
        user["id"], "Ξ ETH long, hoog vertrouwen (voorbeeld)",
        "Entry 2340.0000 · Stop 2290.0000 · Take profit 2430.0000",
        "/dashboard", silent=False,
    )
    return RedirectResponse(url="/dashboard", status_code=303)
```

De route-naam (`send_demo_telegram_message` → `send_demo_push_message`) en het pad (`/telegram/voorbeeld`) mogen verschillen; check of `web/templates/dashboard.html` deze route bij naam of bij pad aanroept (`grep -n "telegram/voorbeeld" web/templates/*.html`) en werk de knoptekst/het formulier-`action` bij naar wat logisch is (bijvoorbeeld `/push/voorbeeld`), consistent in route én template.

- [ ] **Step 5: Verificatie**

```bash
cd /home/user/Trade
python3 -c "from app import market_scanner; from web import main"
grep -n "telegram_notify.send_breakout_retest_alert\|telegram_notify.send_trendline_retest_alert\|telegram_notify.send_eval_danger_alert\|telegram_notify.send_demo_signal_message" app/market_scanner.py web/main.py
```

Expected: modules importeren zonder fout, grep geeft geen output.

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add app/market_scanner.py web/main.py
git commit -m "market_scanner.py en web/main.py: zelf gedetecteerde signalen en evaluatie-waarschuwing naar push"
```

---

### Task 7: Quiet-list wiring (rustige meldingen)

**Files:**
- Modify: `app/signal_processor.py`
- Modify: `app/periodic_summary.py`
- Modify: `app/health_check.py`

**Interfaces:**
- Consumes: `repo.create_notification` (Task 1)

Zes call sites worden een `notifications`-rij in plaats van een verzendaanroep: `send_expired_pending_message`, `send_stale_pending_message`, `send_narrative_update` (alle drie in `signal_processor.py`), `send_period_summary` (`periodic_summary.py`), en `send_admin_alert` op twee plekken (`health_check.py` en `signal_processor.py:149`).

- [ ] **Step 1: `send_expired_pending_message` (signal_processor.py:781) en `send_stale_pending_message` (regel 818)**

```python
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
```

Zelfde vorm voor `send_stale_pending_message`, tekst aanpassen ("oude melding vervangen door een nieuw signaal" in plaats van "tegenovergestelde richting").

- [ ] **Step 2: `send_narrative_update` (signal_processor.py:363)**

Dit gebeurt in `_send_narrative_notifications`, dat nu een `telegram_message_id` bijhoudt via `repo.upsert_narrative_notification` om een bestaand bericht te *bewerken* in plaats van een nieuwe rij te sturen (edit-gedrag, Web Push/een notification-rij kent dat onderscheid niet — elke update wordt gewoon een nieuwe rij):

```python
    for user in repo.list_users():
        try:
            repo.create_notification(
                user["id"], "narrative_update",
                f"Verhaal-update: {narrative['coin']}",
                _narrative_summary_text(narrative, timeline, is_contradiction, contradicted_since),
                f"/coins/{narrative['coin']}",
            )
        except Exception:
            logger.exception("Verhaal-melding voor %s naar gebruiker %s is mislukt",
                              narrative["coin"], user["username"])
```

De `if not user["telegram_chat_id"]: continue`-check vervalt (elke gebruiker krijgt nu een rij, ongeacht of hij push heeft ingesteld — het staat gewoon klaar op `/meldingen`). `_narrative_summary_text` bestaat nog niet: haal de tekstopbouw uit `telegram_notify.format_narrative_update` of vergelijkbare functie (`grep -n "def format_narrative" app/telegram_notify.py`) en zet een kale-tekst-variant (zonder Telegram-opmaak/emoji) in `signal_processor.py` of `repo.py` als kleine helper. De `existing`/`existing_message_id`-opzoeklogica (`repo.get_narrative_notification`, `repo.upsert_narrative_notification`) vervalt hier — die diende alleen het Telegram-bewerken, niet meer nodig.

- [ ] **Step 3: `send_admin_alert` op beide plekken**

`health_check.py:67`:

```python
    if problems:
        repo.create_notification(
            None, "system_health", "HesPulse zelfcheck",
            "; ".join(problems), None,
        )
```

Verwijder de `if not config.TELEGRAM_BOT_TOKEN or not config.ADMIN_TELEGRAM_CHAT_ID:`-guard eromheen (regel 57-59) — die gold alleen voor de Telegram-verzending, een `notifications`-insert heeft geen tokens nodig. `from app import repo` toevoegen bovenaan `health_check.py`, `telegram_notify`-import mag weg als er verder niets anders in dit bestand op leunt (check met `grep -n telegram_notify app/health_check.py` na deze wijziging).

`signal_processor.py:149`:

```python
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
```

- [ ] **Step 4: `send_period_summary` (periodic_summary.py:47)**

Check eerst de exacte inhoud/opbouw met `grep -n "def send_period_summary" -A 30 app/telegram_notify.py` en `grep -n "def format_period_summary" -A 40 app/telegram_notify.py` (als die bestaat) om de samenvattingstekst te hergebruiken. Vervang de verzendaanroep door:

```python
        repo.create_notification(
            user["id"], "period_summary", "Weekoverzicht",
            summary_text, "/dashboard",
        )
```

waarbij `summary_text` de platte-tekst-variant is van wat `format_period_summary` nu opbouwt (zonder Telegram-markdown/emoji-opmaak die niet past in een korte lijst-rij — hergebruik de cijfers, herschrijf de opmaak).

- [ ] **Step 5: Verificatie**

```bash
cd /home/user/Trade
python3 -c "from app import signal_processor, periodic_summary, health_check"
grep -n "telegram_notify.send_expired_pending_message\|telegram_notify.send_stale_pending_message\|telegram_notify.send_narrative_update\|telegram_notify.send_period_summary\|telegram_notify.send_admin_alert" app/signal_processor.py app/periodic_summary.py app/health_check.py
```

Expected: modules importeren, grep geeft geen output.

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add app/signal_processor.py app/periodic_summary.py app/health_check.py
git commit -m "Rustige meldingen (vervallen signalen, verhaal-updates, weekoverzicht, admin-alerts) naar notifications-tabel"
```

---

### Task 8: `/meldingen`-pagina + admin-afscherming

**Files:**
- Modify: `web/main.py`
- Create: `web/templates/meldingen.html`
- Modify: `web/templates/base.html` (navigatielink)

**Interfaces:**
- Consumes: `repo.list_notifications`, `repo.list_admin_notifications`, `repo.mark_notification_read` (Task 1), `config.ADMIN_USERNAME` (Task 2)

- [ ] **Step 1: `is_admin`-fix op regel 687**

Huidige regel:

```python
    is_admin = bool(config.ADMIN_TELEGRAM_CHAT_ID) and user["telegram_chat_id"] == config.ADMIN_TELEGRAM_CHAT_ID
```

Vervangen door:

```python
    is_admin = bool(config.ADMIN_USERNAME) and user["username"] == config.ADMIN_USERNAME
```

Dit is de enige plek in de huidige codebase die `is_admin` zo berekent (bevestig met `grep -rn "is_admin = " web/main.py`); als er meer plekken zijn, allemaal op dezelfde manier bijwerken.

- [ ] **Step 2: Route toevoegen**

```python
@app.get("/meldingen", response_class=HTMLResponse)
async def meldingen_page(request: Request, user: dict = Depends(require_login)):
    is_admin = bool(config.ADMIN_USERNAME) and user["username"] == config.ADMIN_USERNAME
    return templates.TemplateResponse(
        "meldingen.html",
        {
            "request": request, "user": user,
            "notifications": repo.list_notifications(user["id"]),
            "admin_notifications": repo.list_admin_notifications() if is_admin else None,
        },
    )


@app.post("/meldingen/{notification_id}/gelezen")
async def mark_notification_read(notification_id: int, user: dict = Depends(require_login)):
    repo.mark_notification_read(notification_id, user["id"])
    return {"ok": True}
```

Check de bestaande naamgeving van `templates` (Jinja2Templates-instantie) en `HTMLResponse`-import bovenaan `web/main.py`, hergebruik die.

- [ ] **Step 3: `web/templates/meldingen.html`**

```html
{% extends "base.html" %}
{% block title %}Meldingen{% endblock %}
{% block content %}
<h1>Meldingen</h1>

{% if admin_notifications is not none %}
<section>
  <h2>Systeem (alleen jij)</h2>
  <ul class="notification-list">
    {% for n in admin_notifications %}
    <li class="{{ 'unread' if not n.is_read else '' }}">
      <strong>{{ n.title }}</strong>
      <p>{{ n.body }}</p>
      <time>{{ n.created_at }}</time>
    </li>
    {% else %}
    <li class="empty">Geen systeemmeldingen.</li>
    {% endfor %}
  </ul>
</section>
{% endif %}

<section>
  <h2>Jouw meldingen</h2>
  <ul class="notification-list">
    {% for n in notifications %}
    <li class="{{ 'unread' if not n.is_read else '' }}" data-notification-id="{{ n.id }}">
      <a href="{{ n.url or '#' }}" class="mark-read-link">
        <strong>{{ n.title }}</strong>
        <p>{{ n.body }}</p>
        <time>{{ n.created_at }}</time>
      </a>
    </li>
    {% else %}
    <li class="empty">Nog geen meldingen.</li>
    {% endfor %}
  </ul>
</section>

<script>
document.querySelectorAll(".mark-read-link").forEach(function (link) {
  link.addEventListener("click", function () {
    const li = link.closest("li[data-notification-id]");
    fetch("/meldingen/" + li.dataset.notificationId + "/gelezen", { method: "POST" }).catch(function () {});
  });
});
</script>
{% endblock %}
```

Check de exacte block-namen (`{% block title %}`/`{% block content %}`) in een bestaand template zoals `web/templates/evaluatie.html` (`head -20 web/templates/evaluatie.html`) en volg die precies — de bovenstaande namen zijn een aanname.

- [ ] **Step 4: Navigatielink in `base.html`**

Zoek de bestaande navigatie (`grep -n "/evaluatie\|/uitleg" web/templates/base.html`) en voeg een link naar `/meldingen` toe in dezelfde stijl/lijst.

- [ ] **Step 5: Handmatige Playwright-verificatie**

```bash
cd /home/user/Trade
source .venv/bin/activate
DATABASE_PATH=/tmp/scratch_meldingen.db uvicorn web.main:app --reload &
sleep 2
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    page = browser.new_page()
    page.goto('http://127.0.0.1:8000/login')
    # inloggen met een testaccount dat al bestaat in scratch_meldingen.db, of eerst aanmaken
    page.screenshot(path='/tmp/meldingen_login.png')
    browser.close()
"
```

Maak eerst een testaccount aan met `scripts/create_user.py` tegen dezelfde `DATABASE_PATH`, log in, navigeer naar `/meldingen`, en controleer visueel (screenshot) dat de pagina rendert zonder Jinja2-fout en dat een via `repo.create_notification` ingevoegde testrij verschijnt.

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/main.py web/templates/meldingen.html web/templates/base.html
git commit -m "/meldingen-pagina met admin-afscherming via ADMIN_USERNAME"
```

---

### Task 9: App-icoon-badge meetelt ongelezen meldingen

**Files:**
- Modify: `web/main.py`
- Modify: `web/templates/base.html`

**Interfaces:**
- Consumes: `repo.count_unread_notifications` (Task 1)

- [ ] **Step 1: `api_system_status` uitbreiden (web/main.py:809-819)**

```python
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

- [ ] **Step 2: `base.html` JS bijwerken (regel 811-814)**

```javascript
          if ("setAppBadge" in navigator) {
            var badgeTotal = s.pending_count + s.unread_notifications;
            if (badgeTotal > 0) navigator.setAppBadge(badgeTotal).catch(function () {});
            else navigator.clearAppBadge().catch(function () {});
          }
```

- [ ] **Step 3: Verificatie**

```bash
cd /home/user/Trade
DATABASE_PATH=/tmp/scratch_badge.db python3 -c "
from app import db, repo
db.init_db()
with db.session() as conn:
    conn.execute(\"INSERT INTO users (username, password_hash, created_at) VALUES ('t3', 'x', ?)\", (db.now_iso(),))
    uid = conn.execute('SELECT id FROM users WHERE username = ?', ('t3',)).fetchone()['id']
repo.create_notification(uid, 'test', 'T', 'B', None)
assert repo.count_unread_notifications(uid) == 1
print('OK')
"
```

Expected: `OK`. Voor de JS-kant: start `uvicorn` (Task 3 Step 4-commando), open `/dashboard`, bevestig via de browser-devtools dat `fetch('/api/system-status')` (of het exacte pad, check met `grep -n "api/system-status\|api_system_status" web/main.py`) een `unread_notifications`-veld teruggeeft.

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add web/main.py web/templates/base.html
git commit -m "App-icoon-badge telt ongelezen meldingen mee"
```

---

### Task 10: Service worker push-handlers

**Files:**
- Modify: `web/static/service-worker.js`

**Interfaces:**
- Consumes: payload-vorm `{title, body, url, icon, silent}` zoals gebouwd in `app/push_notify.py` (Task 4)

- [ ] **Step 1: Twee event listeners toevoegen**

Aan het eind van `web/static/service-worker.js`, na de bestaande `fetch`-listener (regel 35-55), niets daarin wijzigen:

```javascript
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      silent: !!data.silent,
      data: { url: data.url },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data && event.notification.data.url;
  if (url) event.waitUntil(clients.openWindow(url));
});
```

- [ ] **Step 2: Verificatie (samen met Task 3's browsertest)**

Er is geen geautomatiseerde manier om een echte pushmelding vanuit een scratch-script te triggeren (dat vereist een bereikbare pushdienst-endpoint). Verifieer in de browser-devtools onder Application → Service Workers dat de nieuwe listeners geregistreerd zijn (geen foutmelding bij het herladen van de service worker), en test de volledige keten pas in Task 11's handmatige VPS-verificatie met een echte `send_push`-aanroep (bijvoorbeeld via de testpush-knop uit Task 6 Step 4).

- [ ] **Step 3: Commit**

```bash
cd /home/user/Trade
git add web/static/service-worker.js
git commit -m "Service worker: push-melding tonen en doorklikken naar de juiste pagina"
```

---

### Task 11: Telegram verwijderen + volledige regressie + push

**Files:**
- Delete: `app/telegram_notify.py`
- Modify: `main.py`
- Modify: `app/signal_processor.py`, `app/market_scanner.py`, `app/health_check.py`, `web/main.py` (resterende imports/aanroepen van `telegram_notify`, met name `is_quiet_now`)
- Modify: `app/config.py`, `.env.example`, `requirements.txt`
- Modify: `app/schema.sql` (comment bijwerken, kolom zelf blijft staan)

Dit is de enige taak die Telegram echt verwijdert — pas uitvoeren nadat Task 1 t/m 10 gepusht staan en de gebruiker bevestigd heeft dat een testpush (Task 6 Step 4) op zijn telefoon aankomt.

- [ ] **Step 1: `is_quiet_now` verplaatsen voordat `telegram_notify.py` verdwijnt**

`app/signal_processor.py` en `app/market_scanner.py` gebruiken nog `telegram_notify.is_quiet_now(...)` op meerdere plekken (dit is puur een tijdvenster-berekening, niets Telegram-specifieks aan). Verplaats de functie zelf naar `app/push_notify.py`:

```python
from datetime import datetime, time as dtime


def is_quiet_now(quiet_hours_start, quiet_hours_end) -> bool:
    """Verplaatst uit het oude telegram_notify.py: puur een tijdvenster-
    check, niets Telegram-specifieks. Ongewijzigde logica."""
    if not quiet_hours_start or not quiet_hours_end:
        return False
    now = datetime.now().time()
    start = datetime.strptime(quiet_hours_start, "%H:%M").time()
    end = datetime.strptime(quiet_hours_end, "%H:%M").time()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end
```

Kopieer de exacte bestaande implementatie uit `app/telegram_notify.py:83-...` (`grep -n "def is_quiet_now" -A 15 app/telegram_notify.py` voor de precieze logica, vooral de dag-overschrijdende `start > end`-tak) in plaats van de aanname hierboven blind over te nemen. Vervang in `signal_processor.py` en `market_scanner.py` elke `telegram_notify.is_quiet_now(...)` door `push_notify.is_quiet_now(...)`.

- [ ] **Step 2: Alle resterende `telegram_notify`-imports verwijderen**

```bash
cd /home/user/Trade
grep -rln "telegram_notify" app/ web/ main.py
```

Voor elk gevonden bestand: verwijder de `import`-regel en controleer dat er geen enkele `telegram_notify.`-aanroep meer overblijft (na Step 1 zou dat alleen nog de importregel zelf moeten zijn).

- [ ] **Step 3: `app/telegram_notify.py` verwijderen**

```bash
cd /home/user/Trade
git rm app/telegram_notify.py
```

- [ ] **Step 4: Telegram `/start`-listener uit `main.py` verwijderen**

Zoek de `asyncio.gather(...)`-opzet die de Discord-bot en de Telegram-listener samen start (`grep -n "asyncio.gather\|telegram" main.py`), verwijder de Telegram-tak, laat de Discord-bot en eventuele andere achtergrondtaken ongewijzigd draaien.

- [ ] **Step 5: Config opruimen**

`app/config.py`: verwijder `TELEGRAM_BOT_TOKEN` en `ADMIN_TELEGRAM_CHAT_ID` (regel 22 en 71) — `ADMIN_USERNAME` staat er al sinds Task 2, blijft. `.env.example`: verwijder de bijbehorende secties, laat de VAPID/ADMIN_USERNAME-secties staan. `requirements.txt`: verwijder `python-telegram-bot`.

- [ ] **Step 6: `telegram_chat_id`-gebruik in UI opruimen**

De kolom zelf blijft in `users` (geen `DROP COLUMN`-migratie, SQLite maakt dat onnodig lastig en de spec vraagt er niet om), maar elke plek die hem nog toont of erop filtert in de UI moet weg: het instellingenformulier op het dashboard (`grep -n "telegram_chat_id" web/templates/dashboard.html`) en de bijbehorende `update_user_settings`-aanroep in `web/main.py` (regel 870-872) — laat het veld gewoon weg uit het formulier en de aanroep, `repo.update_user_settings` zelf hoeft niet per se te wijzigen als de parameter al optioneel is (check de signatuur).

- [ ] **Step 7: Volledige regressie**

```bash
cd /home/user/Trade
source .venv/bin/activate
python3 -c "
import app.config, app.db, app.repo, app.push_notify, app.signal_processor
import app.market_scanner, app.health_check, app.periodic_summary
import web.main
print('OK: alle modules importeren zonder telegram_notify')
"
grep -rn "telegram_notify\|TELEGRAM_BOT_TOKEN\|ADMIN_TELEGRAM_CHAT_ID" app/ web/ main.py
```

Expected: `OK: alle modules importeren zonder telegram_notify`, en de laatste `grep` geeft geen output (op eventuele historische verwijzingen in `docs/` of oude specs na, die blijven ongemoeid).

Draai daarna de complete scratch-DB-vlucht die dit project al gebruikt bij eerdere grote wijzigingen: `db.init_db()` op een verse `DATABASE_PATH`, een testgebruiker aanmaken, een nep-signaal door `signal_processor.handle_message` of een vergelijkbare ingang halen (kijk naar hoe eerdere plannen dit deden, bijvoorbeeld de marktscan- of coin-narratives-plannen, dezelfde opzet hergebruiken) en bevestigen dat er geen crash optreedt en dat er een rij in `notifications` en/of een `push_notify.send_push`-aanroep plaatsvindt (mock `push_notify.webpush` net als in Task 4 Step 2 om een echte netwerkaanroep te vermijden).

- [ ] **Step 8: Commit en push**

```bash
cd /home/user/Trade
git add -A
git commit -m "Telegram volledig verwijderd, HesPulse-app is nu het enige meldingenkanaal"
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 9: Exacte VPS-deploy-commands voor de gebruiker**

```bash
cd /opt/crypto-alerts
git pull origin claude/crypto-day-trading-alerts-5p8w6v
source .venv/bin/activate
pip install -r requirements.txt
```

Daarna `.env` aanvullen met `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIM_EMAIL`, `ADMIN_USERNAME` (het sleutelpaar genereren zoals in Task 2 Step 2, dit keer op de VPS zelf zodat de private key nooit via een ander kanaal reist):

```bash
python3 -c "
from py_vapid import Vapid02
v = Vapid02()
v.generate_keys()
print('VAPID_PUBLIC_KEY=' + v.public_key_str())
print('VAPID_PRIVATE_KEY=' + v.private_key_str())
"
nano .env   # de vier nieuwe regels toevoegen/invullen
```

Dan herstarten:

```bash
sudo systemctl restart crypto-bot crypto-web
sudo systemctl status crypto-bot --no-pager
sudo systemctl status crypto-web --no-pager
```

Tenslotte, per gebruiker: inloggen op het dashboard, "Meldingen aanzetten" klikken, en de testpush-knop (Task 6 Step 4) gebruiken om te bevestigen dat een echte melding op de telefoon aankomt vóórdat je erop vertrouwt voor een live signaal.

---

## Self-Review

**Spec-dekking:** elke sectie van `docs/superpowers/specs/2026-09-15-push-meldingen-design.md` heeft een taak: datamodel → Task 1, VAPID → Task 2, abonneerflow → Task 3, versturen + volledige call-site-inventarisatie → Task 5/6, service worker → Task 10, rustige lijst → Task 8, badge → Task 9, foutafhandeling (404/410) → Task 4, wat verdwijnt (incl. de `is_admin`-fix) → Task 8 (fix) + Task 11 (verwijdering), testen → elke taak heeft een scratch-stap, Task 11 Step 7 is de volledige regressie.

**Placeholder-scan:** geen "TBD"/"later toevoegen". Waar exacte bestaande code niet 1-op-1 overgenomen kon worden zonder het bestand zelf te lezen (bijvoorbeeld de exacte velden van `send_swing_signal`, de precieze opbouw van `format_period_summary`), staat een concreet `grep`-commando dat de uitvoerder naar de echte bestaande tekst leidt — geen giswerk, wel een expliciete opzoekstap in plaats van kant-en-klare code die toch fout zou kunnen zijn zonder die bron gezien te hebben.

**Type-consistentie:** `push_notify.send_push(user_id, title, body, url, silent)` heeft overal dezelfde signatuur (Task 4 definieert hem, Task 5/6 gebruiken hem exact zo). `repo.create_notification(user_id, type, title, body, url)` idem. `is_quiet_now` verhuist in Task 11 van `telegram_notify` naar `push_notify` met ongewijzigde signatuur, en alle aanroepers in Task 5/6 blijven `telegram_notify.is_quiet_now` gebruiken tot Task 11 dat in één keer omzet — bewust zo volgordelijk, anders zou Task 5 al een functie aanroepen die nog niet bestaat.
