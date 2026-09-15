# Push-meldingen via de HesPulse-app (i.p.v. Telegram)

## Context

HesPulse stuurt nu alle meldingen aan gebruikers via Telegram
(`app/telegram_notify.py`): nieuwe signalen, SL/TP-updates, vervallen
signalen, lange-termijn-verhaal-updates, wekelijkse samenvattingen, en
naar de beheerder een systeemgezondheid-alert. Aanleiding voor dit
deelproject: de gebruiker vindt Telegram niet overzichtelijk genoeg en te
druk, en wil dat de HesPulse-app zelf de meldingen verzorgt, met een
scherpe knip tussen wat er echt uit moet springen en wat rustig kan
wachten.

Dit is het eerste van vier deelprojecten uit een bredere visie (de
andere drie: minder tegenstrijdige signalen op korte termijn, Smart
Money Concepts, en een sterk verbeterde autonome scan). Die staan
gepland als eigen spec + plan zodra dit deelproject live staat.

## Beslissingen uit de brainstorm

- Telegram wordt volledig vervangen, ook het admin-gezondheidskanaal.
  Harde knip voor alle gebruikers tegelijk, geen overgangsperiode
  waarin beide kanalen naast elkaar bestaan. Een gebruiker die zijn
  pushmeldingen nog niet heeft ingesteld, mist dus meldingen totdat hij
  dat doet — geaccepteerd risico, expliciet gekozen boven een vangnet.
- Pushmeldingen (echte systeemmelding, met geluid, ook als de telefoon
  vergrendeld is) zijn er alleen voor tijdkritische, uitvoerbare
  gebeurtenissen. Dit was in de brainstorm zelf een korte lijst van
  vier; de volledige inventarisatie in "Versturen (server → client)"
  hieronder telt er zeven, met dezelfde onderliggende logica
  (tijdkritisch en/of direct uitvoerbaar):
  - Nieuw signaal, ongeacht bron: Discord-getriggerd, zelf gedetecteerd
    door de marktscan, vanuit een bewaakt niveau (swing), of een
    uitbraak/trendlijn-terugtest
  - SL/TP geraakt op een open trade
  - Prijs terug bij een eerder gemist niveau (bestaand mechanisme in
    `level_check.py`)
  - Herhaald-verlies-waarschuwing van de marktscan (veiligheidsrem)
  - 85%-drempel op dagverlies of drawdown van een actieve
    Kraken-evaluatie: dit raakt het account waar echt getraded wordt,
    dus net zo tijdkritisch als een SL/TP-melding
- Alles wat niet in die lijst staat gaat naar een rustige, stille lijst
  in de app zelf, zonder geluid of piep: vervallen pending signaal
  (zonder terugkeer naar het niveau), lange-termijn-verhaal-updates,
  wekelijkse samenvatting, weekoverzicht, en systeemgezondheid
  (alleen zichtbaar voor de beheerder).
- Tikken op een pushmelding opent de app op de relevante coin-pagina.
  Er komen geen actieknoppen op de melding zelf (dat kon in Telegram
  wel, Genomen/Negeren); de gebruiker doet die actie in de app.
- De pushmelding zelf is kort en zakelijk: titel = coin, richting,
  vertrouwen. Body = alleen de kerncijfers (entry, stop, take profit).
  Geen emoji-opeenstapeling, geen disclaimer, geen factor-lijst in de
  melding — die volledige analyse staat al op de coin-pagina waar de
  melding naartoe leidt.
- Bestaande stille-uren-instelling (`quiet_hours_start`/`quiet_hours_end`
  op de `users`-tabel, `telegram_notify.is_quiet_now`) blijft gelden:
  buiten stille uren normaal geluid, erbinnen wordt de melding wel
  getoond maar stil.
- Aanpak: eigen Web Push met VAPID-sleutels (bibliotheek `pywebpush`),
  geen externe pushdienst (Firebase/OneSignal). Blijft in eigen beheer,
  past bij de rest van de architectuur (alles zelf gehost, één
  gedeelde SQLite-database).

## Datamodel

Twee nieuwe tabellen in `app/schema.sql`, met bijbehorende idempotente
migratie in `app/db.py:_migrate()` volgens de bestaande conventie
(`PRAGMA table_info`-check, dan `ALTER TABLE`/`CREATE TABLE IF NOT
EXISTS`).

```sql
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

`user_id` op `notifications` is nullable: een systeemgezondheid-rij
heeft geen normale gebruiker, die wordt apart gefilterd op `type =
'system_health'` en alleen aan het admin-account getoond (zie
"Rustige lijst in de app").

`push_subscriptions.endpoint` is uniek: bij een nieuw abonnement van
hetzelfde apparaat overschrijft `repo.py` de bestaande rij (upsert) in
plaats van een dubbele rij aan te maken.

## VAPID-sleutels

Eén keer gegenereerd sleutelpaar, opgeslagen als `VAPID_PUBLIC_KEY` en
`VAPID_PRIVATE_KEY` in `.env`, naast de bestaande secrets. De publieke
sleutel gaat ook naar de frontend (ingebakken in een template of via een
klein `/api/push/vapid-public-key`-endpoint), nodig om
`pushManager.subscribe()` in de browser aan te roepen.

## Abonneerflow (client → server)

1. Knop "Meldingen aanzetten" op het dashboard (zichtbaar zolang de
   gebruiker nog geen actief abonnement heeft op dit apparaat).
2. Klik vraagt `Notification.requestPermission()` aan; bij toestemming
   registreert de service worker een abonnement via
   `pushManager.subscribe({ userVisibleOnly: true, applicationServerKey:
   VAPID_PUBLIC_KEY })`.
3. Het abonnement-object (endpoint + keys.p256dh + keys.auth) gaat naar
   een nieuwe route `POST /api/push/subscribe`, die het via `repo.py`
   opslaat (upsert op `endpoint`).
4. Weigert de gebruiker toestemming, of is Web Push niet beschikbaar
   (bijvoorbeeld Safari zonder "toegevoegd aan beginscherm"), dan blijft
   de knop zichtbaar met een korte uitleg dat pushmeldingen daarvoor
   een geïnstalleerde app vereisen.

## Versturen (server → client)

Nieuwe module `app/push_notify.py`, zelfde rol als
`telegram_notify.py` nu.

```python
async def send_push(user_id: int, title: str, body: str, url: str) -> None:
    """Stuurt naar elk geregistreerd apparaat van deze gebruiker. Een
    apparaat dat de browser/OS niet meer kent (410/404 terug) wordt
    meteen verwijderd, anders blijft de tabel vervuild raken met dode
    abonnementen. Eén mislukt apparaat blokkeert de andere apparaten
    van dezelfde gebruiker niet, en blokkeert nooit de fan-out naar
    andere gebruikers (zelfde patroon als telegram_notify.send_signal
    nu al per gebruiker in zijn eigen try/except draait)."""
```

Payload (JSON, versleuteld door pywebpush volgens de Web Push-standaard):
`{"title": ..., "body": ..., "url": ..., "icon": "/static/icon-192.png"}`.

Volledige inventarisatie van elke huidige `telegram_notify`-aanroep in
de codebase, en waar die naartoe gaat. Dit verving een eerdere, te
grove indeling uit de brainstorm zelf ("de vier genoemde
gebeurtenissen") die drie call sites miste — vooral
`send_eval_danger_alert` is een gat dat ertoe doet: dat is de
waarschuwing dat je Kraken-evaluatie 85% van het dag- of
drawdown-budget verbruikt heeft, en dat account is inmiddels waar het
echte geld op staat.

| Huidige aanroep | Locatie | Wordt |
|---|---|---|
| `send_signal` | `signal_processor.py:927` | push (nieuw signaal) |
| `send_signal_update` | `signal_processor.py:1050` | push (SL/TP geraakt) |
| `send_signal_chart` | `signal_processor.py:951` | **vervalt**, geen vervanging — de coin-pagina waar de push naartoe wijst toont de grafiek al |
| `send_swing_signal` | `signal_processor.py:513` | push (nieuw signaal, vanuit een bewaakt niveau) |
| `send_breakout_retest_alert` | `market_scanner.py:98` | push (nieuw signaal, zelf gedetecteerd) |
| `send_trendline_retest_alert` | `market_scanner.py:182` | push (nieuw signaal, zelf gedetecteerd) |
| `send_eval_danger_alert` | `web/main.py:946` | **push**, niet quiet — 85%-drempel op het account waar echt getraded wordt is per definitie tijdkritisch |
| `send_expired_pending_message` | `signal_processor.py:781` | quiet (vervallen zonder terugkeer) |
| `send_stale_pending_message` | `signal_processor.py:818` | quiet (vervallen zonder terugkeer) |
| `send_narrative_update` | `signal_processor.py:363` | quiet (verhaal-update) |
| `send_period_summary` | `periodic_summary.py:47` | quiet (weekoverzicht) |
| `send_admin_alert` (systeemgezondheid) | `health_check.py:67` | quiet, admin-only |
| `send_admin_alert` (herhaalde API-fouten) | `signal_processor.py:149` | quiet, admin-only |
| `send_demo_signal_message` | `web/main.py:882` | **wordt een testpush** via `push_notify.send_push`, dubbel nut: laat zien hoe een melding eruitziet, én bevestigt dat het abonnement van dit apparaat echt werkt |
| `send_mute_suggestion`, `send_new_coin_message`, `send_untracked_coin_message` | — | dode code, geen enkele aanroep in de huidige codebase, wordt verwijderd, niet gemigreerd |

Elke "push"-rij hierboven roept straks `push_notify.send_push(...)` aan
op precies de plek waar nu de `telegram_notify`-aanroep staat. Elke
"quiet"-rij wordt een `repo.create_notification(...)`-insert in de
`notifications`-tabel in plaats van een verzendaanroep.

### Inhoud van de pushmelding

Titel: `"{coin-symbool} {COIN} {richting}, {vertrouwen}"`, bijvoorbeeld
`"Ξ ETH long, hoog vertrouwen"`. Body: alleen de kerncijfers,
bijvoorbeeld `"Entry 2340 · Stop 2290 · Take profit 2430"`. Voor
SL/TP-updates: `"Take profit geraakt op {coin}"` / `"Stop loss geraakt
op {coin}"` met het resultaat in euro's als er een concreet bedrag is.
Geen factor-breakdown, geen disclaimer, geen voortgangsbalk in de
melding zelf — dat blijft op de coin-pagina, waar `url` naartoe wijst.
Icoon: `/static/icon-192.png` (bestaand HesPulse-icoon).

## Service worker

`web/static/service-worker.js` krijgt twee nieuwe event listeners,
naast de bestaande install/activate/fetch-logica (die blijft
ongewijzigd, dit raakt alleen de PWA-schil, niet de caching-strategie):

```js
self.addEventListener("push", (event) => {
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      data: { url: data.url },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
```

## Rustige lijst in de app

Nieuwe pagina `/meldingen` (route in `web/main.py`, template
`web/templates/meldingen.html`): toont de rijen uit `notifications`
voor de ingelogde gebruiker, nieuwste boven, ongelezen visueel
gemarkeerd. Klikken op een rij zet `is_read=1` (via `repo.py`) en
volgt de `url` als die er is.

De systeemgezondheid-rijen (`type='system_health'`, `user_id IS NULL`)
zijn alleen zichtbaar als de ingelogde gebruiker het admin-account is.

Let op, dit raakt een bestaande aanname: `web/main.py:687` bepaalt
`is_admin` nu als `user["telegram_chat_id"] == config.ADMIN_TELEGRAM_CHAT_ID`.
Beide velden verdwijnen in dit plan (zie "Wat verdwijnt"), dus die
regel breekt zodra Telegram weg is. Vervanging: nieuwe config-variabele
`ADMIN_USERNAME` in `.env`, vergeleken met `user["username"]`
(`users.username` bestaat al, is uniek). `web/main.py:687` wordt
`is_admin = bool(config.ADMIN_USERNAME) and user["username"] ==
config.ADMIN_USERNAME`. Dit moet in dezelfde taak als de
Telegram-opruiming, niet erna, anders is er een moment waarop de
admin-pagina voor niemand meer werkt.

Het bestaande app-icoon-badge (taak #78, aantal niet-opgevolgde
meldingen) telt voortaan ook `SELECT COUNT(*) FROM notifications WHERE
user_id = ? AND is_read = 0` mee, naast wat het al telde.

## Wat verdwijnt

- `app/telegram_notify.py` en alle aanroepen ervan uit
  `signal_processor.py`, `market_scanner.py`, `level_check.py`,
  `health_check.py`, `periodic_summary.py`.
- `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_CHAT_ID`,
  `telegram_chat_id`-kolom op `users` en de Telegram `/start`-listener
  in `main.py`. `ADMIN_TELEGRAM_CHAT_ID` wordt vervangen door de nieuwe
  `ADMIN_USERNAME` (zie "Rustige lijst in de app"), niet zomaar
  verwijderd.
- python-telegram-bot uit `requirements.txt`.

Dit is een aparte opruimtaak aan het eind van het implementatieplan,
ná bevestiging dat de nieuwe pushmeldingen live werken — niet
tegelijk met de nieuwbouw, om nooit een moment zonder werkende
meldingen te hebben tijdens de overgang zelf.

## Foutafhandeling

- `pywebpush` gooit een `WebPushException` bij een mislukte aflevering.
  Statuscode 404/410 → abonnement is dood, meteen verwijderen uit
  `push_subscriptions`. Andere statuscodes → loggen en doorgaan, geen
  retry (zelfde "niet crashen, wel loggen" patroon als
  `telegram_notify.send_signal` nu al hanteert).
- Geen abonnementen voor een gebruiker → `send_push` doet niets, geen
  foutmelding (een gebruiker die nog geen pushmeldingen heeft
  ingesteld, mist ze gewoon, zoals besloten bij de harde knip).

## Testen

Geen pytest-suite in dit project. Verificatie zoals gebruikelijk via
een scratch-script tegen een scratch-database
(`DATABASE_PATH=/tmp/scratch.db`): een nep-abonnement inschrijven,
`push_notify.send_push` aanroepen tegen een lokale mock in plaats van
de echte push-dienst, en de opgebouwde payload en foutafhandeling
(404/410-pad) controleren. Een echte melding op een telefoon kan niet
vanuit deze omgeving getest worden; dat controleert de gebruiker zelf
op zijn eigen toestel na deploy, zoals bij eerdere features.

## Buiten scope

- Smart Money Concepts, minder tegenstrijdige signalen, en de
  verbeterde autonome scan: aparte deelprojecten, eigen spec.
- Geen vangnet/overgangsperiode met Telegram ernaast (expliciet
  afgewezen, harde knip).
- Geen actieknoppen op de pushmelding zelf (expliciet afgewezen,
  gebruiker tikt door naar de app).
