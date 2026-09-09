# Automatische steun/weerstand-zones — ontwerp

## Aanleiding

Dit is het derde deelproject van de "vernieuwing van patroonherkenning en
duidelijkheid in de grafiek"-reeks. De eerste twee zijn al klaar:
factor-verfijningen (ADX-richting, Volume-percentiel, RSI 1u) en
candlestick-patroonherkenning (zie
`docs/superpowers/specs/2026-09-09-candlestick-patronen-design.md`).

Beide eerdere deelprojecten verbeterden de vertrouwen-score. Geen van
beide raakt waar een trade daadwerkelijk in- en uitstapt. De gebruiker
gaf expliciet aan dat een goede entry vinden "heel moeilijk en belangrijk"
is. Dit deelproject pakt dat rechtstreeks aan: HesPulse herkent zelf, puur
uit de candle-geschiedenis, waar de prijs al meerdere keren gekeerd is
(structurele steun/weerstand), en gebruikt dat zowel om de voorgestelde
stop loss/take profit te verscherpen als om een nieuwe score-factor te
vullen.

Community-niveaus (`SourceLevel`/`pattern_name`, puur tekst overgenomen
uit een Discord-bericht) bestaan al en blijven ongewijzigd. Dit
deelproject voegt een tweede, onafhankelijke bron van niveaus toe: niet
wat de bron zei, maar wat de candles zelf laten zien.

## Niet-doelen

- Geen database-opslag. Zones worden live berekend uit de al opgehaalde
  4h candle-data, net als de candlestick-patronen. Niets nieuws in
  `schema.sql`, geen migratie.
- Geen wijziging aan de swing-toets (`evaluate_level_watch`,
  `compute_stop_take_from_levels` voor community-niveaus). Die blijft
  precies zoals hij is; dit deelproject raakt alleen het day-trading pad
  (`process_day_trading_signal`).
- Geen aparte steun- versus weerstand-classificatie. Eén zone werkt als
  steun als de prijs er van boven op afkomt, als weerstand van onderaf —
  precies zoals in de praktijk. Geen aparte detectielogica per rol.
- Geen wijziging aan `CONFIRM_THRESHOLD` (blijft 60%) of aan hoe de
  bestaande tien factoren werken. Er komt één factor bij.
- Geen daily-candle zone-detectie. Alleen 4h, dezelfde horizon als de
  rest van de day-trading toetsing, geen extra candle-fetch nodig.

## Sectie 1: Detectie (`app/indicators.py`)

Twee stappen: pivot-punten zoeken, dan clusteren tot zones.

**Nieuwe constanten:**

```python
# Hoeveel candles aan elke kant moeten "lager" (voor een pivot-high) of
# "hoger" (voor een pivot-low) zijn, wil een candle als lokaal keerpunt
# tellen. 3 is streng genoeg om ruis (elke kleine schommeling) niet als
# keerpunt te zien, maar laat genoeg pivots over op de laatste 100
# candles om zinvol te kunnen clusteren.
SR_PIVOT_WINDOW = 3

# Hoeveel candles terug de zone-detectie meeneemt. Ruim genoeg voor
# meerdere testen van dezelfde zone, niet zo ruim dat een allang niet meer
# relevant niveau van maanden geleden nog meetelt.
SR_ZONE_LOOKBACK = 100

# Hoe dicht twee pivot-prijzen bij elkaar moeten liggen (als fractie van
# de prijs) om tot dezelfde zone te horen. Te klein: elke pivot wordt zijn
# eigen "zone" van 1 punt, nooit genoeg touches. Te groot: totaal
# ongerelateerde niveaus versmelten tot één onbruikbaar brede band.
SR_ZONE_CLUSTER_TOLERANCE_PCT = 0.005

# Minimaal aantal pivots in een cluster om als echte zone te tellen. Eén
# pivot is geen patroon, twee is het begin van "de prijs kwam hier al
# eerder terug".
SR_ZONE_MIN_TOUCHES = 2
```

**Nieuwe dataclass en functie:**

```python
@dataclass
class SRZone:
    price_low: float
    price_high: float
    touches: int


def detect_sr_zones(df: pd.DataFrame, lookback: int = SR_ZONE_LOOKBACK) -> list[SRZone]:
    """Vindt structurele steun/weerstand-zones in de laatste `lookback`
    candles: eerst lokale keerpunten (pivot-highs/-lows, een candle die
    hoger/lager is dan SR_PIVOT_WINDOW candles aan beide kanten), daarna
    geclusterd tot zones (pivots binnen SR_ZONE_CLUSTER_TOLERANCE_PCT van
    elkaar horen bij dezelfde zone). Een zone telt pas mee vanaf
    SR_ZONE_MIN_TOUCHES pivots. Geen aparte steun/weerstand-classificatie:
    dezelfde zone kan beide rollen spelen afhankelijk van de kant waar de
    prijs vandaan komt, dat wordt pas bij gebruik (risk.py, de score-
    factor) bepaald aan de hand van de huidige prijs."""
    window = df.tail(lookback).reset_index(drop=True)
    n = len(window)
    pivots: list[float] = []

    for i in range(SR_PIVOT_WINDOW, n - SR_PIVOT_WINDOW):
        high_i = window["high"].iloc[i]
        low_i = window["low"].iloc[i]
        left_highs = window["high"].iloc[i - SR_PIVOT_WINDOW:i]
        right_highs = window["high"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if high_i > left_highs.max() and high_i > right_highs.max():
            pivots.append(float(high_i))
        left_lows = window["low"].iloc[i - SR_PIVOT_WINDOW:i]
        right_lows = window["low"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if low_i < left_lows.min() and low_i < right_lows.min():
            pivots.append(float(low_i))

    if not pivots:
        return []

    pivots.sort()
    clusters: list[list[float]] = [[pivots[0]]]
    for price in pivots[1:]:
        cluster_high = clusters[-1][-1]
        if price <= cluster_high * (1 + SR_ZONE_CLUSTER_TOLERANCE_PCT):
            clusters[-1].append(price)
        else:
            clusters.append([price])

    return [
        SRZone(price_low=min(c), price_high=max(c), touches=len(c))
        for c in clusters
        if len(c) >= SR_ZONE_MIN_TOUCHES
    ]
```

**Nieuwe factor-functie**, in dezelfde vorm als de andere `check_*`-functies:

```python
# Hoe ver een zone maximaal van de entry mag liggen (in ATR) om nog als
# kandidaat te tellen voor de stop/take-verfijning en deze factor. Een
# zone die zes keer de ATR verderop ligt is geen realistisch punt meer
# voor déze trade, ook al is de zone zelf sterk.
SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE = 6.0


def check_sr_zone(direction: str, entry_price: float, atr: float, zones: list[SRZone]) -> tuple[str, bool, str]:
    """Is er een bruikbare zone aan de stop-kant van de prijs (onder de
    entry bij long, erboven bij short) binnen SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE
    x ATR? Zelfde kant-bepaling als risk.compute_stop_take_from_levels
    gebruikt voor community-niveaus, hier toegepast op zelf-gedetecteerde
    zones. Geen aparte richting-afhankelijke detectie nodig: een zone is
    een zone, welke kant hem "steun" maakt hangt puur af van waar de
    entry-prijs zit."""
    direction = direction.lower()
    max_distance = SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * atr
    edges = [edge for zone in zones for edge in (zone.price_low, zone.price_high)]

    if direction == "long":
        candidates = [e for e in edges if e < entry_price and entry_price - e <= max_distance]
    else:
        candidates = [e for e in edges if e > entry_price and e - entry_price <= max_distance]

    if not candidates:
        return ("Steun/weerstand", False, "geen zone dichtbij genoeg voor een bruikbaar niveau")

    nearest = max(candidates) if direction == "long" else min(candidates)
    distance_atr = abs(entry_price - nearest) / atr if atr else 0.0
    return ("Steun/weerstand", True, f"zone op {distance_atr:.1f}x ATR afstand")
```

## Sectie 2: Entry/stop/take verfijnen (`app/signal_processor.py`)

`process_day_trading_signal` (rond regel 592-611) roept nu al
`risk.compute_stop_take_from_levels` aan zodra er community-niveaus
(`message_levels`) voor dit specifieke bericht zijn, anders
`risk.compute_stop_take`. Die functie is al precies gebouwd om een platte
lijst prijsniveaus te nemen, het dichtstbijzijnde bruikbare niveau aan
elke kant te kiezen, en terug te vallen op de ATR-berekening als er niets
bruikbaars is — inclusief een minimumafstand-check
(`MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION`) tegen een belachelijk kleine
stop. Zelf-gedetecteerde zones hoeven deze logica dus niet te herhalen,
ze leveren alleen extra kandidaat-niveaus.

Nieuw: `detect_sr_zones(df)` wordt altijd berekend (niet alleen als er
message_levels zijn), en de zone-randen binnen
`SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE x ATR` worden toegevoegd aan
`message_levels` vóór de aanroep van `compute_stop_take_from_levels`.
Community-niveaus en zelf-gedetecteerde zones staan zo in dezelfde lijst;
`compute_stop_take_from_levels` kiest gewoon het dichtstbijzijnde
bruikbare niveau, ongeacht de bron. Dat is bewust: een screenshot-niveau
en een zelf-gedetecteerde zone zijn voor de stop-berekening evenwaardig,
alleen "hoe dichtbij en bruikbaar" telt.

```python
zones = indicators.detect_sr_zones(df)
zone_levels = [
    edge for zone in zones for edge in (zone.price_low, zone.price_high)
    if abs(edge - ind.price) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
]
message_levels = [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id)]
combined_levels = message_levels + zone_levels
if combined_levels:
    stop_take = risk.compute_stop_take_from_levels(
        interp.direction, ind.price, ind.atr, combined_levels, swing_low=swing_low, swing_high=swing_high,
    )
else:
    stop_take = risk.compute_stop_take(
        interp.direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high,
    )
```

Geen zone binnen bereik en geen community-niveaus: `combined_levels` is
leeg, exact het huidige pad blijft ongewijzigd draaien.

## Sectie 3: Score-factor

`compute_advanced_extra_factors` (async, berekent nu al BTC-trend/
Daily-trend/1u bevestiging/RSI 1u/Divergentie/Candlepatroon/Liquiditeit)
krijgt er één losse, synchrone check bij: `indicators.check_sr_zone(direction, ind.price, ind.atr, zones)`,
met dezelfde `zones` die net voor de stop/take-berekening al berekend
zijn — geen dubbel werk. Zelfde fail-closed try/except-patroon als de
andere factoren in die functie.

Van 10 naar 11 geavanceerde factoren, van 14 naar 15 totaal.
`CONFIRM_THRESHOLD` blijft 60%.

## Sectie 4: Grafiek (`web/main.py`, `web/static/coin.js`, `web/templates/coin.html`)

`/api/candles/{symbol}` krijgt een nieuw veld `sr_zones`: een lijst
`{"price_low": float, "price_high": float, "touches": int}`, rechtstreeks
uit `indicators.detect_sr_zones(df)` — geen index-naar-tijd-mapping nodig
zoals bij `patterns`, een zone is een prijsband, geen tijdstip.

`coin.js` tekent elke zone als vlak, doorzichtig blok over de volle
breedte van de grafiek, in dezelfde stijl als de bestaande
`zoneGroups`-logica voor community-niveaus (twee bij elkaar horende
niveaus die al als blok getekend worden), maar in een eigen kleur zodat
zelf-gedetecteerde zones te onderscheiden zijn van community-niveaus.
Sterkte (`touches`) staat in een klein label op de zone of in een tooltip
bij hover — geen aparte lijst nodig zoals bij de candlestick-patronen, een
zone is zelf al zichtbaar genoeg als vlak in plaats van een punt-marker.

## Zelf-review

**Niet-doelen nageleefd**: geen database-wijziging, swing-toets
ongewijzigd, geen aparte steun/weerstand-classificatie, drempel
ongewijzigd, alleen 4h.

**Hergebruik in plaats van duplicatie**: de stop/take-selectielogica
(dichtstbijzijnde bruikbare niveau per kant, minimumafstand-guard,
fallback naar ATR) wordt niet opnieuw geschreven voor zones — zones
worden platte kandidaat-niveaus die de al bestaande, al geteste
`compute_stop_take_from_levels` binnengaan. Dit is een correctie tijdens
het schrijven van deze spec op wat in de brainstorm-sectie werd
voorgesteld ("nieuwe ATR-marge-logica in risk.py"): die logica bestond
al, alleen hergebruiken was nodig. Het gebruikersgerichte gedrag (zone
binnen bereik verscherpt stop/take, anders ongewijzigde ATR-berekening,
harde ondergrens tegen een te kleine stop) is exact wat besproken en
goedgekeurd is, alleen de implementatieroute is directer.

**Community-niveaus en zelf-gedetecteerde zones samengevoegd** in plaats
van zones alleen als fallback te gebruiken wanneer er geen
community-niveaus zijn: zo verbetert elke day-trading melding een
mogelijke entry, niet alleen de meldingen waarvan de bron toevallig een
screenshot met zichtbare niveaus deelde. Beide bronnen zijn voor de
stop/take-berekening gelijkwaardig, `compute_stop_take_from_levels` kiest
toch al puur op afstand, niet op bron.

**Scope**: één nieuwe detectiefunctie, één nieuwe factor-functie, een
kleine wijziging aan één call-site in signal_processor.py, één nieuw
API-veld, één nieuwe grafiek-laag. Past in één implementatieplan.
