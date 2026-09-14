# Autonome marktscan — design

## Aanleiding

HesPulse reageert nu uitsluitend op een Discord-bericht dat de gebruiker
zelf doorstuurt (`app/signal_processor.py:handle_message`). Zonder
doorgestuurd bericht gebeurt er niets: geen technische toets, geen
Telegram-melding, ook al zou de technische data op dat moment allang een
kans laten zien. De product owner wil dat het systeem zelf, continu, de
markt in de gaten houdt en zelf kansen signaleert, niet alleen als reactie
op een community-post.

## Scope

Coins: dezelfde dynamische lijst als nu al bijgehouden wordt
(`repo.list_coins()`, gevuld via `coinlist.ensure_coin_tracked` zodra een
coin ooit in een doorgestuurd bericht voorkwam). Geen aparte, vaste lijst.

Scanfrequentie: elk uur. Niet elke 4 uur (de underlying candle-timeframe):
de laatste 4u-candle is bij Binance nog "in wording" totdat hij sluit, dus
tussentijds checken vangt een beweging (RSI/volume/EMA's die richting de
kant van bevestiging bewegen terwijl de candle vult) eerder op dan wachten
tot de candle daadwerkelijk sluit. Zelfde soort redenering als
`level_check.py`, die ook vaker draait (15 min) dan de candle zelf.

Richting: de scan bepaalt zelf long of short via de bestaande trendregel
(EMA9 boven EMA21 → long-kandidaat, EMA9 onder EMA21 → short-kandidaat),
dezelfde regel die nu al de trend-basisfactor is in
`indicators.basic_factors`.

Meldingsdrempel: dezelfde drempel als een community-bericht, minstens 3
van de 4 basisfactoren (`indicators.confirms_direction`, ongewijzigd).
Trend telt bij een autonoom signaal weliswaar per constructie altijd als
✓ (de richting is er juist op gekozen), maar de product owner koos expliciet
voor "meer kansen vinden" boven een striktere eis — dus geen aparte,
strengere drempel voor dit pad. Alleen bij een bevestigde kans (hoog
vertrouwen) gaat er een Telegram-melding uit; een afwijzing wordt niet
gemeld (in tegenstelling tot een community-bericht, waar elke tip altijd
een bericht krijgt — bij tientallen coins elk uur zou dat een spervuur aan
ruis worden zonder dat een community-signaal daar aanleiding toe gaf).

## Architectuur

Geen tweede, parallelle implementatie van de toetsings- en fan-out-logica.
De scan hergebruikt `signal_processor.process_day_trading_signal()`
ongewijzigd in zijn kernlogica: die functie doet nu al de technische
toets, de stop/take-berekening, de dedup tegen een al open signaal, de
mute-check, de risicoberekening per gebruiker, het aanmaken van
journal-regels en het versturen van Telegram-berichten — precies wat een
autonoom signaal ook nodig heeft.

Nieuw bestand `app/market_scanner.py` met één functie `scan_market()`:
voor elke coin in `repo.list_coins()`, na elkaar (niet gelijktijdig, om
Binance niet te overvragen — zelfde patroon als `level_check.py`):

1. `df = exchange.fetch_ohlcv(coin)`
2. `ind = indicators.compute_indicators(df)`
3. richting bepalen: `"long" if ind.ema9 > ind.ema21 else "short"`
4. een synthetische `Interpretation(coin=coin, direction=richting,
   category="day_trading", unclear=False, reason="")` bouwen
5. `await process_day_trading_signal(message_id=None, interp)`

Een fout bij één coin (bijvoorbeeld een tijdelijke Binance-storing) mag de
rest van de scan niet blokkeren: elke coin in een eigen try/except, loggen
en doorgaan naar de volgende coin.

Nieuwe systemd-timer `deploy/crypto-market-scan.timer` +
`.service`, elk uur (`OnCalendar=hourly`), zelfde vorm als
`crypto-level-check.timer`.

## Wijzigingen aan bestaande code

**`app/signal_processor.py`**

- `process_day_trading_signal(message_id: int, interp: Interpretation)`
  wordt `process_day_trading_signal(message_id: int | None, interp:
  Interpretation)`.
- De twee plekken die `message_id` gebruiken om iets over het BRONbericht
  op te zoeken worden overgeslagen als `message_id is None`:
  - `repo.mark_message_untracked(message_id, interp.coin)` (bij een
    niet-bestaande coin) — kan niet voorkomen voor de scan, die haalt zijn
    coins al uit de bestaande, gevalideerde lijst, maar de guard blijft
    voor de duidelijkheid.
  - `message_levels = [lvl["price_level"] for lvl in
    repo.list_source_levels_for_message(message_id, interp.coin)]` wordt
    een lege lijst als `message_id is None` (geen bericht, dus geen
    bron-niveaus — de SR-zone-niveaus uit `detect_sr_zones` blijven wel
    gewoon meetellen, die komen niet uit een bericht).
- Nieuwe parameter `notify_on_update: bool = True` op
  `process_day_trading_signal`. Bij `existing` (een al open signaal wordt
  bijgewerkt in plaats van nieuw aangemaakt): `repo.update_signal(...)`
  gebeurt altijd, maar `_notify_signal_update(...)` alleen als
  `notify_on_update` True is. De scan roept aan met
  `notify_on_update=False`: een coin die al eerder door de scan zelf
  gemeld is en nog steeds klopt, wordt in de database ververst (nieuwe
  prijs/indicatoren, zichtbaar op dashboard) maar stuurt geen nieuwe
  Telegram-melding elk uur. Een community-bericht blijft ongewijzigd
  `notify_on_update=True` (default): een mens die opnieuw post over
  dezelfde coin/richting verdient wel een verse melding.
  Let op: dit is onafhankelijk van `message_id is None` — een door de scan
  ontdekt signaal dat een gebruiker nog moet nemen, en waar vervolgens
  een COMMUNITY-bericht over dezelfde coin/richting binnenkomt, mag wél
  gewoon een update-melding geven (de mens koos bewust om te posten). De
  `notify_on_update`-vlag wordt dus door de AANROEPER bepaald (scan vs.
  `handle_message`), niet afgeleid van `message_id`.

**`app/market_scanner.py`** (nieuw) — zie architectuur hierboven.

**`app/schema.sql`**

- `signals.message_id INTEGER NOT NULL REFERENCES messages(id)` wordt
  `signals.message_id INTEGER REFERENCES messages(id)` (nullable).
  Migratie in `db.py:_migrate()`: SQLite staat geen `ALTER COLUMN` toe om
  een NOT NULL-constraint te verwijderen; de gebruikelijke aanpak (nieuwe
  tabel met het gewenste schema, data overzetten, oude tabel droppen, hernoemen)
  gebeurt alleen als de bestaande `signals`-tabel nog de NOT NULL-constraint
  heeft (te herkennen via `PRAGMA table_info` / `sql` uit
  `sqlite_master`), idempotent, zodat een tweede keer opstarten een no-op is.

**`app/repo.py`**

- `list_recent_signals(coin, limit)`: `JOIN messages m ON m.id =
  s.message_id` wordt `LEFT JOIN`. `message_summary` valt terug op
  `COALESCE(mcr.message_summary, m.message_summary, 'Zelf gedetecteerd
  door HesPulse')`.
- `_JOURNAL_SELECT`: dezelfde wijziging, `JOIN messages m ON m.id =
  s.message_id` → `LEFT JOIN`, dezelfde COALESCE-fallback op
  `message_summary`.
- Elke andere plek die `signals.message_id` gebruikt (zoek op
  `s.message_id` in repo.py) nalopen op dezelfde aanname.

**`app/telegram_notify.py`**

- `format_signal_message(signal)`: één regel toegevoegd direct na de
  vertrouwen-header, alleen als `signal.get("message_id") is None`:
  `"🔎 Zelf gedetecteerd door HesPulse"`. Dit is het zichtbare bewijs dat
  de product owner vroeg: duidelijk onderscheid tussen een melding die uit
  een doorgestuurd bericht kwam en een die het systeem zelf vond.
- `signal_data` (gebouwd in `process_day_trading_signal`) bevat al
  `"message_id": message_id`, dus deze sleutel is al aanwezig, geen extra
  veld nodig.

**Web (dashboard/coin-pagina)**

- Overal waar een signaal/journal-regel getoond wordt (dashboard,
  coin-pagina): een klein label "Zelf gedetecteerd" naast de bestaande
  vertrouwen-badge, zichtbaar wanneer `entry.message_id` leeg is. Exacte
  plek: naast de SHORT/LONG-badge in `_macros.html`'s `open_trade_body`
  (zelfde macro als bij de topbar-pill eerder deze sessie, geen nieuwe
  macro nodig).

## Wat NIET verandert

- `message_coin_results`, `source_levels` en `swing_watches` blijven
  `message_id NOT NULL`: die tabellen horen puur bij de
  bericht-interpretatie-pijplijn (multi-coin-berichten, bron-niveaus,
  swing-bewaking) en worden door de autonome scan niet aangeraakt. Alleen
  `signals.message_id` wordt nullable.
- `confirms_direction` en `basic_factors` in `app/indicators.py` blijven
  ongewijzigd: dezelfde 3-van-4-drempel, geen aparte striktere variant.
- Per-gebruiker aan/uit-instelling komt er niet: de scan is systeembreed
  aan voor alle gebruikers, zoals `ENABLE_ADVANCED_FACTORS` dat ook is.
- Muted coins: al opgelost, `process_day_trading_signal`'s bestaande
  fan-out checkt `repo.is_coin_muted(user_id, coin)` per gebruiker vóór
  het versturen van een Telegram-bericht, ongeacht of het signaal uit een
  bericht of uit de scan komt.

## Uitbreidingen (op verzoek van de product owner, allemaal meenemen)

### 1. Noodrem op het dashboard

Eén systeembrede vlag in de bestaande `settings`-tabel (`app/db.py`'s
`get_setting`/`set_setting`, sleutel/waarde, geen migratie nodig). Nieuwe
knop op het dashboard (bij de bestaande instellingen-sectie) die
`market_scan_enabled` op `"0"`/`"1"` zet via een kleine AJAX-route in
`web/main.py`, zelfde patroon als "Instellingen opslaan zonder
paginaherlaad" (task #95). `market_scanner.scan_market()` checkt deze
vlag als eerste regel (`repo` krijgt een dunne `is_market_scan_enabled()`
wrapper om `get_setting`) en stopt meteen als hij uit staat — geen coins
worden dan aangeraakt, geen Binance-calls. Standaard aan
(`get_setting("market_scan_enabled", default="1")`).

### 2. Weekoverzicht in de bestaande periodieke samenvatting

`app/periodic_summary.py` krijgt een extra regel in de wekelijkse
samenvatting (niet de maandelijkse, die is bewust beknopter): hoeveel
signalen de autonome scan die week zelf vond (`message_id IS NULL`),
hoeveel daarvan door de gebruiker genomen zijn, en de winrate daarvan.
Nieuwe repo-functie `period_stats_auto_scan(user_id, since_iso)` naast de
bestaande `period_stats`, met dezelfde WHERE-structuur maar gefilterd op
`s.message_id IS NULL`. Alleen toegevoegd aan het bericht als er
minstens één autonoom signaal was die week (anders een lege regel die
niks toevoegt).

### 3. Rem bij een zijwaartse BTC-markt

Nieuwe functie `indicators.btc_is_flat(btc_ind: Indicators) -> bool`:
`abs(btc_ind.ema9 - btc_ind.ema21) < BTC_FLAT_EMA_GAP_ATR_MULTIPLE *
btc_ind.atr` (nieuwe constante, aanbevolen startwaarde 0.3 — een kwart
tot derde van de ATR is een gangbare "geen duidelijke richting"-marge,
zelfde soort ATR-genormaliseerde aanpak als de bestaande
`SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE`). `market_scanner.scan_market()`
haalt BTC's eigen candles en indicatoren ÉÉN keer op aan het begin van de
cyclus (niet per coin) en slaat, als `btc_is_flat` True is, alle
ALTCOIN-signalering deze cyclus over (BTC zelf blijft gewoon meedoen, die
kan niet circulair van zijn eigen trend afhangen). Gelogd, niet gemeld:
dit is een stille marktconditie, geen gebeurtenis om een Telegram-bericht
over te sturen.

### 4. Cooldown na een verlies

Nieuwe repo-functie `recent_autonomous_loss(coin, direction, hours) ->
bool`: True als de laatst GESLOTEN journal-regel op een autonoom signaal
(`s.message_id IS NULL`) voor deze coin+richting binnen `hours` uur
geleden een verlies was (`result_eur < 0`). Nieuwe constante
`AUTO_SCAN_LOSS_COOLDOWN_HOURS` (aanbevolen 12 — twaalf van de vierentwintig
scan-cycli per dag overslaan na een verlies is een reële afkoelperiode
zonder een kans dagenlang te blokkeren). `market_scanner.scan_market()`
checkt dit vóór het aanroepen van `process_day_trading_signal` en slaat de
coin+richting over als de cooldown nog loopt, net als de BTC-flat-check
stil gelogd, geen Telegram-bericht (er gebeurt niets, dus niets te
melden).

### 5. Waarschuwing bij herhaald verlies (in plaats van afzwakken)

Zoals in de pitch aangegeven: signalen niet stilzwijgend onderdrukken op
basis van een verlies-patroon, dat past niet bij "elke trade is een
handmatige beslissing" (CLAUDE.md) en de bestaande regel dat de
gemeten/geschatte scheiding altijd zichtbaar blijft. In plaats daarvan:
een zichtbare waarschuwing, zelfde stijl als de bestaande
`repeated_factor`-regel in `format_rejected_message` maar dan voor een
BEVESTIGDE autonome kans. Nieuwe repo-functie
`consecutive_autonomous_losses(coin, direction, limit=3) -> int`: hoeveel
van de laatste `limit` gesloten autonome journal-regels voor deze
coin+richting op rij een verlies waren (0 zodra de nieuwste een winst is).
In `process_day_trading_signal`, alleen als `message_id is None`:
`signal_data["repeated_loss_note"]` gezet als dit aantal ≥ 3. Nieuwe regel
in `telegram_notify.format_signal_message`, na de bestaande
`context_note`-regel: "📉 Dit zelf-gedetecteerde patroon verloor de
laatste {n} keer op rij bij {coin}. Blijft een geldige kans, weeg dit wel
mee." Puur informatief, het signaal wordt gewoon aangemaakt en gemeld
zoals altijd.

### 6. Sterkte-ranking bij meerdere gelijktijdige kansen

`market_scanner.scan_market()` verzamelt de coin/richting/aantal-
bevestigde-factoren van elke NIEUWE (niet: bijgewerkte) autonome kans
die in deze ene cyclus ontstaat. Na afloop van de hele cyclus, alleen als
dat er 2 of meer zijn: één extra Telegram-bericht per gebruiker (niet per
signaal, dat gebeurde al) met de kansen gerangschikt van sterkste naar
zwakste (aantal bevestigde basisfactoren, bij gelijke stand de
`ENABLE_ADVANCED_FACTORS`-score als tiebreaker indien beschikbaar). Nieuwe
functie `telegram_notify.send_scan_cycle_summary(ranked, chat_id)`. Dit
is een AANVULLING op de bestaande "meerdere gelijktijdige kansen"-regel
in elk los bericht (task #111, die blijft ongewijzigd), niet een
vervanging.

## Testen

Scratch-DB/TestClient-tests, zelfde patroon als de rest van deze
sessie:

1. `market_scanner.scan_market()` tegen gemockte `exchange.fetch_ohlcv`
   (twee coins: één met EMA9 > EMA21 en genoeg bevestigende factoren →
   verwacht een nieuw signaal met `message_id IS NULL`; één zonder
   bevestiging → geen signaal, geen Telegram-aanroep).
2. Een coin die al een open, bevestigd autonoom signaal heeft: een tweede
   scan-cyclus moet `repo.update_signal` aanroepen maar NIET
   `telegram_notify.send_signal`/`send_signal_update` (mock en assert
   `not called`).
3. Dezelfde coin/richting al open via een ECHT community-bericht
   (`message_id` niet None): de scan mag dit signaal bijwerken zonder een
   dubbel signaal aan te maken (bestaande `find_open_signal`-dedup, nu
   getest met een scan-aanroep als trigger in plaats van een bericht).
4. `repo.list_recent_signals`/`_JOURNAL_SELECT` met een signaal zonder
   `message_id`: `message_summary` moet de fallbacktekst geven, geen
   crash op de LEFT JOIN.
5. `format_signal_message` met `message_id=None` bevat de "Zelf
   gedetecteerd"-regel; met een gezette `message_id` niet.
6. Handmatige Playwright-verificatie: dashboard/coin-pagina tonen het
   "Zelf gedetecteerd"-label correct bij een scan-signaal en niet bij een
   community-signaal.
7. Volledige regressie van de bestaande signal_processor-tests (dedup,
   mute, evaluatie-risico, stopcap) blijft ongewijzigd slagen met
   `message_id=None` als extra testcase naast de bestaande
   `message_id`-gevallen.
8. `market_scan_enabled` op `"0"`: `scan_market()` doet aantoonbaar niets
   (geen `exchange.fetch_ohlcv`-aanroep, mock met `assert not called`).
9. `period_stats_auto_scan`: scratch-DB met een gemengde week (één
   community-signaal, twee autonome signalen waarvan één gesloten met
   winst) → alleen de autonome twee tellen mee, het community-signaal
   niet.
10. `btc_is_flat`: unit-test met een synthetische `Indicators` net binnen
    en net buiten de drempel. Integratie: BTC vlak → geen enkel
    altcoin-signaal die cyclus, ondanks een altcoin die zelf ruim aan de
    3-van-4-eis voldoet.
11. `recent_autonomous_loss`: scratch-DB met een net gesloten verlies
    binnen `AUTO_SCAN_LOSS_COOLDOWN_HOURS` → coin+richting wordt die
    cyclus overgeslagen. Buiten de cooldown-periode (oudere `exit_time`)
    → gewoon weer meegenomen.
12. `consecutive_autonomous_losses`: drie verliezen op rij → aanwezige
    `repeated_loss_note` in `signal_data` en in de Telegram-tekst. Een
    winst ertussen → geen waarschuwing, ondanks eerdere verliezen.
13. Ranking-bericht: scratch-DB-scan met drie kwalificerende coins in
    dezelfde cyclus, verschillend aantal bevestigde factoren →
    `send_scan_cycle_summary` één keer per gebruiker aangeroepen, in de
    juiste volgorde. Met maar één kwalificerende coin: geen extra
    bericht (`send_scan_cycle_summary` niet aangeroepen).
