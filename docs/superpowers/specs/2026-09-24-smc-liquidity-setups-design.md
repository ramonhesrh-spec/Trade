# SMC liquidity setups — design

> **Noot na implementatie.** Een paar namen uit dit ontwerp bestaan niet
> meer in de code: `delete_stale_smc_setups(coin, keep_ids)` werd
> `delete_smc_setup(setup_id)` (één rij tegelijk, zodat een bouwende setup
> meerdere cycli blijft bestaan), en `_find_smc_candidate` /
> `_candidate_score` werden `_check_smc_setup` + `_complete_smc_setup`
> (SMC dingt niet mee in de structurele top-3). Het implementatieplan
> `docs/superpowers/plans/2026-09-24-smc-liquidity-setups.md` en de code
> zelf zijn leidend voor de uiteindelijke namen en details; dit document
> legt alleen het ontwerp vast.

## Probleem

De bestaande drie structurele detectoren (uitbraak+terugtest, trendlijn+
terugtest, patroon) en de gewone dagtrading-toetsing draaien allemaal op
4-uurs candles. Een klassieke Smart Money Concepts / ICT-stijl setup —
structuurbreuk, liquidity sweep, terugtrek naar een fair value gap of
order block, afwijzing, koers naar de liquidity daaronder of daarboven —
speelt zich af op 15 tot 30 minuten en is binnen ongeveer een dag klaar.
Op een 4-uurs candle valt die hele beweging in een handvol candles, de
steun/weerstand-zones en pivots die het systeem nu herkent worden op dat
tempo berekend, niet op het tempo van deze setups. Zulke kansen komen
daardoor nooit door de bestaande pijplijn heen, of ze nu autonoom gezocht
worden of via een doorgestuurd bericht.

## Kernidee

Een vierde, volledig autonome structurele detector, naast de drie
bestaande, die op 30 minuten (bias) en 15 minuten (entry) naar precies dit
patroon zoekt: een marktstructuurbreuk, voorafgegaan door een liquidity
sweep, gevolgd door een terugtrek naar een zone waar een fair value gap en
een order block overlappen, en een afwijzing daar. Twee fasen:

- **Bouwend**: structuurbreuk en sweep staan vast, de zone (FVG ∩ order
  block) is bekend, maar de prijs zit er nog niet in of heeft nog niet
  afgewezen. Hiervan stuurt het systeem één keer een melding, zodat de
  gebruiker een limit order op de zone kan klaarzetten. Zichtbaar op een
  nieuwe, eigen pagina.
- **Compleet**: prijs is in de zone geweest en heeft daar afgewezen (een
  15m-candle die binnen de zone opent of raakt, maar aan de kant van de
  richting sluit). Wordt een gewoon signaal, `trade_type = "smc"`,
  gaat door dezelfde journaal/trackrecord/winrate-machinery als elk
  ander signaal, en verschijnt zowel op de nieuwe pagina als op de
  bestaande /signalen en het dashboard.

Geen percentage, geen drempel: alle stappen moeten kloppen of er is geen
setup. Geen ATR: stop net voorbij de sweep, doel net vóór de liquidity
zelf, beide structuur-gebaseerd. Altijd melden, ook op een gemute coin —
zelfde precedent als patroon en swing (`is_coin_muted` wordt alleen in het
gewone dagtrading-pad gecheckt, zie `app/signal_processor.py:1075,1225`),
dit is precies bedoeld om een grote kans nooit te missen.

## Niet-doelen

- Geen wijziging aan de bestaande drie structurele detectoren, aan
  `confirms_direction`, of aan de 4-uurs dagtrading-toetsing.
- Geen Discord-koppeling: dit draait volledig autonoom binnen de
  bestaande marktscan-cyclus (elke 20 minuten), nooit getriggerd door een
  doorgestuurd bericht.
- Geen aparte, snellere scan-timer. De bestaande 20-minuten-cyclus is snel
  genoeg: een terugtrek in een zone duurt meestal meerdere candles, geen
  enkele 15m-tik.
- Geen instelbare tijdshorizon per coin of gebruiker. 30m/15m ligt vast.
- Geen ATR, nergens in dit onderdeel — niet voor de zone-dedup, niet voor
  stop/doel.
- Geen integratie met het per-gebruiker drempel-percentage of de net
  gebouwde verplichte-factoren-instelling (`user_required_factors`). SMC
  is een harde, binaire eis, los daarvan.
- Geen wijziging aan hoe mute werkt voor gewone dagtrading-meldingen.

## Component 1 — detectie-primitieven (`app/indicators.py`)

Vier nieuwe functies, elk zoveel mogelijk bovenop wat er al staat.

```python
@dataclass
class StructureBreak:
    direction: str          # "long" of "short"
    broken_pivot: Pivot     # de swing-high/low die brak
    break_index: int        # candle-index van de sluiting die brak


def find_structure_break(window: pd.DataFrame) -> Optional[StructureBreak]:
    """Market structure shift: de laatste candle in window sluit voorbij
    een eerdere, bevestigde swing (via het al bestaande _find_pivots) —
    voor bullish een close boven een eerdere swing-high, voor bearish een
    close onder een eerdere swing-low. Een staart die er doorheen prikt
    zonder dat de candle er ook mee sluit telt niet, dat is een sweep
    (zie find_liquidity_sweep_before_break hieronder), geen structuurbreuk.
    Geeft de meest recente breuk terug, of None."""


def find_liquidity_sweep_before_break(
    window: pd.DataFrame, structure_break: StructureBreak,
) -> Optional[Pivot]:
    """Hergebruikt _find_liquidity_sweep (al gebruikt door de sniper-entry-
    feature) op het venster vóór structure_break.break_index, met DEZELFDE
    richting als de structuurbreuk — niet tegengesteld. _find_liquidity_sweep's
    eigen conventie is al dat direction="short" een sweep aan de high-kant
    betekent (kind="high" intern), en dat is precies de buy-side liquidity
    die een bearish reversal voedt: prijs veegt eerst een eerdere high leeg
    (stop losses van shorts, breakout-buys) voordat hij hard omlaag draait
    en een eerdere low doorbreekt (de structuurbreuk zelf). Bij
    direction="long" spiegelt dit: een sweep van een eerdere low (kind="low"),
    de sell-side liquidity die een bullish reversal voedt. Geeft de geveegde
    pivot terug (wordt straks de stop), of None als er geen sweep vlak voor
    de breuk zat — dan is het geen geldige setup."""


@dataclass
class FVG:
    low: float
    high: float


def find_fair_value_gaps(df: pd.DataFrame, direction: str) -> list[FVG]:
    """Klassieke drie-candle fair value gap: voor bearish (weerstand-zone
    om in te zakken) candle 1's low boven candle 3's high, het gat
    daartussen. Voor bullish het spiegelbeeld. Zoekt over de volledige
    meegegeven df (15m), retourneert alle gevonden gaps, nieuwste eerst."""


@dataclass
class OrderBlock:
    low: float
    high: float


def find_order_blocks(df: pd.DataFrame, direction: str) -> list[OrderBlock]:
    """De laatste candle in de tegengestelde kleur vlak vóór een sterke
    displacement-beweging: voor bearish de laatste groene candle voor een
    duidelijke rode dump (drie of meer candles op rij dalend, of één
    candle met een bereik van minstens 2x het gemiddelde bereik van de
    voorgaande 10 candles — zelfde soort "duidelijke beweging"-maat als
    elders in dit bestand, geen nieuwe losse constante). Retourneert het
    volledige candle-bereik (low, high) als zone."""


def find_confluence_zone(fvgs: list[FVG], order_blocks: list[OrderBlock]) -> Optional[tuple[float, float]]:
    """Enige geldige terugtrek-zone: een fair value gap en een order block
    die elkaar overlappen. Geen overlap, geen zone — puur alleen een FVG
    of alleen een order block telt niet mee (expliciete keuze, zuiverheid
    boven meer signalen). Geeft (low, high) van de overlap terug, het
    snijvlak van beide ranges."""
```

## Component 2 — data model (`app/schema.sql`, `app/repo.py`)

Nieuwe tabel, brand-new dus `CREATE TABLE IF NOT EXISTS` volstaat, geen
`_migrate()`-guard nodig (precedent `muted_coins`/`sr_zone_failures`):

```sql
CREATE TABLE IF NOT EXISTS smc_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    structure_level REAL NOT NULL,
    sweep_price REAL NOT NULL,
    liquidity_target REAL NOT NULL,
    alert_sent INTEGER NOT NULL DEFAULT 0,
    signal_id INTEGER REFERENCES signals(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_smc_setups_coin ON smc_setups(coin);
```

`app/repo.py`, vier nieuwe functies:

```python
def upsert_smc_setup(coin: str, direction: str, zone_low: float, zone_high: float,
                      structure_level: float, sweep_price: float, liquidity_target: float) -> int:
    """Vindt een bestaande bouwende setup voor deze coin+richting waarvan
    de zone binnen ZONE_DEDUP_PCT procent van de nieuwe zone ligt (géén
    ATR, een percentage van de prijs — zie de niet-doelen) en werkt die
    bij (updated_at), of maakt een nieuwe rij aan als er geen match is.
    Retourneert het id. Nooit alert_sent overschrijven bij een update op
    een bestaande rij, dat zou de eenmalige melding laten herhalen."""


def list_forming_smc_setups() -> list[dict]:
    """Alle bouwende setups (signal_id IS NULL), voor de nieuwe pagina."""


def mark_smc_alert_sent(setup_id: int) -> None:
    ...


def complete_smc_setup(setup_id: int, signal_id: int) -> None:
    """Koppelt de bouwende setup aan het net aangemaakte signaal."""


def delete_stale_smc_setups(coin: str, keep_ids: list[int]) -> None:
    """Verwijdert bouwende setups voor deze coin die niet meer in
    keep_ids zitten (dit scan-cyclus geen match meer) — dezelfde vervallen-
    logica als 'prijs liep voorbij de zone zonder afwijzing' of 'een
    nieuwe tegengestelde structuurbreuk gebeurde eerst', uitgewerkt in
    Component 3 hieronder. Nooit een rij verwijderen die al een
    signal_id heeft, dat is een voltooide setup, geen vervallen bouwende."""
```

`ZONE_DEDUP_PCT`: nieuwe module-constante in `app/indicators.py` of
`app/market_scanner.py` (bijvoorbeeld 0.3%), analoog aan de bestaande
`TRENDLINE_DEDUP_ATR_MULTIPLE`, maar in percentage in plaats van ATR.

## Component 3 — orkestratie (`app/market_scanner.py`)

Nieuwe functie `_find_smc_candidate(coin, df_30m, df_15m) -> Optional[dict]`,
zelfde vorm als de drie bestaande `_find_*_candidate`-functies (geeft een
kandidaat terug met een `notify()`-closure, wordt door `scan_market()`
meegewogen tegen de andere structurele kandidaten via `_candidate_score`).

Stappen binnen die functie, in volgorde — elke stap kan `None` teruggeven
en dan stopt de check voor deze coin dit cyclus:

1. `find_structure_break(df_30m)` — geen breuk, geen setup.
2. `find_liquidity_sweep_before_break(df_30m, structure_break)` — geen
   sweep vlak voor de breuk, geen setup.
3. `find_fair_value_gaps(df_15m, direction)` en
   `find_order_blocks(df_15m, direction)`, dan
   `find_confluence_zone(...)` — geen overlap, geen setup.
4. `repo.upsert_smc_setup(...)` met de gevonden zone, `structure_level`
   (de gebroken pivot-prijs), `sweep_price` (de geveegde pivot-prijs),
   `liquidity_target` (de eerstvolgende tegengestelde liquidity-pivot
   voorbij de zone, gevonden met dezelfde `_find_pivots` op een breder
   venster).
5. Is de laatste 15m-candle nog niet in de zone geweest: dit cyclus stopt
   hier. Was `alert_sent` nog 0, dan wordt de eenmalige "bouwend"-melding
   verstuurd (zie Component 5) en `mark_smc_alert_sent` gezet — geen
   signaal, geen journaalregel, puur een pushmelding.
6. Is de prijs wel in de zone geweest: kijk of er al een afwijzende candle
   was (een 15m-candle die de zone raakt maar aan de kant van de richting
   sluit). Nog niet: stap 5 hierboven. Wel: dit wordt de kandidaat die
   `scan_market()` terugkrijgt, met `notify()` die het echte signaal
   aanmaakt (zie Component 4) en `repo.complete_smc_setup` aanroept.

**Vervallen** (uitgewerkt in `delete_stale_smc_setups`, aangeroepen aan
het eind van elke scan-cyclus per coin): een bouwende setup die de prijs
voorbij de zone ziet lopen zonder ooit af te wijzen, of waarvoor een
nieuwe, tegengestelde structuurbreuk gebeurt vóórdat de oude is afgerond,
wordt verwijderd. Een setup met een `signal_id` (al voltooid) wordt nooit
verwijderd, die blijft als koppeling bestaan.

Scan-cyclus blijft ongewijzigd op 20 minuten (zie Niet-doelen). Per coin
worden binnen dezelfde cyclus als nu ook 30m- en 15m-candles opgehaald,
naast de bestaande 4-uurs data — twee extra `exchange.fetch_ohlcv`-
aanroepen per coin per cyclus.

## Component 4 — signaal-aanmaak (geen ATR)

Bij het compleet worden van een setup (stap 6 hierboven):

```python
sign = -1 if direction == "long" else 1
stop_loss = sweep_price + STOP_MARGIN_PCT * sweep_price * sign
take_profit = liquidity_target + TARGET_MARGIN_PCT * liquidity_target * sign
```

Beide gebruiken hetzelfde teken, niet toevallig: voor short ligt de stop
BOVEN de geveegde high (verder van de entry af) en het doel ligt ook
BOVEN de liquidity-low (dichter bij de entry, "net vóór" het niveau) —
voor long allebei eronder. Zelf-review-correctie: een eerdere versie van
deze formule had voor het doel het omgekeerde teken, wat het doel voorbij
de liquidity in plaats van ervóór had gelegd. `STOP_MARGIN_PCT`/
`TARGET_MARGIN_PCT`: nieuwe, kleine percentages, 0,1% voor de stop en
0,5% voor het doel — dit zijn geen vrijblijvende voorbeeldwaarden maar de
daadwerkelijk te gebruiken constanten, puur prijs-gebaseerd, geen ATR.
Geverifieerd met een concreet voorbeeld (short: sweep_price 2820,
liquidity_target 2600 → stop 2823, doel 2613, beide aan de juiste kant;
**tweede zelf-review-correctie, tijdens de SDD-uitvoering van Task 5
gevonden**: een eerdere versie van dit voorbeeld noemde ten onrechte
"stop 2848, doel 2626" — die getallen kloppen alleen bij 1%-marges, niet
bij de hierboven genoemde 0,1%/0,5%. Nagerekend en gecorrigeerd; de
0,1%/0,5%-percentages zelf staan niet ter discussie, alleen het
illustratieve rekenvoorbeeld was fout).

`risk.compute_position_size(risk_eur, entry_price, stop_loss, cost_rate)`
wordt ongewijzigd hergebruikt — die functie was al zuiver
afstand-gebaseerd, nooit ATR-afhankelijk, dus hoeft niet aangepast.

`signals`-rij: `trade_type = "smc"`, `pattern_name = "SMC liquidity sweep"`
(of vergelijkbaar), `pass_pct`/`hard_gates_ok` blijven `None`/`1` (geen
percentage-toets van toepassing, net als swing), `reason` bevat een
leesbare "waarom"-tekst opgebouwd uit `structure_level`, `sweep_price`,
de zone en `liquidity_target` (geen ✓/✗-breakdown-formaat zoals
`confirms_direction`, dit is geen gepoolde-factoren-toets — dus
`repo.user_confirmed`/de verplichte-factoren-feature is hier sowieso niet
van toepassing, zoals in de Niet-doelen al staat).

## Component 5 — meldingen

Twee soorten, beide via de bestaande push-infrastructuur, geen mute-check
(zie Kernidee):

- **Bouwend** (eenmalig, stap 5 in Component 3): geen `signals`-rij, geen
  journaal — een losse pushmelding naar alle gebruikers via
  `push_notify.send_push`, met de zone erin: "ETH, bearish structuur +
  sweep gezien, zone 2695-2710, zet je limit order klaar."
- **Compleet** (stap 6): gaat via `fanout_confirmed_signal` met de
  sentinel `_KANSBEREKENING_NOT_APPLICABLE` — zelfde pad als swing, altijd
  gemeld, geen per-gebruiker percentage-vergelijking, wel de bestaande
  per-gebruiker positiegrootte en stop-cap.

## Component 6 — nieuwe pagina (`web/main.py`, `web/templates/smc.html`)

Nieuwe route `/smc`, nieuwe navigatielink in `base.html`. Twee secties:

- **Bouwende setups** bovenaan, prominent: per setup de zone (zone_low -
  zone_high) groot en duidelijk, dat is de limit-order-informatie.
  Daaronder, ingeklapt net als de bestaande `reason_popup`/
  `confidence-detail`-secties elders, de onderbouwing: welk niveau brak
  (`structure_level`), waar de sweep zat (`sweep_price`), waar het doel
  ligt (`liquidity_target`). Data via `repo.list_forming_smc_setups()`.
- **Afgeronde signalen**: dezelfde `macros.signal_card`-stijl als
  /signalen, gefilterd op `trade_type == "smc"`.

Afgeronde SMC-signalen verschijnen ook gewoon op de bestaande /signalen
en het dashboard, tellen mee in trackrecord/winrate/journaal — deze
pagina is een extra, gerichte weergave, geen aparte losse wereld (zie
Kernidee).

## Testen

Geen pytest-suite, geen live Binance-toegang in de ontwikkelomgeving (zie
CLAUDE.md). Voor de vier nieuwe detectie-primitieven in
`app/indicators.py`: throwaway scripts met handmatig samengestelde
`pd.DataFrame`-candle-reeksen die een bekende structuurbreuk+sweep+FVG+
order-block-sequentie nabouwen, en losse reeksen die er expres net naast
zitten (staart-doorbraak zonder close-doorbraak, sweep te lang vóór de
breuk, FVG zonder overlappende order block) om te bewijzen dat die
terecht `None` teruggeven. Voor `upsert_smc_setup`/dedup/vervallen:
scratch-DB scripts zoals bij elke eerdere plan in dit project. Voor de
pagina: handmatige Playwright-verificatie tegen een scratch-DB met een
paar handmatig ingevoegde `smc_setups`-rijen.
