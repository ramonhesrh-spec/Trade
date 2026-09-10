# Meerdere coins per Discord-bericht

## Aanleiding

De gebruiker meldde dat op de BNB-coinpagina niveaus van TAO en LINK
verschenen onder "bronnen". Oorzaak: één Discord-bericht ging over meerdere
coins tegelijk (een watchlist-achtige post), maar `app/anthropic_interpret.py`
interpreteert nu altijd precies één coin per bericht (`Interpretation.coin`
is een los `Optional[str]`). De AI koos BNB als hoofdcoin, maar nam ook de
ingetekende niveaus van TAO en LINK van dezelfde afbeelding over, allemaal
opgeslagen met `coin='BNB'`.

Besloten (expliciete keuze van de product owner, niet de kleine
reparatie-fix): wanneer een bericht meerdere coins bevat, pakt HesPulse elke
coin apart op als eigen signaal, met zijn eigen niveaus en eigen toetsing.
Een bericht met BNB, TAO en LINK levert drie losse verwerkingen op, elk
door de volledige bestaande pijplijn (samenvatting, bron niveaus, day
trading toets of lange termijn/narrative-pad, Telegram-melding), alsof het
drie losse berichten waren. Dit geldt ook voor coins die maar terloops
genoemd worden (bijvoorbeeld ter vergelijking) — expliciete keuze van de
product owner, met het besef dat dit het aantal meldingen bij een drukke
community-post kan verhogen.

## Niet-doelen

- Geen backfill van bestaande `messages`-rijen: die behouden hun huidige
  coin/direction/category/unclear/note/message_summary/price_at_receipt/
  narrative_id gewoon op de bestaande kolommen, zoals bij eerdere features
  (coin_narratives, swing-toets) al het patroon was.
- `scripts/backfill_swing_watches.py` wordt niet aangepast: dat is een
  eenmalig script dat zijn werk al gedaan heeft op historische data, geen
  onderdeel van de live pijplijn.
- Het dedupe-venster en de dedupe-voorwaarden (exact dezelfde `raw_text`,
  binnen 3 minuten, niet na een API-fout) blijven ongewijzigd. Alleen wát
  er bij een gevonden duplicaat gekopieerd wordt, verandert (nu N
  coin-resultaten in plaats van één).
- Geen wijziging aan hoe een single-coin bericht zich gedraagt: voor een
  bericht met precies één coin blijft de uitkomst functioneel identiek aan
  nu, alleen intern via de nieuwe tabel opgeslagen in plaats van rechtstreeks
  op `messages`.
- Geen apart limiet op het aantal coins per bericht. Als dit in de praktijk
  tot te veel meldingen leidt, is dat een vervolg-aanpassing, geen onderdeel
  van dit ontwerp.

## Sectie 1: Anthropic-interpretatie

`app/anthropic_interpret.py`'s TOOL-schema krijgt een array op het hoogste
niveau in plaats van losse coin/direction/category/unclear/reason/
source_levels-velden:

```json
{
    "name": "record_interpretation",
    "description": "Registreer de interpretatie van een Discord trading bericht. Een bericht kan over meerdere coins tegelijk gaan (bijvoorbeeld een watchlist-post of een vergelijking) — geef dan een apart item per coin, ook als een coin maar terloops genoemd wordt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "coins": {
                "type": "array",
                "description": "Eén item per coin die het bericht noemt. Leeg als geen enkele coin met voldoende zekerheid te bepalen is.",
                "items": {
                    "type": "object",
                    "properties": {
                        "coin": {"type": "string", "description": "Ticker symbool, bijvoorbeeld BTC."},
                        "direction": {"type": "string", "enum": ["long", "short", "neutraal", ""]},
                        "category": {"type": "string", "enum": ["day_trading", "lange_termijn", "aandelen"]},
                        "unclear": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "source_levels": {
                            "type": "array",
                            "description": "Alleen niveaus die de bron zelf heeft ingetekend voor DEZE coin. Een niveau dat bij een andere coin in dezelfde afbeelding hoort, hoort bij dat andere coin se item, niet hier.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "price_level": {"type": "number"},
                                    "pattern_name": {"type": "string"}
                                },
                                "required": ["price_level"]
                            }
                        }
                    },
                    "required": ["coin", "category", "unclear"]
                }
            }
        },
        "required": ["coins"]
    }
}
```

`SYSTEM_PROMPT` krijgt een nieuwe alinea die expliciet instrueert: een
bericht kan meerdere coins behandelen, geef een apart item per coin (ook een
coin die maar ter vergelijking genoemd wordt), en bij een afbeelding met
niveaus voor meerdere coins hoort elk niveau bij precies één item — dit is
de directe fix voor de gerapporteerde bug (TAO/LINK-niveaus die bij BNB
belandden).

`SourceLevel` blijft ongewijzigd. `Interpretation` blijft ongewijzigd qua
velden (`coin`, `direction`, `category`, `unclear`, `reason`,
`source_levels`) — het is nog steeds "de uitkomst voor één coin", alleen
`interpret_message()` verandert van teruggeven van één `Interpretation` naar
`list[Interpretation]`. Een leeg `coins`-array (geen enkele coin te
bepalen) geeft een lijst met precies één `Interpretation(coin=None,
unclear=True, reason="coin niet duidelijk uit het bericht te halen")` terug
— hetzelfde effectieve gedrag als nu bij een volledig onduidelijk bericht.

## Sectie 2: database

Nieuwe tabel, één rij per (bericht, coin):

```sql
CREATE TABLE IF NOT EXISTS message_coin_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    coin TEXT,
    direction TEXT,
    category TEXT,
    unclear INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    message_summary TEXT,
    price_at_receipt REAL,
    narrative_id INTEGER REFERENCES coin_narratives(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_coin_results_message_id ON message_coin_results(message_id);
CREATE INDEX IF NOT EXISTS idx_message_coin_results_coin ON message_coin_results(coin);
CREATE INDEX IF NOT EXISTS idx_message_coin_results_unclear ON message_coin_results(unclear);
```

`messages` zelf verandert geen kolom: `coin`, `direction`, `category`,
`unclear`, `note`, `message_summary`, `price_at_receipt`, `narrative_id`
blijven bestaan (historische rijen, en de "API fout"/"duplicaat"-paden
hieronder blijven ze rechtstreeks gebruiken), maar worden voor een
succesvol geïnterpreteerd multi-coin bericht niet meer ingevuld — de
per-coin uitkomst leeft dan in `message_coin_results`. `processed_at` op
`messages` blijft zijn huidige betekenis houden: "is de verwerking van dit
hele bericht klaar", gezet nadat alle coins verwerkt zijn (of na een totale
mislukking).

`signals`, `source_levels`, `swing_watches` veranderen niet: die hebben al
hun eigen `coin`-kolom per rij en hun eigen `message_id`-foreign key, dat
bleef altijd al correct per coin.

## Sectie 3: verwerkingspijplijn

`app/signal_processor.py:handle_message` splitst in een envelope-deel en
een per-coin-deel:

**Envelope-deel** (ongewijzigd qua volgorde, nu over de hele lijst):
1. Dedupe-check op `raw_text`, zoals nu.
2. Bij een gevonden duplicaat: kopieer niet langer één coin/direction/
   category naar de nieuwe `messages`-rij, maar lees alle
   `message_coin_results`-rijen van het origineel en maak voor elk daarvan
   een nieuwe rij aan met hetzelfde message_id maar het nieuwe bericht se
   `message_id`, met `note` aangevuld met "duplicaat van bericht #X, niet
   opnieuw verwerkt". `messages.processed_at` van het nieuwe bericht wordt
   gezet, `messages.coin/direction/category/unclear` blijven leeg (dezelfde
   envelope-conventie als bij een normale succesvolle verwerking).
3. Anthropic-interpretatie: nu `interpret_message()` die een lijst
   teruggeeft, via dezelfde `_interpret_with_retry` (3 pogingen op de hele
   aanroep, niet per coin — één Anthropic-call blijft één Anthropic-call).
4. Bij een totale mislukking (na 3 pogingen): ongewijzigd, rechtstreeks op
   `messages` (coin=None, unclear=True, note met de fout), exact zoals nu.
   Er is dan geen enkele `message_coin_results`-rij.
5. Bij succes: loop over de lijst, roep per `Interpretation` de bestaande
   per-coin-logica aan (zie hieronder), en zet daarna
   `messages.processed_at`.

**Per-coin-deel** (was het grootste deel van de huidige `handle_message`,
wordt een losse functie die per coin exact doet wat er nu al gebeurt, maar
schrijft naar `message_coin_results` in plaats van naar `messages`):
- `explain.summarize_message(coin, raw_text)` — ongewijzigd aangeroepen,
  resultaat opgeslagen in `message_coin_results.message_summary` voor déze
  coin (elke coin krijgt zijn eigen, op die coin toegespitste samenvatting).
- Bron niveaus opslaan (`repo.insert_source_level`) — ongewijzigd, deze
  functie nam coin al als parameter.
- day_trading: `process_day_trading_signal`, ongewijzigd van signatuur.
- lange_termijn/aandelen: `evaluate_narrative`/`evaluate_level_watch`/
  live-prijs-vastlegging, ongewijzigd van signatuur, nu met
  `message_coin_results.price_at_receipt`/`narrative_id` als opslagplek
  in plaats van `messages`.

`repo.py` krijgt: `insert_message_coin_result(message_id, coin, direction,
category, unclear, note, message_summary=None) -> int` (voor het aanmaken
van de rij zodra de coin-verwerking start), en
`update_message_coin_result(...)` voor de velden die pas later bekend
worden (`price_at_receipt`, `narrative_id`) — exacte signaturen zijn aan de
implementatie-planningsfase.

## Sectie 4: de kern-bug zelf, één laag dieper

`repo.list_source_levels_for_message(message_id)` (gebruikt in
`process_day_trading_signal` om `message_levels` op te bouwen voor de
stop/take-berekening) filtert nu alleen op `message_id`, niet op coin. Met
meerdere coins die straks hetzelfde `message_id` delen, zou dit exact
dezelfde soort bug reproduceren als de gerapporteerde — nu niet alleen
zichtbaar in de "bronnen"-lijst, maar ook lekkend in de stop loss/take
profit-berekening van de verkeerde coin. Dit MOET meeveranderen:
`list_source_levels_for_message` krijgt een verplichte `coin`-parameter
(`WHERE message_id = ? AND coin = ?`), en de aanroep in
`process_day_trading_signal` geeft `interp.coin` mee. Dit is geen losse
sub-taak maar een harde vereiste van dit ontwerp: zonder deze fix lost de
wijziging het gerapporteerde probleem niet werkelijk op, hij verplaatst het.

## Sectie 4b: dezelfde klasse bug, ook in de narrative-koppeling

Tijdens het uitwerken van het implementatieplan bleek `app/repo.py`'s
`create_narrative`/`update_narrative_progress` hetzelfde patroon te hebben
als Sectie 4's `list_source_levels_for_message`: ze schrijven
`UPDATE messages SET narrative_id = ? WHERE id = message_id`, zonder
coin-filter. Met meerdere coins die hetzelfde `message_id` delen, zou een
lange-termijn-narrative voor coin A het hele bericht (dus ook coin B se
niet-gerelateerde resultaat) aan narrative A koppelen. `list_narrative_messages`
leest bovendien rechtstreeks `messages.narrative_id`/`messages.message_summary`
voor de narrative-tijdlijn.

Zelfde verplichte fix als Sectie 4: `create_narrative`/`update_narrative_progress`
schrijven voortaan naar `message_coin_results.narrative_id WHERE id = <coin-resultaat-id>`
in plaats van naar `messages.narrative_id WHERE id = message_id`, en
`list_narrative_messages` leest de tijdlijn via een join op
`message_coin_results` (voor `narrative_id`/`message_summary`) met `messages`
(voor `received_at`/`raw_text`), met dezelfde soort legacy-tak als Sectie
5's dashboard-query voor historische pre-migratie rijen.

## Sectie 5: zichtbare impact

**Dashboard, onduidelijke berichten** (`repo.recent_unclear_messages`,
admin-only): toont voortaan per coin een eigen regel. Query wordt een JOIN
tussen `message_coin_results` (waar `unclear = 1`) en `messages` (voor
`received_at`/`raw_text`), samengevoegd met de bestaande query op
`messages` zelf (voor de "API fout"-rijen, die geen
`message_coin_results`-rij hebben) en historische pre-migratie rijen.

**Telegram**: een multi-coin bericht kan meerdere losse meldingen
opleveren, precies zoals meerdere losse Discord-berichten dat nu al doen.
Geen samenvoeging tot één bericht — dat zou de per-coin-toetsing en
region-specifieke stop/take-informatie juist weer door elkaar halen, het
tegenovergestelde van deze fix.

**`scripts/regenerate_message_summaries.py`**: leest nu
`list_messages_for_summary_backfill()` die rechtstreeks van `messages`
leest. Voor berichten na deze wijziging moet dit per coin uit
`message_coin_results` lezen in plaats van van `messages`; historische
rijen blijven via het oude pad werken. Onderdeel van de implementatie, geen
apart ontwerp nodig — hetzelfde soort dubbele-bron-patroon als Sectie 5's
dashboard-query.

## Zelf-review

- Placeholder-scan: geen "TBD"/"TODO", elke sectie geeft concrete
  kolomnamen, functienamen en een uitgewerkte tool-schema.
- Interne consistentie: Sectie 2's schema en Sectie 3's pijplijn-beschrijving
  gebruiken dezelfde kolomnamen (`message_coin_results.message_summary`,
  `.price_at_receipt`, `.narrative_id`) als waar Sectie 3 ze vult.
- Scope-check: dit blijft één samenhangende wijziging (interpretatie →
  opslag → pijplijn → de twee zichtbare lijstjes die ervan afhangen), niet
  opgesplitst in losse deelprojecten nodig.
- Ambiguïteitscheck: het duidelijkste risico was `list_source_levels_for_message`
  die zonder coin-filter de oorspronkelijke bug alsnog in de stop/take-
  berekening zou laten doorsijpelen — expliciet als harde vereiste benoemd
  in Sectie 4, niet als losse suggestie.
