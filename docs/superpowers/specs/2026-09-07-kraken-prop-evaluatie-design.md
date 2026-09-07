# Kraken Prop evaluatie simulator — ontwerp

## Aanleiding

Kraken Pro biedt sinds mei 2026 Kraken Prop aan: een evaluatie kopen, een
virtueel saldo (5000 tot 200000 dollar) krijgen, en bij het halen van een
winstdoel zonder een dagverlies- of drawdownlimiet te breken een echt
gefinancierd account krijgen. De evaluatie kost geld en is eenmalig: faal je,
dan ben je die betaling kwijt.

De gebruiker wil eerst virtueel kunnen testen of zijn eigen discipline en
HesPulse's signalen een evaluatie zouden overleven, voordat hij er echt geld
aan uitgeeft. Dit ontwerp voegt die simulatie toe aan HesPulse, bovenop de
al bestaande oefentrade-functie.

## Niet-doelen

- Geen koppeling met een echt Kraken-account. Dit is een simulatie op
  HesPulse's eigen data, niets stroomt naar of van Kraken.
- Geen automatische koppeling aan Discord-signalen. Een evaluatie run
  gebruikt dezelfde handmatige coin+richting-keuze als de bestaande
  oefentrades op de coin-pagina (bevestigd met de gebruiker).
- Geen meerdere gelijktijdige runs per gebruiker. Eén actieve run tegelijk
  (bevestigd met de gebruiker); een nieuwe run starten kan pas nadat de
  vorige geslaagd, mislukt, of handmatig gestopt is.
- Geen wijziging aan `risk.py`'s echte positiegrootte-berekening, aan
  `portfolio_eur`, aan `risk_percent`, of aan de echte winrate-statistieken.
  Een evaluatie run is een volledig aparte, virtuele boekhouding die
  meelift op bestaande oefentrades zonder de bestaande
  oefentrade-garantie (nooit invloed op portfolio of winrate) te
  doorbreken.
- Geen backfill: bestaande oefentrades van vóór deze feature worden nooit
  met terugwerkende kracht aan een evaluatie gekoppeld.

## Bevestigde Kraken-regels die dit ontwerp namaakt

- Maximaal dagverlies: 3% van het saldo bij het begin van de handelsdag,
  elke dag opnieuw berekend, reset dagelijks om 00:30 UTC.
- Maximale drawdown: verlies vanaf het startbedrag van de evaluatie, over
  de hele looptijd, reset nooit.
- Winstdoel: een percentage van het startbedrag; bij het halen daarvan is
  de evaluatie geslaagd.
- Geen tijdslimiet, geen regel over hoeveel dagen je moet handelen.

Het exacte winstdoel-percentage en het exacte drawdown-percentage per
Kraken-tier kon tijdens dit ontwerp niet met zekerheid achterhaald worden
(niet publiek doorzoekbaar buiten het aankoopscherm in Kraken Pro zelf).
Daarom zijn dit in de simulatie twee door de gebruiker zelf ingestelde
percentages bij het starten van een run, in plaats van vaste, per-tier
ingebakken waarden. Het dagverlies-percentage (3%) is wel bevestigd en
ligt in de simulatie vast op 3%, met de waarde als kolom opgeslagen zodat
een toekomstige wijziging geen codewijziging vereist.

De zes bedragen (5000 / 10000 / 25000 / 50000 / 100000 / 200000) zijn in de
simulatie gewoon getallen in HesPulse's eigen valuta-eenheid (dezelfde
eenheid als `portfolio_eur`), niet een letterlijke dollar-naar-euro
omrekening. Het gaat om het mechanisme testen, niet om een exacte
valuta-simulatie.

## Datamodel

### Nieuwe tabel `prop_evaluations`

| kolom | type | omschrijving |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER NOT NULL REFERENCES users(id) | |
| tier_amount | REAL NOT NULL | startbedrag, bijv. 10000 |
| profit_target_pct | REAL NOT NULL | door gebruiker gekozen bij start |
| max_daily_loss_pct | REAL NOT NULL DEFAULT 3.0 | vast, opgeslagen voor traceerbaarheid |
| max_drawdown_pct | REAL NOT NULL | door gebruiker gekozen bij start |
| current_balance | REAL NOT NULL | virtueel saldo, begint op tier_amount |
| day_start_balance | REAL NOT NULL | saldo bij begin van de huidige handelsdag |
| day_start_date | TEXT NOT NULL | handelsdag-label (YYYY-MM-DD, UTC, zie hieronder) waar day_start_balance bij hoort |
| status | TEXT NOT NULL DEFAULT 'actief' | 'actief' / 'geslaagd' / 'mislukt' / 'gestopt' |
| closed_reason | TEXT | reden bij afsluiten, null zolang actief |
| started_at | TEXT NOT NULL | |
| ended_at | TEXT | null zolang actief |

Eén rij per run. Geschiedenis blijft staan (geen verwijdering), zodat de
gebruiker eerdere pogingen kan terugzien.

### Nieuwe kolom `journal_entries.evaluation_id`

`INTEGER REFERENCES prop_evaluations(id)`, nullable. Gezet op het moment
dat een oefentrade wordt aangemaakt terwijl de gebruiker een actieve
evaluatie run heeft (zie hieronder); blijft `NULL` voor elke trade die geen
actieve run trof op het moment van aanmaken, en voor alle niet-oefentrades.

Schema-wijziging is tweedelig, zoals de rest van het project: de nieuwe
tabel via `CREATE TABLE IF NOT EXISTS` in `schema.sql`, de nieuwe kolom op
de bestaande `journal_entries`-tabel via schema.sql (fresh database) plus
een idempotente `ALTER TABLE ... ADD COLUMN` met `PRAGMA table_info`-guard
in `db.py:_migrate()` (bestaande database). De index op
`journal_entries.evaluation_id` hoort, net als bij `messages.narrative_id`
eerder, in `_migrate()` zelf, ná de kolom-ALTER, nooit in schema.sql.

## Handelsdag-grens

Kraken reset de dagverlieslimiet om 00:30 UTC. De simulatie gebruikt
dezelfde grens: het handelsdag-label voor een tijdstip `t` (UTC) is de
kalenderdatum van `t`, tenzij `t`'s tijd vóór 00:30 UTC valt, in welk geval
het label de vorige kalenderdag is. Deze regel wordt op precies één plek
geïmplementeerd (zie `risk.py` hieronder) en nergens gedupliceerd.

## Wanneer wordt een trade aan een run gekoppeld

Bij het aanmaken van een nieuwe oefentrade (bestaande route
`POST /coins/{symbol}/oefen`): als de gebruiker op dat moment een actieve
evaluatie run heeft (`repo.get_active_evaluation(user_id)` is niet `None`),
krijgt de nieuwe `journal_entries`-rij `evaluation_id` gezet op die run.
Geen aparte keuze voor de gebruiker: elke oefentrade tijdens een actieve
run telt automatisch mee, precies zoals in het oorspronkelijke idee
afgesproken. De coin-pagina toont een korte notitie bij het oefentrade-
formulier als er een actieve run is, zodat dit niet verrassend is.

## Wat er gebeurt bij het sluiten van een gekoppelde trade

Bestaande route (waar `repo.close_journal_trade` al wordt aangeroepen)
krijgt na die aanroep een extra stap: als de gesloten entry een
`evaluation_id` had én die run nog `status = 'actief'` is, wordt het
resultaat verwerkt.

`repo.close_journal_trade` geeft voortaan een 3-tuple terug in plaats van
een 2-tuple: `(result_eur, is_practice, evaluation_id)`, waarbij
`evaluation_id` de waarde van de gesloten entry is (kan `None` zijn). Dit
is de enige wijziging aan die functie's interface; de bestaande twee
waarden en hun betekenis blijven ongewijzigd.

Nieuwe pure functie `risk.evaluate_prop_progress(evaluation: dict,
result_eur: float, closed_at: datetime) -> dict` (geen database-toegang,
puur berekenen, makkelijk te testen met losse scenario's):

1. Bepaal het handelsdag-label van `closed_at` volgens de regel hierboven.
2. Is dat label anders dan `evaluation["day_start_date"]`: reset
   `day_start_balance` naar `evaluation["current_balance"]` (het saldo
   vóór dit resultaat) en zet `day_start_date` op het nieuwe label.
3. Nieuw saldo: `current_balance = evaluation["current_balance"] +
   result_eur` (of de gereset `day_start_balance + result_eur` als stap 2
   net een reset deed — het saldo zelf verandert niet door een dagreset,
   alleen het referentiepunt voor de dagverlieslimiet).
4. Check in deze volgorde, eerste treffer wint:
   - Drawdown: is `current_balance <= tier_amount * (1 -
     max_drawdown_pct / 100)`? Dan `status = 'mislukt'`,
     `closed_reason = "maximale drawdown geraakt"`.
   - Dagverlies: is `current_balance <= day_start_balance * (1 -
     max_daily_loss_pct / 100)`? Dan `status = 'mislukt'`,
     `closed_reason = "maximaal dagverlies geraakt"`.
   - Winstdoel: is `current_balance >= tier_amount * (1 +
     profit_target_pct / 100)`? Dan `status = 'geslaagd'`,
     `closed_reason = "winstdoel gehaald"`.
   - Anders: `status = 'actief'`, `closed_reason = None`.
5. Geef de nieuwe waarden terug: `current_balance`, `day_start_balance`,
   `day_start_date`, `status`, `closed_reason`.

De aanroepende route persisteert het resultaat: altijd
`repo.update_evaluation_state(...)` met de nieuwe saldo/dag-velden, en als
`status` niet meer `'actief'` is, aanvullend `repo.close_evaluation(...)`.

Een trade die sluit terwijl zijn gekoppelde run inmiddels al
`'geslaagd'`/`'mislukt'`/`'gestopt'` is (bijvoorbeeld: twee trades tegelijk
open, de ene sluit en breekt de drawdownlimiet, de andere sluit daarna
pas) wordt normaal als oefentrade afgesloten; het resultaat telt niet meer
mee op de al afgesloten run. Een gesloten run is bevroren.

## Repo-functies (CRUD, `app/repo.py`)

- `create_evaluation(user_id, tier_amount, profit_target_pct,
  max_drawdown_pct) -> int`
- `get_active_evaluation(user_id) -> Optional[dict]`
- `get_evaluation(evaluation_id) -> Optional[dict]`
- `list_evaluations_for_user(user_id) -> list[dict]` (nieuwste eerst)
- `update_evaluation_state(evaluation_id, current_balance,
  day_start_balance, day_start_date) -> None`
- `close_evaluation(evaluation_id, status, closed_reason) -> None`

De bestaande oefentrade-aanmaakfunctie krijgt `evaluation_id` als extra,
optioneel veld (net als de andere kolommen in dat generieke insert-pad),
geen nieuwe aparte functie nodig.

## Webroutes en UI (`web/main.py`, templates)

- `POST /evaluatie/start`: form met `tier_amount` (dropdown met de zes
  bedragen), `profit_target_pct`, `max_drawdown_pct`. Weigert als de
  gebruiker al een actieve run heeft (dubbele start via twee tabbladen
  tegelijk).
- `POST /evaluatie/stop`: handmatig stoppen van de actieve run zonder
  slagen of falen (`status = 'gestopt'`), voor als de gebruiker wil
  opnieuw beginnen zonder op een limiet te wachten.
- Dashboard-route krijgt `active_evaluation =
  repo.get_active_evaluation(user_id)` en `evaluation_history =
  repo.list_evaluations_for_user(user_id)` in de context.
- Dashboard-sectie "Evaluatie simulatie", zelfde kaart-stijl als de
  risicogauge: als er geen actieve run is, het startformulier; als er wel
  een actieve run is, een statuskaart met tier, dag-nummer (dagen sinds
  `started_at`), huidig saldo, resterende ruimte tot dagverlieslimiet,
  resterende ruimte tot max drawdown, voortgang naar winstdoel (als
  percentage-balk), en een stopknop.
- Geschiedenis: een `<details>`-accordion onder de statuskaart, zelfde
  patroon als "Lopend verhaal"/"Bewaakt niveau", met per afgeronde run:
  tier, resultaat (geslaagd/mislukt/gestopt), gestart/geëindigd, reden.
- Coin-pagina's oefentrade-formulier toont, als er een actieve run is, een
  korte notitie: "Deze oefentrade telt mee op je lopende evaluatie
  (tier)."

## Zelf-review

**Niet-doelen nageleefd**: geen enkele wijziging raakt `risk.py`'s echte
positiegrootte-logica, `portfolio_eur`, `risk_percent`, of de
winrate-queries — die filteren nu al expliciet op `is_practice = 0` en
blijven dat doen; een evaluatie-gekoppelde trade is en blijft een
oefentrade in elk ander opzicht. Geen Kraken-koppeling, geen automatische
signalen, geen gelijktijdige runs, geen backfill.

**Schema-conventie**: nieuwe tabel via `CREATE TABLE IF NOT EXISTS`, nieuwe
kolom via schema.sql + idempotente `_migrate()`-ALTER, index pas ná de
kolom in `_migrate()`. Consistent met hoe `coin_narratives` en
`messages.narrative_id` eerder zijn toegevoegd.

**Ambiguïteit die is opgelost**: het onbevestigde Kraken-percentage voor
winstdoel en drawdown per tier is opgelost door ze door de gebruiker zelf
te laten instellen in plaats van te gokken naar een exact getal; het wél
bevestigde dagverlies-percentage (3%) ligt vast. De valuta-eenheid van de
zes tier-bedragen is expliciet de app's eigen eenheid, geen dollar-naar-
euro omrekening.

**Race-achtig scenario behandeld**: een trade die sluit nadat zijn run al
is afgesloten door een andere trade wordt genoemd en opgelost (geen
update meer op een bevroren run).
