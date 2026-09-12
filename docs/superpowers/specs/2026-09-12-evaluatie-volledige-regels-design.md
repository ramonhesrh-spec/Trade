# Evaluatie: volledige regels toepassen op echte trade-kansen

## Aanleiding

Vandaag gelden de Kraken Prop-evaluatieregels (dagverlies, drawdown,
winstdoel, 5x hefboomlimiet) alleen voor oefentrades die de gebruiker zelf
op het dashboard aanmaakt. Een echt Discord-signaal wordt gesized op
`portfolio_eur x risk_percent`, krijgt nooit een `evaluation_id`, en telt
dus nergens mee voor een lopende evaluatie. Wie zijn evaluatie serieus wil
laten meebewegen met de echte signalen die HesPulse binnenkrijgt, kan dat
nu niet: het systeem "ziet" een lopende evaluatie eenvoudigweg niet als er
een echt signaal binnenkomt.

De gebruiker wil dat, zodra hij een evaluatie actief heeft staan, HesPulse
zich voor échte trade-kansen aan de volledige regels van die evaluatie
houdt: sizing op het evaluatiesaldo, binnen dagverlies en drawdown, inclusief
fees en hefboomkosten. Doel is zoveel mogelijk Kraken Prop-evaluaties halen
door het systeem zelf discipline te laten afdwingen, in plaats van dat
alleen bij handmatige oefentrades te doen.

## Niet-doelen

- Geen wijziging aan hoe de stop loss zelf berekend wordt (marktstructuur:
  swing low/high + ATR-buffer, of bron-niveaus). Een engere stop zou vaker
  voortijdig uitstoppen op ruis; dat probleem wordt hier niet aangepakt.
- Geen ondersteuning voor meerdere gelijktijdig actieve evaluaties per
  gebruiker. Dat is al een bestaande, bewuste beperking (`prop_evaluations`:
  hoogstens één rij per gebruiker met status 'actief').
- Geen wijziging aan hoe een evaluatie start, slaagt of mislukt
  (`risk.evaluate_prop_progress`, `trading_day_label`) — die logica blijft
  ongewijzigd, dit deelproject verandert alleen HOEVEEL risico een trade
  neemt en OF een trade meetelt.
- Geen fee/hefboomkosten-verrekening voor niet-evaluatie-trades (de
  gewone portfolio_eur/risk_percent-trades). Dat blijft exact zoals nu.
- Geen aparte per-trade keuze om een signaal wel/niet aan de evaluatie te
  koppelen (zie Sectie 1) — dat is bewust automatisch.

## Sectie 1: automatische koppeling

Zodra een gebruiker een actieve evaluatie heeft (`repo.get_active_evaluation`
geeft een rij terug), gebruikt ELK echt signaal voor die gebruiker — zowel
de day-trading-hoofdflow als de swing-toets-flow in `signal_processor.py` —
voortaan de evaluatie als sizing-basis in plaats van
`portfolio_eur`/`risk_percent`, en krijgt de aangemaakte `journal_entries`-rij
`evaluation_id` gezet. Zonder actieve evaluatie verandert er niets: dan
blijft het bestaande `portfolio_eur x risk_percent`-pad exact zoals het is.

Dit maakt de twee bestaande aanroepen van
`risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])` in
`signal_processor.py` conditioneel: met actieve evaluatie wordt in plaats
daarvan de nieuwe functie uit Sectie 2 gebruikt, gebaseerd op
`active_eval["current_balance"]`.

## Sectie 2: sizing-formule

Nieuwe functie in `risk.py`, `compute_eval_risk_eur`, die het risicobedrag
voor één trade teruggeeft als het KLEINSTE van vier grenzen:

1. **Persoonlijke bovengrens**: `active_eval["current_balance"] *
   user["risk_percent"] / 100` — dezelfde `risk_percent`-instelling als
   altijd, nu tegen het evaluatiesaldo in plaats van `portfolio_eur`.
2. **Dagbudget-aandeel**: een derde van wat er nog over is van het
   dagverlies-budget. Resterend dagbudget is `day_start_balance *
   max_daily_loss_pct / 100`, min wat er vandaag al verloren is
   (`day_start_balance - current_balance`, nooit negatief), min het risico
   dat al vaststaat in nog open evaluatie-trades
   (`repo.total_open_risk_eur_for_evaluation`, al bestaande functie, nu
   ook gebruikt voor de sizing-berekening zelf in plaats van alleen voor
   de dashboard-weergave). Door door drie te delen blijft er ruimte voor
   nog twee tegenvallers dezelfde dag.
3. **Drawdown-aandeel**: dezelfde berekening, maar tegen de nooit-resettende
   drawdown-ruimte: `tier_amount * max_drawdown_pct / 100`, min
   `tier_amount - current_balance` (nooit negatief), min hetzelfde open
   risico, gedeeld door drie.
4. **Hefboomcap**: de bestaande `MAX_EVAL_LEVERAGE`-berekening uit
   `web/main.py:_resolve_practice_risk_eur`, ongewijzigd: `MAX_EVAL_LEVERAGE
   * current_balance * stop_distance / entry_price`.

```python
EVAL_BUDGET_TRADE_RESERVE = 3  # reserveer ruimte voor nog dit aantal - 1 volgende trades

def compute_eval_daily_budget_remaining(evaluation: dict, open_risk_eur: float) -> float:
    daily_loss_amount = evaluation["day_start_balance"] * evaluation["max_daily_loss_pct"] / 100
    loss_so_far = max(0.0, evaluation["day_start_balance"] - evaluation["current_balance"])
    return max(0.0, daily_loss_amount - loss_so_far - open_risk_eur)


def compute_eval_drawdown_budget_remaining(evaluation: dict, open_risk_eur: float) -> float:
    drawdown_amount = evaluation["tier_amount"] * evaluation["max_drawdown_pct"] / 100
    drawdown_so_far = max(0.0, evaluation["tier_amount"] - evaluation["current_balance"])
    return max(0.0, drawdown_amount - drawdown_so_far - open_risk_eur)


def compute_eval_risk_eur(
    evaluation: dict, risk_percent: float, open_risk_eur: float,
    entry_price: float, stop_loss: float,
) -> float:
    personal_cap = evaluation["current_balance"] * risk_percent / 100
    daily_share = compute_eval_daily_budget_remaining(evaluation, open_risk_eur) / EVAL_BUDGET_TRADE_RESERVE
    drawdown_share = compute_eval_drawdown_budget_remaining(evaluation, open_risk_eur) / EVAL_BUDGET_TRADE_RESERVE
    stop_distance = abs(entry_price - stop_loss)
    leverage_cap = (
        MAX_EVAL_LEVERAGE * evaluation["current_balance"] * stop_distance / entry_price
        if stop_distance > 0 and entry_price > 0 else float("inf")
    )
    return max(0.0, min(personal_cap, daily_share, drawdown_share, leverage_cap))
```

`MAX_EVAL_LEVERAGE` verhuist van `web/main.py` naar `risk.py` (het hoort
bij de evaluatie-rekenregels, niet bij de webroute), `web/main.py` importeert
'm van daar.

## Sectie 3: stoppen als het budget bijna op is

Als `compute_eval_daily_budget_remaining` ONDER 5% van het volledige
dagbudget (`day_start_balance * max_daily_loss_pct / 100`) zit, OF
`compute_eval_drawdown_budget_remaining` onder 5% van de volledige
drawdown-ruimte zit, wordt er voor de rest van die situatie geen nieuwe
evaluatie-trade meer gesized: het signaal komt gewoon binnen zoals altijd
voor de gewone `portfolio_eur`-sizing (`evaluation_id` blijft `None` op die
`journal_entries`-rij, telt dus niet mee voor de evaluatie). Voor het
dagbudget lost dit vanzelf op zodra `trading_day_label` een nieuwe
handelsdag aangeeft; voor drawdown lost het pas op als latere winst
`current_balance` weer ver genoeg boven de drempel brengt.

Nieuwe functie `risk.eval_sizing_blocked(evaluation, open_risk_eur) -> bool`
die deze twee percentages checkt en `True`/`False` teruggeeft. Aangeroepen
vóór `compute_eval_risk_eur`; als `True`, gedraagt het signaal zich alsof er
geen actieve evaluatie is (Sectie 1's normale pad).

## Sectie 4: fees en hefboomkosten

Alleen voor trades met een `evaluation_id` (dus niet voor gewone
portfolio-trades). Twee kostensoorten:

- **Handelsfee**: 0,04% bij openen + 0,04% bij sluiten = 0,08% round-trip
  over de positiewaarde. Zeker, ongeacht hoelang de trade openstaat.
- **Hefboomkosten**: 0,033% per dag over de positiewaarde, zolang de
  positie openstaat.

**Bij het bepalen van de positiegrootte** (dus vóór de trade genomen wordt)
is de exacte hefboomkost nog niet bekend — dat hangt af van hoelang de
trade uiteindelijk loopt. HesPulse rekent voorzichtigheidshalve met één dag
hefboomkosten erbij, passend bij een day-trading-systeem waar de meeste
trades binnen een dag klaar zijn. `compute_position_size` in `risk.py`
wordt uitgebreid met optionele fee-parameters:

```python
EVAL_TRADE_FEE_RATE = 0.0008         # 0,04% open + 0,04% sluiten
EVAL_LEVERAGE_DAILY_RATE = 0.00033   # per dag
EVAL_SIZING_DAYS_ASSUMPTION = 1.0    # voorzichtige aanname vooraf

def compute_position_size(
    risk_eur: float, entry_price: float, stop_loss: float,
    cost_rate: float = 0.0,
) -> Optional[float]:
    """cost_rate is de extra kostenfractie van de positiewaarde die
    meetelt als 'verlies' naast de pure prijsbeweging (fees + geschatte
    hefboomkosten), 0.0 voor niet-evaluatie-trades (ongewijzigd gedrag)."""
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    return risk_eur / (distance + entry_price * cost_rate)
```

Voor een evaluatie-trade wordt `cost_rate = EVAL_TRADE_FEE_RATE +
EVAL_LEVERAGE_DAILY_RATE * EVAL_SIZING_DAYS_ASSUMPTION` meegegeven; voor
elke andere trade blijft `cost_rate = 0.0` (default), dus ongewijzigd
gedrag voor alle bestaande aanroepen van `compute_position_size`.

**Bij het sluiten van de trade** wordt de WERKELIJKE kost verrekend, op
basis van hoe lang de trade daadwerkelijk openstond. Dit vereist het
werkelijke moment van instappen, dat vandaag nergens wordt opgeslagen
(`journal_entries` heeft wel `exit_time`, geen `entry_time`) en de
werkelijk gebruikte positiegrootte, die vandaag alleen achteraf uit
`risk_eur`/`entry_price`/`stop_loss` wordt herleid zonder de
fee-aanpassing uit deze sectie mee te nemen. Twee nieuwe kolommen op
`journal_entries`:

- `entry_time TEXT` — gezet op het moment dat `status` naar `'genomen'`
  gaat (dus in `update_journal_status`, analoog aan hoe `exit_time` al bij
  `close_journal_trade` wordt gezet).
- `position_size REAL` — de daadwerkelijk gebruikte positiegrootte,
  opgeslagen op het moment van aanmaken van de `journal_entries`-rij
  (`create_journal_entry`), zodat de fee-berekening bij sluiten precies
  dezelfde positiegrootte gebruikt als waarmee gesized is, in plaats van
  een losse herberekening die uit de pas kan lopen.

`close_journal_trade` trekt, alleen als `evaluation_id is not None`, de
werkelijke kosten af van `result_eur` vóór dat bedrag bij de evaluatie
wordt opgeteld:

```python
notional_eur = (entry["position_size"] or 0.0) * entry_price
trade_fee_eur = notional_eur * EVAL_TRADE_FEE_RATE
days_held = max(
    0.0,
    (datetime.fromisoformat(exit_time) - datetime.fromisoformat(entry["entry_time"])).total_seconds() / 86400,
)
leverage_cost_eur = notional_eur * EVAL_LEVERAGE_DAILY_RATE * days_held
if entry["evaluation_id"] is not None:
    result_eur -= (trade_fee_eur + leverage_cost_eur)
```

Loopt een trade toevallig meerdere dagen, dan zie je dat direct terug in
`current_balance`, en schaalt de volgende trade daar via de Sectie
2-formule automatisch op mee. De gewone `portfolio_eur`-aanpassing voor
niet-evaluatie-trades verandert niet: fees/hefboomkosten worden daar
helemaal niet verrekend (bestaand gedrag, buiten scope).

## Sectie 5: oefentrades gelijk trekken

`web/main.py:_resolve_practice_risk_eur` en de losse
`MAX_EVAL_LEVERAGE`-berekening daarin vervallen. Oefentrades roepen
voortaan dezelfde `risk.compute_eval_risk_eur`/`risk.eval_sizing_blocked`
aan als echte signalen (Sectie 1-3), en dezelfde
`compute_position_size(..., cost_rate=...)` als Sectie 4, zodat er nog maar
één plek is die weet hoe evaluatie-sizing werkt. Handmatige invoer
(`manual_risk_eur`, het eigen bedrag dat je op het oefentrade-formulier kan
intypen) blijft bestaan als bovengrens die de automatische berekening kan
overschrijven, precies zoals nu, maar wordt niet meer los van de
dagbudget/drawdown-grenzen gecapt: die grenzen gelden ook op een handmatig
ingevoerd bedrag.

## Sectie 6: zichtbaarheid

Het Telegram-bericht voor een signaal dat op de evaluatie is gesized krijgt
een regel met welk deel van het dagbudget deze trade gebruikt (bijvoorbeeld
"risico €42 — 8% van je resterende dagbudget"), naar het patroon van de
bestaande risicowaarschuwing-regel in het bericht
(CLAUDE.md: "Risicobeheer: risicowaarschuwing in het bericht zelf"). Als
Sectie 3 evaluatie-sizing blokkeert, krijgt het bericht in plaats daarvan
een duidelijke regel: "dagbudget evaluatie op, deze trade telt niet mee
voor je evaluatie" (of de drawdown-variant).

Op de bestaande `/evaluatie`-pagina en de dashboard-samenvatting
(`_build_eval_context`) wordt het al berekende
`eval_daily_loss_remaining_eur` hergebruikt om te tonen hoeveel
risicobudget een volgende trade nog zou krijgen (`/
EVAL_BUDGET_TRADE_RESERVE`), zodat de gebruiker vooraf kan inschatten
waarom een volgend signaal kleiner of groter gesized wordt.

## Sectie 7: database-wijzigingen samengevat

Twee nieuwe kolommen op de bestaande `journal_entries`-tabel, beide
`NULL`-baar (bestaande rijen hebben geen waarde, dat is correct: alleen
nieuwe evaluatie-trades gebruiken ze):

```sql
ALTER TABLE journal_entries ADD COLUMN entry_time TEXT;
ALTER TABLE journal_entries ADD COLUMN position_size REAL;
```

Per CLAUDE.md-conventie: toegevoegd aan zowel `schema.sql` (de
`CREATE TABLE IF NOT EXISTS journal_entries`-definitie, voor nieuwe
databases) als een idempotente `ALTER TABLE` in `db.py:_migrate()`,
gecheckt via `PRAGMA table_info` (voor bestaande databases). Geen nieuwe
index nodig: geen van beide kolommen wordt gebruikt in een `WHERE`- of
`JOIN`-clausule.
