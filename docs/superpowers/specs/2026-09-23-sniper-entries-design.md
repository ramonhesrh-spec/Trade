# Sniper entries — design

## Probleem

De bestaande "betere entry"-suggestie (`suggested_entry_low/high`, uit de
steun/weerstand-zone tussen entry en stop) lost drie dingen niet op:

1. De eerste melding komt op marktprijs, niet op het scherpste instapmoment.
2. De suggestie is een brede zone (de hele geclusterde S/R-band), geen
   precies niveau.
3. Er is weliswaar al een proactief wachtmechanisme
   (`level_check.py::check_pending_signals`, elke 15 min), maar dat kijkt
   alleen of de prijs terug is in die brede zone — niet naar een scherp,
   herkenbaar omslagmoment.

## Kernidee

`indicators._find_liquidity_sweep` bestaat al (SMC-deelproject, sessie van
2026-09-16): een stop-hunt van een eerdere pivot-low/-high, gevolgd door
een close terug aan de goede kant, binnen de laatste
`LIQUIDITY_SWEEP_RECENT_CANDLES` (3) candles. Dat is precies wat "sniper"
bedoelt — een scherp, precies, vers omslagpunt, geen brede zone. Nu wordt
dit alleen gebruikt als 1-van-16 gepoolde factor (`check_liquidity_sweep`,
via `compute_advanced_extra_factors`), onzichtbaar tussen de rest.

Dit ontwerp tilt de sweep eruit als eigen, zichtbaar concept: een precieze
prijs, een duidelijke reden ("waarom is dit een sniper-entry"), zichtbaar
op de signaalkaart en in de pushmelding, plus een eigen proactieve
melding als de sweep pas ná het eerste signaal gebeurt. Geen nieuwe
SMC-detectie — puur het zichtbaar maken en actief bewaken van wat er al
gedetecteerd wordt.

## Niet-doelen

- De eerste melding blijft ongewijzigd op marktprijs komen (expliciet
  bevestigd door de gebruiker) — sniper is een aanvulling, geen vervanging.
- Geen daily-timeframe-variant in v1 (`check_daily_liquidity_sweep` blijft
  een aparte, gepoolde factor zoals nu; alleen de 4u-sweep wordt sniper).
- Geen wijziging aan stop-loss/take-profit/positiegrootte-berekening.
- Swing blijft buiten scope (geen sweep-factor in die toets, zie
  `confirms_direction`'s basis-pad).
- Geen aparte SMC-detectielogica (order blocks, fair value gaps) — expliciet
  overwogen (aanpak C) en afgewezen: hoger bouwrisico voor weinig extra
  precisie boven wat de sweep al geeft.

## Component 1 — precieze prijs + reden beschikbaar maken

Nieuwe functie in `app/indicators.py`:

```python
def find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]:
```

Roept `_find_liquidity_sweep` rechtstreeks aan op dezelfde window
(`df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)`, identiek aan
`check_liquidity_sweep`). Geeft `None` terug als er geen sweep is, anders
`(hit.price, reden)` waarbij `reden` een leesbare uitleg is, bijvoorbeeld:

> "Stop-hunt: prijs werd even onder {hit.price:.4f} geduwd en sloot er
> meteen weer boven — de klassieke bear trap, hier zaten net de stops van
> anderen."

(spiegelbeeld voor short/boven). Dit is de tekst die straks zowel op de
signaalkaart als in de push komt — de gebruiker vroeg expliciet om een
duidelijke "waarom sniper"-uitleg, niet alleen een prijs of badge.

`check_liquidity_sweep` zelf blijft ongewijzigd (nog steeds gebruikt voor
de gepoolde 16-factoren-toets); deze nieuwe functie is een aparte, dunne
laag eroverheen — geen dubbele detectielogica, wel een aparte, op-maat
tekst voor sniper-gebruik in plaats van de kortere factor-detail-string.

## Component 2 — bij signaal-aanmaak

Op de vier plekken waar nu al een `signal_data`-dict gebouwd wordt vóór
`repo.insert_signal`:
- `signal_processor.py::process_day_trading_signal`
- `market_scanner.py::_find_breakout_retest_candidate`
- `market_scanner.py::_find_trendline_retest_candidate`
- `market_scanner.py::_find_chart_pattern_candidate`

komt één extra regel: `sniper = indicators.find_sniper_entry_price(direction, df)`.
`df` is op alle vier plekken al beschikbaar (geen extra Binance-aanroep).

**Schema:** twee nieuwe kolommen op `signals`, twee-delige migratie zoals
CLAUDE.md voorschrijft (`CREATE TABLE IF NOT EXISTS` dekt een verse
database, `_migrate()` met `PRAGMA table_info`-guard dekt een bestaande):
- `sniper_entry_price REAL` (nullable)
- `sniper_reason TEXT` (nullable)

**repo.py:** drie plekken hebben allemaal hun eigen expliciete kolomlijst,
geen van alle `SELECT s.*` — alle drie moeten `sniper_entry_price`
(en waar relevant `sniper_reason`) er los bij krijgen, anders valt het veld
stil weg zonder foutmelding (precies de fout die de bestaande comment
boven `_JOURNAL_SELECT` al één keer eerder beschreef, bij
`suggested_entry_low/high`):
- `insert_signal`'s `fields`-lijst (schrijven)
- `_JOURNAL_SELECT` — beide kolommen, voor de signaalkaart
- `list_pending_entries_with_price` — alleen `sniper_entry_price` (als
  `None`, betekent dat "nog niet gevonden bij aanmaak", de trigger voor
  Component 3 hieronder om zelf opnieuw te checken; `sniper_reason` is
  hier niet nodig, Component 3 berekent zijn eigen verse reden)

**Weergave (signal_card, `_macros.html`):** een nieuw blok, direct na het
bestaande `signal-card-entry-zone`-blok, met een eigen, opvallende stijl
(niet `muted` zoals de gewone entry-zone-suggestie — dit moet duidelijk
anders ogen):

```html
{% if entry.sniper_entry_price is defined and entry.sniper_entry_price is not none %}
<div class="signal-card-sniper">
  🎯 Sniper: {{ "%.4f"|format(entry.sniper_entry_price) }}
  <span class="muted">— {{ entry.sniper_reason }}</span>
</div>
{% endif %}
```

Nieuwe CSS-klasse `.signal-card-sniper` in `style.css`: duidelijk visueel
onderscheiden van de rest van de kaart (bijvoorbeeld een subtiele gouden/
amber accentkleur en linkerrand, niet het bestaande groen van
`is-confirmed` — sniper is een ander soort signaal, geen hogere
kansberekening).

**Pushmelding:** vijf `make_body`-closures bouwen vandaag elk hun eigen
pushtekst, geen gedeelde functie — allemaal krijgen dezelfde extra regel
als `sniper_entry_price` niet `None` is:
- `signal_processor.py::process_day_trading_signal` (heeft al
  `entry_zone_note`, rond regel 1138)
- `signal_processor.py`'s signaal-ververs-pad (heeft al `entry_zone_note`,
  rond regel 1261)
- `market_scanner.py::_find_breakout_retest_candidate`'s `_breakout_body`
  (regel ~181) — bouwt vandaag GEEN entry-zone-tekst, alleen entry/stop/
  take profit; dit is de eerste entry-gerelateerde tekst die deze
  make_body krijgt
- `market_scanner.py::_find_trendline_retest_candidate`'s `_trendline_body`
- `market_scanner.py::_find_chart_pattern_candidate`'s `_pattern_body`

Toegevoegde regel, overal hetzelfde format:

```
🎯 Sniper: {price:.4f} — {reason}
```

Los van de bestaande "Mogelijk betere entry"-regel in de twee
`signal_processor.py`-paden (die blijft ongewijzigd voor signalen zonder
sweep); de drie `market_scanner.py`-paden krijgen dus voor het eerst een
entry-gerelateerde regel in hun pushtekst, maar alleen wanneer er
daadwerkelijk een sweep is — geen tekst als `sniper_entry_price` `None`
is, dus geen verandering voor de meeste bestaande meldingen.

## Component 3 — het wachtmechanisme

`level_check.py::check_pending_signals()` krijgt een vierde, hoogst-
prioriteit situatie, vóór de bestaande `in_entry_zone`-check. Op dit
moment haalt die functie per coin alleen `exchange.fetch_last_price` op;
voor de sniper-check is er een candle-window nodig, dus per coin (waar nog
geen sniper-trigger gevonden is deze cyclus) ook `exchange.fetch_ohlcv`
ophalen — dezelfde aanroep die `market_scanner.py` en
`signal_processor.py` al elders doen, geen nieuw patroon.

Net als de bestaande `coin_prices`-cache in deze functie (één
`fetch_last_price` per coin, hergebruikt over meerdere pending regels van
verschillende gebruikers op dezelfde coin): een nieuwe `coin_sniper`-cache
van hetzelfde soort, zodat twee gebruikers met een pending signaal op
dezelfde coin niet allebei hun eigen `fetch_ohlcv` triggeren. Gekeyed op
`(coin, direction)`, niet alleen `coin` — twee pending regels op dezelfde
coin kunnen in theorie tegenovergestelde richtingen hebben (bv. een
patroon-short naast een dagtrading-long die nog beide wachten), en
`find_sniper_entry_price` is richtingsafhankelijk. Zelfde soort
tuple-key-precedent als de bestaande `coin_levels`-cache verderop in deze
functie (`(message_id, coin)`).

```python
if entry["sniper_entry_price"] is None:  # nog niet gevonden bij aanmaak
    cache_key = (coin, entry["direction"])
    if cache_key not in coin_sniper:
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            coin_sniper[cache_key] = indicators.find_sniper_entry_price(entry["direction"], df)
        except Exception:
            logger.exception("Kon geen candles ophalen voor sniper-check op %s, sla over", coin)
            coin_sniper[cache_key] = None
    sniper = coin_sniper[cache_key]
else:
    sniper = None  # al getoond bij aanmaak, geen dubbele proactieve melding nodig
```

Bij een treffer: dezelfde bestaande `journal_entries.level_alert_sent`-vlag
(`repo.mark_level_alert_sent`) wordt gebruikt — geen nieuwe kolom, geen
nieuwe tabel. Dit is bewust dezelfde "één keer per pending regel"-vlag als
de drie bestaande proactieve situaties: een sniper-trigger telt als
dezelfde soort eenmalige nudge, en voorkomt dat een coin binnen één cyclus
zowel een sniper- als een gewone niveau-melding krijgt.

```
🎯 {coin} {richting} — sniper-trigger geraakt op {price:.4f}
{reason}
```

heeft voorrang op de bestaande "Terug in de betere-entry-zone" / "Terug
bij een interessant niveau" — als de sniper-conditie deze cyclus raak is,
wordt alleen die gemeld, niet allebei.

## Foutafhandeling

- `find_sniper_entry_price` faalt nooit hard: dezelfde
  try/except-structuur als de rest van `compute_advanced_extra_factors`
  (een ontbrekende sweep is gewoon `None`, geen uitzonderlijke situatie).
- Een mislukte `fetch_ohlcv` in `check_pending_signals` voor de
  sniper-check volgt dezelfde `except Exception: logger.exception(...);
  continue`-aanpak als de bestaande `fetch_last_price`-aanroep erboven —
  één coin die faalt blokkeert de rest van de cyclus niet.

## Testen

Geen pytest-suite in dit project (zie CLAUDE.md) — verificatie via
throwaway scripts tegen een scratch-database, zoals de rest van deze
sessie:
- `find_sniper_entry_price`: synthetische OHLCV met een handmatig
  geconstrueerde sweep-candle (zelfde aanpak als de eerdere
  `find_forming_wedge`-tests deze sessie), long en short, en het
  None-pad zonder sweep.
- `insert_signal`/`_JOURNAL_SELECT`: scratch-DB round-trip, sniper-velden
  moeten door de hele keten heen bewaard blijven tot op de signaalkaart.
- `check_pending_signals`: gemockte `exchange.fetch_ohlcv` die een sweep
  oplevert, controleren dat de proactieve melding vuurt en
  `level_alert_sent` op 1 komt te staan, en dat een tweede cyclus daarna
  niet nogmaals meldt.
- Handmatige Playwright-check van de signaalkaart (`.signal-card-sniper`
  zichtbaar, duidelijk onderscheiden van de rest) op zowel /signalen als
  /coins/{symbol}.
