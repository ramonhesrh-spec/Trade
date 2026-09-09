# Candlestick-patroonherkenning uitbreiden + zichtbaar op de grafiek — ontwerp

## Aanleiding

HesPulse herkent op dit moment precies één candlestick-patroon zelf:
bullish/bearish engulfing (`app/indicators.py:check_candle_pattern`, deze
sessie toegevoegd als één van de tien geavanceerde factoren). Alle andere
"patronen" die de gebruiker op het dashboard ziet komen van de community
zelf: `pattern_name` is vrije tekst die de AI overneemt uit het Discord-
bericht (bijvoorbeeld "double bottom"), gekoppeld aan een prijsniveau.
HesPulse beoordeelt zelf niets aan die tekst.

Twee losstaande klachten liggen hieraan ten grondslag: (1) HesPulse
herkent zelf te weinig candlestick-patronen naast engulfing, en (2) wat er
wél herkend wordt is niet duidelijk zichtbaar op de coin-grafiek zelf —
community-niveaus staan als naamloze gestippelde lijn, met de uitleg pas
in de tabel eronder.

Dit is het eerste van drie deelprojecten die samen "vernieuwing van
patroonherkenning en duidelijkheid in de grafiek" vormen. De twee andere
(klassieke chart-patronen zoals double bottom/head-and-shoulders via
pivot-detectie, en automatisch herkende steun/weerstand-zones) volgen
later, elk met hun eigen spec. Dit deelproject bouwt niets voor die twee
voor — het legt wel de marker-conventie op de grafiek vast die ze later
kunnen hergebruiken.

## Niet-doelen

- Geen klassieke chart-patronen (double bottom, head-and-shoulders,
  driehoeken, wiggen). Die vereisen pivot-detectie over tientallen
  candles, een andere aanpak, en komen in een volgende spec.
- Geen automatische steun/weerstand-zone-detectie. Community-niveaus
  (`pattern_name`, `source_levels`) blijven ongewijzigd de enige bron voor
  horizontale niveaus op de grafiek.
- Geen algemene opschoning van de grafiek (kleuren, legenda, hoeveel
  lijnen tegelijk zichtbaar zijn). Dat is een apart deelproject.
- Geen wijziging aan hoeveel factoren meetellen of aan `CONFIRM_THRESHOLD`.
  De vijf nieuwe patronen smelten samen met het bestaande engulfing in de
  al bestaande factor **Candlepatroon** — nog steeds één van de tien
  geavanceerde factoren, geen 14 wordt geen 18.
- Geen backfill-script voor bestaande signalen. De uitgebreide
  `check_candle_pattern` gaat vanaf nu meetellen (net als elke eerdere
  factor-uitbreiding deze sessie), oude signalen in de database blijven
  ongewijzigd staan met hun oude reason-breakdown.
- Geen database-migratie. Patronen op de grafiek worden live berekend uit
  de al opgehaalde candle-data, niets wordt opgeslagen.

## Sectie 1: Patroondetectie (`app/indicators.py`)

Vijf nieuwe detectiefuncties naast de bestaande engulfing-logica, allemaal
pure functies op een OHLC-rij (of een klein venster eromheen), geen
database, geen netwerk. Namen blijven in het internationale
vaktermen-Engels, zoals nu ook al bij "bullish/bearish engulfing" — elke
trader kent deze termen, een vertaling zou verwarrender zijn dan
verhelderend.

**Body/schaduw-ratio's** (nieuwe constanten, in dezelfde stijl als
`ADX_MIN`/`ATR_TOLERANCE`):

```python
# Hoe lang de "staart" van een hamer/hangende man/vallende ster/omgekeerde
# hamer minimaal moet zijn t.o.v. het candle-lichaam, om als duidelijk
# patroon te tellen in plaats van een gewone candle met iets meer schaduw
# dan gemiddeld.
HAMMER_SHADOW_RATIO = 2.0

# Hoe klein de schaduw aan de ANDERE kant van het lichaam moet blijven
# (t.o.v. het lichaam zelf), zodat een candle met twee lange schaduwen
# (spinning top) niet per ongeluk als hamer of ster telt.
HAMMER_OPPOSITE_SHADOW_MAX_RATIO = 0.5

# Hoe klein het lichaam moet zijn t.o.v. de volledige candle-range
# (high - low) om als doji te tellen.
DOJI_BODY_MAX_RATIO = 0.1
```

**Trendcontext.** Hamer/hangende man, vallende ster/omgekeerde hamer, en
doji zijn alleen zinvol als omkeersignaal ná een duidelijke trend — een
hamer in een zijwaartse markt betekent niets. `detect_single_candle_patterns`
krijgt daarom de al berekende volledige EMA9/EMA21-reeksen mee (dezelfde
reeksen die `ema_series()` al voor de grafiek berekent, dus geen extra
rekenwerk) en bepaalt de trend vlak vóór de candle door `ema9[i-1]` tegen
`ema21[i-1]` af te zetten — exact dezelfde vergelijking als de bestaande
basisfactor Trend, alleen op een eerder punt in de reeks. Zonder duidelijke
voorafgaande trend (of te weinig candles ervoor) telt de candle simpelweg
niet mee als patroon, net zoals nu al met te-korte-historie omgegaan wordt
in `check_divergence`.

**Nieuwe functie:**

```python
def detect_single_candle_patterns(
    df: pd.DataFrame, index: int, ema9_series: list[float], ema21_series: list[float],
) -> list[tuple[str, str]]:
    """Alle single-candle patronen (Hammer, Hanging Man, Shooting Star,
    Inverted Hammer, Doji) op de candle op `index`, elk als (naam, richting)
    met richting 'bullish' of 'bearish'. Een candle kan meerdere patronen
    tegelijk matchen (zeldzaam maar mogelijk bij grensgevallen); de aanroeper
    beslist wat daarmee gebeurt. Retourneert een lege lijst als er te weinig
    voorafgaande candles zijn om de trend te bepalen, of als niets matcht."""
```

Logica per patroon (candle op `index`, `body = |close - open|`,
`upper_shadow = high - max(open, close)`, `lower_shadow = min(open, close) - low`,
`candle_range = high - low`, trend via `ema9[index-1] > ema21[index-1]`):

- **Hammer** (bullish): `lower_shadow >= body * HAMMER_SHADOW_RATIO` en
  `upper_shadow <= body * HAMMER_OPPOSITE_SHADOW_MAX_RATIO` en trend vóór
  de candle was dalend (`ema9[index-1] < ema21[index-1]`).
- **Hanging Man** (bearish): zelfde vorm als Hammer, maar trend vóór de
  candle was stijgend.
- **Shooting Star** (bearish): `upper_shadow >= body * HAMMER_SHADOW_RATIO`
  en `lower_shadow <= body * HAMMER_OPPOSITE_SHADOW_MAX_RATIO` en trend
  vóór de candle was stijgend.
- **Inverted Hammer** (bullish): zelfde vorm als Shooting Star, maar trend
  vóór de candle was dalend.
- **Doji** (richting afhankelijk van context): `body <= candle_range * DOJI_BODY_MAX_RATIO`.
  Trend vóór de candle stijgend → bearish (mogelijke omkeer naar beneden).
  Trend vóór de candle dalend → bullish. Geen duidelijke trend (te weinig
  candles, of `ema9[index-1] == ema21[index-1]`) → geen match.
- Een `candle_range` van 0 (open=high=low=close, kan bij illiquide data
  voorkomen) levert nergens een deling door nul op: de shadow-checks falen
  dan vanzelf (0 >= body * ratio is alleen waar als body ook 0 is, en dan
  is het geen bruikbaar patroon) en de doji-check gebruikt `candle_range`
  alleen in een vermenigvuldiging, nooit als deler.

```python
def detect_star_pattern(df: pd.DataFrame, index: int) -> Optional[tuple[str, str]]:
    """Morning Star (bullish) of Evening Star (bearish) op de candles
    index-2, index-1, index. None als er geen 3-candle sterpatroon matcht
    of als index < 2."""
```

- **Morning Star**: candle `index-2` een duidelijk bearish candle (body
  minstens gemiddeld voor de laatste 20 candles, hergebruikt via dezelfde
  soort vergelijking als `ATR_TOLERANCE`), candle `index-1` een kleine
  candle (body `<= DOJI_BODY_MAX_RATIO * 3` van de range van candle
  `index-2`, een indecisie-candle), candle `index` een duidelijk bullish
  candle die sluit boven het middelpunt van het lichaam van candle
  `index-2`.
- **Evening Star**: spiegelbeeld.

**Bestaande `check_candle_pattern` (engulfing) blijft ongewijzigd** als
losse functie — engulfing heeft zijn eigen vorm-logica en hoeft niet
samengevoegd te worden met de single-candle/star detectoren om hetzelfde
eindresultaat te bereiken.

**Samenvoegende functie voor de score:**

```python
def check_candle_pattern_extended(
    df: pd.DataFrame, direction: str, ema9_series: list[float], ema21_series: list[float],
) -> tuple[str, bool, str]:
    """Vervangt de aanroep van het bestaande check_candle_pattern in
    compute_advanced_extra_factors. Controleert engulfing (bestaande
    check_candle_pattern) plus alle vijf nieuwe patronen op de laatste
    candle, en telt de factor als gehaald zodra ÉÉN ervan matcht in de
    kant van `direction`. Blijft de bestaande factornaam 'Candlepatroon'
    gebruiken; de breakdown-tekst noemt welk patroon specifiek matchte."""
```

**Historische scan voor de grafiek:**

```python
DEFAULT_PATTERN_SCAN_LOOKBACK = 100

def scan_candle_patterns(
    df: pd.DataFrame, ema9_series: list[float], ema21_series: list[float],
    lookback: int = DEFAULT_PATTERN_SCAN_LOOKBACK,
) -> list[dict]:
    """Alle single-candle- en sterpatronen over de laatste `lookback`
    candles, ELK gevonden patroon (niet gefilterd op een verwachte
    richting — dit is voor weergave, niet voor de score). Elk element:
    {"index": int, "pattern": str, "direction": "bullish"|"bearish"}."""
```

## Sectie 2: Scorekoppeling (`app/signal_processor.py`)

`compute_advanced_extra_factors` roept nu `indicators.check_candle_pattern(df, direction)`
aan (regel ~547 na de vorige sessie's wijziging). Dat wordt
`indicators.check_candle_pattern_extended(df, direction, ema9_series, ema21_series)`.
`ema9_series`/`ema21_series` worden berekend via de al bestaande
`indicators.ema_series(df)` — één extra aanroep, geen extra candle-fetch.
De rest van `compute_advanced_extra_factors` (try/except, fail-closed bij
fouten, plek in de factor-lijst) blijft ongewijzigd: dezelfde factornaam
"Candlepatroon", dezelfde plek in de breakdown.

## Sectie 3: Grafiek-API (`web/main.py`, route `/api/candles/{symbol}`)

Huidige response: `{"candles": [...], "ema9": [...], "ema21": [...]}`.
`ema9`/`ema21` worden al berekend uit `indicators.ema_series(df)` op de
volledige opgehaalde 200 candles (regel 1382). Nieuw: na die berekening
`indicators.scan_candle_patterns(df, ema9_raw, ema21_raw)` aanroepen (de
ruwe series vóór ze tot `{"time", "value"}`-dicts omgezet worden — de
scan-functie werkt op candle-index, niet op tijd) en het resultaat
mappen naar candle-tijden:

```python
patterns = [
    {"time": candles[p["index"]]["time"], "pattern": p["pattern"], "direction": p["direction"]}
    for p in indicators.scan_candle_patterns(df, ema9_raw, ema21_raw)
]
```

Response wordt `{"candles": [...], "ema9": [...], "ema21": [...], "patterns": [...]}`.

## Sectie 4: Grafiek-weergave (`web/static/coin.js`, `web/templates/coin.html`)

**Markers.** `candleSeries.setMarkers()` vervángt de volledige markerlijst
bij elke aanroep (dat gebeurt nu al bij de narrative-markers, en de
trendlijn-tekentool moet daarom expliciet de narrative-markers herstellen
na zijn eigen tijdelijke marker). Patroon-markers moeten daarom in
dezelfde array gemerged worden vóór `setMarkers()` aangeroepen wordt, niet
in een aparte aanroep — anders verdwijnen de narrative-markers of de
patroon-markers stilzwijgend van elkaar.

```javascript
const patternMarkers = (data.patterns || []).map((p) => ({
  time: p.time,
  position: p.direction === "bullish" ? "belowBar" : "aboveBar",
  color: p.direction === "bullish" ? "#33d69f" : "#f2685c",
  shape: "circle",
  text: "", // geen tekst op de grafiek zelf, zie de lijst eronder
}));
const allMarkers = [...narrativeMarkers, ...patternMarkers].sort((a, b) => a.time - b.time);
candleSeries.setMarkers(allMarkers);
```

Kleur en positie volgen dezelfde conventie als de rest van de grafiek:
groen/onder voor bullish, rood/boven voor bearish (zelfde kleuren als de
bestaande stop-loss/take-profit-lijnen). Geen tekst ín de marker (een
cirkel met tekst erin wordt onleesbaar klein) — de naam staat in de lijst
eronder.

**Lijst onder de grafiek**, in dezelfde structuur als de bestaande
bron-niveaus-tabel (`web/templates/coin.html:175-186`): een nieuwe sectie
"Herkende patronen" die de laatste paar gevonden patronen toont (naam,
richting, tijdstip), client-side gevuld vanuit `data.patterns` — geen
aparte server-route nodig, dezelfde data die de markers al gebruiken.

## Sectie 5: Backtest + uitleg-pagina

`scripts/backtest_factors.py`: de regel die nu `indicators.check_candle_pattern(df, direction)`
aanroept wordt `indicators.check_candle_pattern_extended(...)`, zelfde
patroon als deze sessie al bij de vorige factor-uitbreiding is toegepast.

`/uitleg` (`web/templates/uitleg.html`): de factor-kaart "Candlepatroon"
in de lijst van tien geavanceerde factoren krijgt bijgewerkte tekst die
alle zes patronen noemt (engulfing + de vijf nieuwe), in plaats van alleen
engulfing.

## Zelf-review

**Niet-doelen nageleefd**: geen database-migratie, geen wijziging aan het
aantal factoren of de drempel, geen chart-patronen/S+R-zones, geen
backfill.

**Interne consistentie**: `check_candle_pattern` (bestaand, engulfing-only)
blijft bestaan en ongewijzigd; `check_candle_pattern_extended` is de enige
plek die hem aanroept en combineert met de nieuwe detectoren, dus geen
dubbele engulfing-logica.

**Bekend technisch risico expliciet gemaakt**: `setMarkers()` vervangt in
plaats van toevoegt — de spec dwingt de merge-volgorde af in Sectie 4 zodat
narrative- en patroonmarkers elkaar niet stilzwijgend wegvegen, in plaats
van dat dit pas bij implementatie ontdekt wordt.

**Scope**: vijf nieuwe patronen, één bestaande factor blijft één factor,
één API-veld erbij, één nieuwe grafiek-sectie. Past in één
implementatieplan; geen verdere opsplitsing nodig.
