# Bewaakte niveaus voor lange-termijn signalen ("swing watches")

## Aanleiding

Op 5 september 2026 stuurde een gebruiker een bericht door over RAY: "RAY
onderweg voor een weekly double bottom. Laten we hopen dat deze door de
resistance komt", met een screenshot waarop een weerstand op 0.83614 was
ingetekend. De Anthropic-interpretatie classificeerde dit terecht als
`lange_termijn` (geen concrete kortetermijn-entry, weekly-patroon,
voorzichtige taal). RAY steeg daarna meer dan 20%.

Twee dingen gingen mis, geen van beide is een classificatiefout:

1. **Geen technische toetsing.** `signal_processor.handle_message` doet voor
   elke categorie behalve `day_trading` helemaal niets met technische data:
   geen candles, geen indicatoren, geen kansberekening, geen entry/SL/TP.
   Het bericht wordt alleen gelogd en er gaat een stille Telegram-melding
   uit (`send_long_term_message`, `disable_notification=True`).
2. **Het wél opgeslagen niveau werd nooit meer bekeken.** De weerstand van
   0.83614 stond keurig in `source_levels` (die tabel wordt gevuld voor
   *elk* bericht met een afbeelding, ongeacht categorie). Maar
   `level_check.check_pending_signals()`, de periodieke 15-minuten check die
   `source_levels` afzet tegen de live prijs, doet dat alleen voor coins die
   een `journal_entries`-regel hebben. Die regel bestaat alleen bij
   day trading. Het niveau was dus data zonder enige consument.

Dit document beschrijft hoe berichten met een concreet niveau, ongeacht
categorie, wel een echte, doorlopende toetsing krijgen.

## Doel

Elk bericht met een opgeslagen `source_level` (support/resistance/patroon
uit een screenshot) wordt bewaakt totdat de prijs er weer dichtbij komt. Op
dat moment draait een volledige technische toets (daily + 4-uur candles) en
krijgt de gebruiker een actiemelding met een niveau-gebaseerde stop
loss/take profit en positiegrootte, net als bij een day-trading signaal.

Dit geldt zowel voor `lange_termijn`-berichten (die nu niets krijgen) als
voor `day_trading`-berichten (die nu alleen op ATR rekenen, ook als de bron
zelf al een niveau intekende).

## Niet-doelen

- Geen vertrouwenspercentage voor swing-signalen. De bestaande 3-van-4
  factorentoets is gekalibreerd op 4-uur candles via
  `scripts/backtest_factors.py`; die kalibratie bestaat niet voor
  daily/weekly. Swing-meldingen tonen losse ✓/✗ factoren, geen gecombineerd
  cijfer, totdat er een aparte backtest voor deze tijdshorizon is.
- Geen tekst-only detectie van niveaus. De poort blijft simpel en objectief:
  heeft dit bericht een opgeslagen `source_level`, ja of nee. Geen AI-oordeel
  over "is dit concreet genoeg".
- Geen automatische conflictoplossing tussen tegenstrijdige watches op
  dezelfde coin (bijvoorbeeld twee leden die het oneens zijn). Beide blijven
  onafhankelijk lopen.

## Architectuur

De poort "heeft dit bericht een niveau" geldt voor **beide** categorieën,
niet alleen `lange_termijn`:

```
handle_message
├── interpretatie, samenvatting, source_levels opslaan (ongewijzigd)
├── voor elk opgeslagen source_level van dit bericht:
│     evaluate_level_watch(message_id, coin, direction, level)
│       → maakt een swing_watches-regel met status "wachtend"
│       → checkt direct of de prijs nu al dichtbij is; zo ja,
│         meteen door naar run_swing_check (zie hieronder)
└── categorie-vertakking (ongewijzigd: day_trading krijgt zijn bestaande
    4-uur toets, nu met niveau-gebaseerde SL/TP als er een niveau is;
    lange_termijn blijft verder alleen loggen + stille melding)
```

"Dichtbij" wordt overal in dit document gemeten met dezelfde soort
ATR-marge die `level_check.PENDING_LEVEL_ATR_MULTIPLIER` nu al gebruikt
voor day-trading pending-signalen (0.5x ATR), maar dan met de **daily**
ATR: dat is de tijdshorizon van de structurele check, en dus de
natuurlijke maatstaf voor "hoe dichtbij is dichtbij" op een niveau dat uit
een weekly/daily-analyse komt. "Krachtig door het niveau heen" (invalidatie)
gebruikt dezelfde marge: de prijs moet met meer dan die ATR-marge voorbij
het niveau gesloten hebben, in de verkeerde richting, niet zomaar er even
overheen tikken.

Periodiek, in dezelfde 15-minuten timer als `level_check.py` al gebruikt:

```
check_swing_watches()
  voor elke "wachtende" watch:
    prijs dichtbij? → run_swing_check(watch)
    anders, langer dan 8-12 weken oud? → status "vervallen"
    anders, prijs krachtig door het niveau heen in de verkeerde
      richting? → status "ongeldig"
```

`run_swing_check(watch)`:
1. Haal daily én 4-uur candles op, bereken indicatoren op allebei.
2. Bereken de factoren (EMA/MACD/RSI/volume) op beide tijdshorizons apart,
   toon ze gescheiden, geen combinatie tot één label.
3. Bereken stop loss/take profit via het niveau zelf (zie
   "Niveau-gebaseerde risicoberekening"), val terug op ATR als het niveau
   geen bruikbare stop oplevert.
4. Maak per gebruiker een `journal_entries`-regel aan (`trade_type =
   'swing'`), reken positiegrootte uit zoals nu al gebeurt.
5. Stuur een niet-stille Telegram-melding per gebruiker, met dezelfde
   Genomen/Negeren-knoppen als day trading al heeft.
6. Zet de watch op "bevestigd": hij wordt daarna nooit opnieuw getoetst,
   ook niet als de prijs er later nog een keer overheen gaat.

## Niveau-gebaseerde risicoberekening

Nieuw in `app/risk.py`: `compute_stop_take_from_levels(direction, price,
source_levels, atr, swing_low, swing_high)`.

- Welk niveau de stop is en welk het target, wordt bepaald door de **positie
  van het niveau ten opzichte van de huidige prijs en de richting**, nooit
  door de vrije `pattern_name`-tekst te matchen. Bij long: een niveau onder
  de prijs is de stop-basis, een niveau erboven is het target.
- **Ondergrens op de stop-afstand.** Ligt het niveau te dicht bij de huidige
  prijs (kleiner dan een minimumfractie van de ATR), dan is dat niveau geen
  bruikbare stop: val terug op de bestaande ATR-berekening. Dit voorkomt dat
  een toevallig dichtbij getekend niveau een absurd grote positiegrootte
  oplevert (risicobedrag gedeeld door een piepklein verschil).
- **Geen tweede niveau voor een target?** Take profit op 2x de
  stop-afstand, dezelfde soort vaste verhouding als de bestaande 1.5x/3x
  ATR-logica.
- Retourneert `None` voor stop of target als er geen bruikbaar niveau is;
  de caller valt dan terug op `risk.compute_stop_take` zoals vandaag.

Dit geldt zowel voor day trading (nieuw: gebruikt het niveau als het er is,
anders ATR zoals nu) als voor swing.

## Datamodel

Nieuwe tabel `swing_watches` (geen migratie nodig, want nieuwe tabel):

```sql
CREATE TABLE IF NOT EXISTS swing_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    source_level_id INTEGER NOT NULL REFERENCES source_levels(id),
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'wachtend',  -- wachtend/bevestigd/vervallen/ongeldig
    created_at TEXT NOT NULL,
    checked_at TEXT
);
```

Gewijzigde tabellen (migratie nodig, bestaande tabellen):

- `signals`: kolom `trade_type TEXT NOT NULL DEFAULT 'day_trading'`
  (`'day_trading'` of `'swing'`). Bestaat de kolom nog niet op een bestaande
  database: `ALTER TABLE signals ADD COLUMN trade_type TEXT NOT NULL
  DEFAULT 'day_trading'`, guarded door `PRAGMA table_info` in
  `db.py:_migrate()`, plus `CREATE TABLE IF NOT EXISTS` met de kolom erin
  voor verse databases, precies volgens het bestaande patroon in
  CLAUDE.md.

Winrate, journaal-secties en de risicowaarschuwing filteren voortaan
expliciet op `trade_type` waar dat hoort:

- `winrate_stats`: aparte resultaten voor `day_trading` en `swing`, niet
  samengevoegd. Swing-winrate begint bij 0 trades en groeit organisch, dat
  is prima; er wordt geen vertrouwenslabel op geplakt zolang dat aantal
  klein is.
- Open-posities-telling en het totale risicopercentage
  (`_compute_tension`, de risicogauge) blijven **beide** trade_types
  meetellen: dat gaat over totale blootstelling van je portfolio, niet over
  type analyse. Expliciet checken dat geen enkele bestaande query per
  ongeluk op `category = 'day_trading'` filtert en swing-rijen zo stilzwijgend
  buiten de telling houdt.
- Correlatiewaarschuwing (meerdere open posities dezelfde richting) telt
  ook beide typen mee: het gaat om richting-risico op portfolioniveau, niet
  om het soort signaal.
- Mute-per-coin geldt alleen voor `day_trading`-meldingen op die coin. Een
  swing-melding blijft altijd doorkomen, ook op een gemute coin: dat zijn
  juist de zeldzame, grote kansen waar mute niet voor bedoeld is.

## Zichtbaarheid op het dashboard

De coin-pagina toont een nieuwe sectie "Bewaakt niveau" zodra er een
`swing_watches`-regel met status "wachtend" bestaat voor die coin: het
niveau, de richting, en sinds wanneer. Zo blijft dit geen onzichtbare
achterkant-status zoals het lange-termijn-mechanisme dat nu is.

## Backfill

Eenmalig script (naar het patroon van
`scripts/regenerate_message_summaries.py`): loopt alle `source_levels` van
de laatste paar weken langs waar nog geen `swing_watches`-regel voor
bestaat, en maakt die alsnog aan met status "wachtend" (nooit direct
"bevestigd", ook niet als de prijs toevallig al dichtbij staat op het
moment van draaien: de eerstvolgende periodieke check pakt dat vanzelf op).
Berichten ouder dan de verval-periode (8-12 weken) worden overgeslagen, die
zijn toch al niet meer relevant.

## Foutafhandeling

- Ontbrekende live data (candles, prijs): de betreffende factor telt als
  niet-bevestigd, geen crash, geen vals-positieve melding op onvolledige
  data. Zelfde patroon als de bestaande advanced factors in
  `compute_advanced_extra_factors`.
- Te weinig daily-geschiedenis voor een indicator (net gelanceerde coin):
  die ene factor telt als niet-bevestigd, de rest gaat door.
  Coin bestaat niet (meer) op de exchange: geen watch aanmaken, wel dezelfde
  "niet-ondersteund"-melding als day trading nu al stuurt bij een
  onbekende coin.
- Meerdere niveaus in één bericht: elk niveau krijgt zijn eigen
  `swing_watches`-regel.
- Een "bevestigde" watch wordt nooit opnieuw getoetst, ook niet als de
  prijs er later nogmaals overheen gaat: eenmalige melding per watch,
  zelfde soort eenmalig-vlag als `level_alert_sent`.

## Testen

- Pure functies (`_nearest_level`-achtige helpers, de niveau-naar-stop/target
  toewijzing, de ondergrens-check) los te unittesten zonder I/O, zelfde
  stijl als de bestaande functies in `level_check.py`.
- Scratch-DB/TestClient scenario's:
  - Bericht met niveau dichtbij de live prijs → meteen een bevestigde watch
    en een journaalregel (directe check bij binnenkomst).
  - Bericht met niveau ver van de live prijs → watch blijft "wachtend",
    wordt pas bevestigd zodra een latere `check_swing_watches()`-aanroep
    met een dichterbij gelegen prijs draait.
  - Niveau te dicht bij de prijs voor een zinnige stop → valt terug op ATR,
    geen absurde positiegrootte.
  - Watch ouder dan de verval-periode zonder ooit dichtbij te zijn gekomen
    → status "vervallen".
  - Prijs breekt krachtig door het niveau in de verkeerde richting →
    status "ongeldig".
  - Gemute coin: swing-melding gaat alsnog door, day-trading meldingen
    niet.
  - Backfill-script op een fixture-database met oude en verse
    lange-termijn-berichten.

## Openstaande aanname om expliciet te bevestigen bij implementatie

De exacte waarde van de ondergrens op de stop-afstand (bijvoorbeeld: nooit
kleiner dan 0.5x de ATR van de gebruikte tijdshorizon) wordt pas
vastgesteld tijdens implementatie, op basis van wat een aantal echte
coins/niveaus uit de bestaande `source_levels`-tabel opleveren. Dit getal
zelf staat niet ter discussie in dit ontwerp, de aanwezigheid van een
ondergrens wel.
