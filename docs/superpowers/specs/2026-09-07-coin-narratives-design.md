# Lopende verhalen per coin ("coin narratives")

## Aanleiding

Op 7 september 2026 deelde de gebruiker meerdere Discord-updates over TAO
verspreid over ruim een uur: een doorgestuurde community-analyse ("Lange
termijn TAO gekocht", met een lijst technische redenen), een vervolgbericht
("Extra ingeschaald op TAO", een breakout-bevestiging), en een kaal
doorgestuurd bericht met alleen de tekst "TAO" plus een link. Voor dat
laatste bericht kreeg de Anthropic-interpretatie vrijwel niets te lezen —
de eigenlijke analysetekst ("test de belangrijke weekly downtrendline van
644 dagen") zat verstopt in een Discord message-snapshot die de bot niet
meelas zodra het doorstuurbericht ook een eigen bijschrift had (apart al
gevonden en gefixt in `app/discord_bot.py`, commit `be08c57`). Met alleen
de kale grafiekafbeelding en geen begeleidende tekst interpreteerde de AI
dit losse bericht als **short**, terwijl de twee andere berichten over
dezelfde coin **long** waren.

Drie berichten, twee tegenstrijdige richtingen, binnen een uur. HesPulse
behandelt elk bericht volledig los: geen enkel verband met een eerder
bericht over dezelfde coin, zelfs niet als het overduidelijk om dezelfde
lopende positie gaat. Concreet zichtbaar op twee plekken:

1. **Geen samenhang tussen berichten.** Elk `lange_termijn`-bericht met een
   richting stuurt zijn eigen, volledig onafhankelijke stille Telegram-
   melding (`signal_processor.handle_message`, de tak voor
   `interp.category != "day_trading"`). Drie berichten over TAO binnen een
   uur leveren drie losse meldingen op, twee ervan tegenstrijdig, zonder dat
   er ooit vermeld wordt dat ze over dezelfde lopende kans gaan.
2. **Geen overzicht op de coin-pagina.** `web/main.py:coin_page` bouwt voor
   één coin tot wel zeven losse lijsten naast elkaar op: `open_trades`,
   `recent_signals`, de `sparkline`, `long_term_messages`,
   `active_swing_watches`, `source_levels`, `images`. Elk op zijn eigen
   tijdlijn, nergens gecombineerd. De prijsgrafiek zelf tekent alleen de
   "primaire" trade/signaallijn (zie `web/static/coin.js`), dus bij een
   langere geschiedenis van updates is niet meer te zien welke lijn bij
   welk moment hoort.

Dit document beschrijft hoe lange-termijn berichten over dezelfde coin en
richting tot één doorlopend, herkenbaar verhaal worden gegroepeerd, met een
duidelijke melding bij een tegenspraak in plaats van losse, verwarrende
alerts.

## Doel

Elk `lange_termijn`-bericht met een duidelijke richting (long/short) hoort
bij precies één "narrative": een doorlopend verhaal per coin + richting.
Een nieuw bericht dat aansluit bij een al lopend verhaal is een update
daarvan, geen nieuw, los ding. Een bericht met de tegenovergestelde
richting van een lopend verhaal wordt expliciet als tegenspraak gemeld, in
plaats van als een derde, ongerelateerde melding.

De gebruiker ziet op elk moment: welk verhaal loopt er nu voor deze coin,
sinds wanneer, hoeveel updates, en (als het van toepassing is) dat een
nieuw bericht een eerder verhaal tegenspreekt.

## Niet-doelen

- **Geen wijziging aan risico of positiegrootte.** Narratives zijn een
  organisatorisch/informatief concept: welk verhaal loopt er, niet "hoeveel
  moet je inzetten". Ze raken `journal_entries`, `risk.py` of
  positiegrootteberekening niet.
- **Geen samenvoeging met swing-watches.** Een narrative gaat over "welk
  verhaal loopt er nu voor deze coin" (berichten-niveau, elke richting).
  Een swing-watch gaat over "hou dit specifieke prijsniveau in de gaten"
  (niveau-niveau, uit een screenshot). Ze bestaan onafhankelijk naast
  elkaar voor dezelfde coin; een narrative-update creëert of raakt nooit
  een swing-watch en omgekeerd.
- **Geen automatische conflictoplossing tussen twee gebruikers die het
  oneens zijn.** Een tegenspraak binnen dit ontwerp betekent altijd:
  hetzelfde soort bericht (community-analyse, doorgestuurd door dezelfde
  gebruiker) wijst nu de andere kant op dan het vorige. Twee verschillende,
  gelijktijdig geldige meningen van twee community-leden worden niet apart
  gemodelleerd; dat blijft, zoals nu, gewoon twee berichten.
- **Geen backfill.** Telt vanaf het moment dat dit live gaat; bestaande
  `messages`-rijen worden niet met terugwerkende kracht in narratives
  gegroepeerd.
- **Geen herontwerp van de prijsgrafiek.** Alleen kleine, gelabelde
  markeringen op de bestaande grafiek (zie "Zichtbaarheid"); een volledige
  herziening van hoe de grafiek werkt is een apart, groter project.

## Architectuur

Nieuwe functie `evaluate_narrative(message_id, coin, direction)`,
aangeroepen vanuit `signal_processor.handle_message` voor elk
`lange_termijn`-bericht met een bekende richting (`direction in ("long",
"short")`; "neutraal" of leeg doet niet mee, net als bij de bestaande
`_build_context_note`-uitzondering).

```
evaluate_narrative(message_id, coin, direction)
├── actief narrative voor coin, ZELFDE richting?
│     → update: koppel bericht aan bestaand narrative,
│       verhoog message_count, zet last_update_at, GEEN nieuwe rij
├── actief narrative voor coin, TEGENOVERGESTELDE richting?
│     → zet dat narrative op status "tegengesproken", closed_reason
│       vastleggen; maak een NIEUW narrative voor de nieuwe richting;
│       koppel dit bericht daaraan (dit is de eerste update van het
│       nieuwe narrative)
└── geen actief narrative?
      → nieuw narrative, koppel dit bericht (eerste update)
```

Een narrative zonder nieuwe update in 84 dagen (zelfde termijn als
`signal_processor.SWING_WATCH_MAX_AGE_DAYS`, voor consistentie) verloopt
vanzelf naar status "verlopen". Dit wordt gecheckt in dezelfde 15-minuten
periodieke timer als `level_check.py` al gebruikt: een nieuwe
`check_narratives()`-functie, ernaast, niet erin — narratives hebben geen
prijs-gerelateerde toets nodig, alleen een leeftijdscheck.

**Statussen:** `actief`, `tegengesproken`, `verlopen`. Geen "afgesloten"
door de gebruiker: er is geen UI-actie die een narrative handmatig sluit in
deze versie, dat is een mogelijke latere uitbreiding, geen onderdeel van
dit ontwerp.

## Meldingen

Het eerste bericht van een nieuw narrative krijgt een normale, niet-stille
Telegram-melding per gebruiker (zelfde patroon als
`telegram_notify.send_long_term_message` nu al doet). Elke **volgende**
update binnen hetzelfde narrative **bewerkt diezelfde melding** in plaats
van een nieuwe te versturen (`bot.edit_message_text`), zodat de gebruiker
één regel per lopend verhaal in zijn Telegram-chat ziet die zichzelf
bijwerkt, in plaats van een opeenstapeling van losse berichten. De
bewerkte tekst toont de volledige, actuele stand: sinds wanneer het loopt,
hoeveel updates, en een korte tijdlijn van de berichten tot nu toe.

Telegram staat bewerken van een bericht toe tot 48 uur na versturen. Een
update op een narrative dat langer dan 48 uur geleden voor het laatst een
melding kreeg, stuurt in plaats van een edit een **verse melding** die het
hele verhaal opnieuw samenvat (en onthoudt dát nieuwe bericht-ID voor
eventuele latere edits, tot de volgende 48-uursgrens).

Een **tegenspraak** (een nieuw narrative dat een vorig, actief narrative
voor dezelfde coin tegenspreekt) krijgt **altijd** een eigen, verse,
niet-bewerkte melding, expliciet gelabeld als tegenspraak ("Let op: dit
spreekt je lopende long-analyse van 5 september tegen"), nooit verstopt in
een edit van een bericht dat de gebruiker misschien al dagen niet meer
heeft gezien.

Dit vereist per gebruiker het Telegram bericht-ID van de laatst verstuurde
melding voor een narrative te onthouden — zie "Datamodel".

## Day-trading crossover

`signal_processor._build_context_note(coin, direction)` (gebruikt in
`process_day_trading_signal` om een day-trading melding af te zetten tegen
recente lange-termijn context) wordt herbouwd op het actieve narrative in
plaats van op `repo.latest_long_term_direction` (de huidige, naïeve
"pak het allerlaatste bericht"-aanpak). Dit is niet alleen een uitbreiding
maar ook een directe verbetering: de huidige functie zou zich exact door
het foute TAO short-bericht hebben laten misleiden als dát toevallig het
laatste bericht was geweest. Een narrative dat al op "tegengesproken" of
"verlopen" staat, telt niet mee als "actuele lange-termijn context" — alleen
een `actief` narrative doet dat.

Gedrag ongewijzigd op de kernregel: het day-trading signaal wordt **niet**
tegengehouden of aangepast op basis van deze context, alleen de
begeleidende tekst in de melding verandert. Bij een tegenovergestelde
richting wordt dat expliciet benoemd, net zoals de bestaande functie dat nu
al voor de eenvoudige "laatste bericht"-vergelijking doet.

## Datamodel

Nieuwe tabel `coin_narratives` (geen migratie nodig, nieuwe tabel):

```sql
CREATE TABLE IF NOT EXISTS coin_narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'actief',  -- actief/tegengesproken/verlopen
    message_count INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL,
    last_update_at TEXT NOT NULL,
    closed_reason TEXT  -- NULL, of bv. "tegengesproken door narrative #<id>"
);
CREATE INDEX IF NOT EXISTS idx_coin_narratives_coin_status
    ON coin_narratives(coin, status);
```

Nieuwe kolom op een bestaande tabel (migratie nodig):

- `messages.narrative_id INTEGER REFERENCES coin_narratives(id)`, nullable.
  `ALTER TABLE messages ADD COLUMN narrative_id INTEGER REFERENCES
  coin_narratives(id)`, guarded door `PRAGMA table_info` in
  `db.py:_migrate()`, plus in `schema.sql`'s `CREATE TABLE IF NOT EXISTS
  messages` voor verse databases — zelfde tweeledige patroon als
  `signals.trade_type` eerder kreeg.

Nieuwe tabel voor de per-gebruiker Telegram-bericht-tracking (fan-out,
zelfde soort opzet als `journal_entries` dat voor signalen doet):

```sql
CREATE TABLE IF NOT EXISTS narrative_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id INTEGER NOT NULL REFERENCES coin_narratives(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    telegram_message_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE(narrative_id, user_id)
);
```

`UNIQUE(narrative_id, user_id)`: per gebruiker precies één "actuele
melding" per narrative. Een update doet `INSERT ... ON CONFLICT
(narrative_id, user_id) DO UPDATE` (bewerk het bestaande record met het
nieuwe `telegram_message_id`/`sent_at` zodra een edit niet meer kan en er
een verse melding is verstuurd).

## Zichtbaarheid op het dashboard

De coin-pagina vervangt de huidige losse "lange-termijn berichten"-lijst
door één kaart per narrative met status `actief` (en, ingeklapt, recent
`tegengesproken`/`verlopen` narratives eronder): richting, sinds wanneer,
aantal updates, en de updates zelf als tijdlijn erin. Zelfde soort kaart
als de bestaande "Bewaakt niveau"-sectie (`web/templates/coin.html`), geen
nieuw UI-patroon.

Op de bestaande prijsgrafiek (`web/static/coin.js`) komt per
narrative-update een klein, gekleurd puntje op het moment van dat bericht
(kleur = richting, zelfde kleurcode als de bestaande long/short-badges).
Geen nieuwe grafiek, geen extra as, alleen markeringen op de tijdlijn die
er al is.

## Foutafhandeling

- Een narrative-update die zelf geen `telegram_chat_id` heeft voor een
  gebruiker: geen melding voor die gebruiker, net als vandaag al het geval
  is voor elke Telegram-melding.
- Een edit die faalt (bijv. het bericht is inmiddels door de gebruiker zelf
  verwijderd, of een zeldzame Telegram-fout binnen de 48-uursgrens): val
  terug op een verse melding, dezelfde `try/except` stijl als de rest van
  `telegram_notify.py`.
- Twee narrative-updates die nagenoeg gelijktijdig binnenkomen voor
  dezelfde coin+richting (twee snel opeenvolgende berichten): de tweede
  ziet het net aangemaakte/bijgewerkte narrative van de eerste normaal via
  een gewone select-dan-update, geen race-conditie te voorkomen die niet al
  bestond voor `messages`-verwerking in het algemeen (berichten worden
  sequentieel verwerkt binnen één Discord-bot-proces).
- Een narrative dat "tegengesproken" of "verlopen" is, telt nooit meer mee
  als aansluitpunt voor een nieuw bericht: een nieuw bericht na een
  tegenspraak of na verval start altijd een gloednieuw narrative, nooit een
  heropening van het oude.

## Testen

- Pure matching-logica (welke van de drie takken — update/tegenspraak/nieuw
  — een nieuw bericht kiest) los te testen tegen een fixture-lijst van
  bestaande narratives, zonder I/O.
- Scratch-DB/TestClient scenario's:
  - Twee berichten, zelfde coin+richting, binnen 84 dagen → één narrative,
    `message_count = 2`, tweede Telegram-aanroep is een edit (gemockt: de
    `telegram_message_id` van de eerste melding wordt hergebruikt).
  - Twee berichten, zelfde coin, tegenovergestelde richting → twee
    narratives, de eerste op "tegengesproken", de tweede "actief", een
    aparte, niet-bewerkte tegenspraak-melding verstuurd.
  - Een narrative-update na de 48-uursgrens (gesimuleerd door
    `sent_at` terug te zetten) → verse melding in plaats van een edit,
    `narrative_notifications`-rij bijgewerkt met het nieuwe bericht-ID.
  - Een narrative zonder update in meer dan 84 dagen → status "verlopen"
    via `check_narratives()`.
  - Een dag-trading signaal op een coin met een actief, tegengesteld
    narrative → context_note benoemt de tegenspraak; het signaal zelf
    (confidence, technical_confirmed, SL/TP) blijft ongewijzigd.
  - Regressie: `_build_context_note`'s bestaande gedrag voor "geen lange
    termijn context" en "sluit aan bij lange termijn analyse" blijft
    werken, nu via narratives in plaats van
    `repo.latest_long_term_direction`.

## Openstaande aanname om te bevestigen bij implementatie

De exacte tekst/opmaak van de bewerkte Telegram-melding (hoeveel van de
tijdlijn wordt getoond bij bijvoorbeeld 10+ updates: alles, of alleen de
eerste en de laatste paar) wordt tijdens implementatie ingevuld naar het
patroon van de bestaande `format_signal_message`/`format_swing_message`,
niet apart in dit document uitgeschreven. De aanwezigheid van een
samenvattende tijdlijn staat niet ter discussie, de exacte lay-out wel.
