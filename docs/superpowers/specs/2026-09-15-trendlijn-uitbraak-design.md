# Trendlijn-uitbraak-en-terugtest — ontwerp

## Aanleiding

De gebruiker liet een chart zien (XRPUSDT, 4h) met een dalende driehoek:
twee convergerende trendlijnen, prijs bij de apex, een korte uitbraak
boven de bovenlijn die meteen terugviel (fakeout). Vraag: houdt HesPulse
dit soort patronen zelf in de gaten?

Antwoord op dat moment: nee. `detect_sr_zones` (app/indicators.py) en
`find_breakout_retest` ("optie C", zie
`docs/superpowers/specs/2026-09-09-steun-weerstand-zones-design.md` en de
latere marktscan-koppeling) herkennen alleen horizontale steun/weerstand.
Een schuin lopende trendlijn, zoals de bovenkant van een driehoek, valt
daar niet onder.

Dit deelproject voegt diagonale trendlijn-detectie toe, met exact
dezelfde striktheid als optie C nu al heeft (uitbraak op closing-prijs,
sindsdien niet teruggevallen) — de gebruiker was daar expliciet over:
"moet wel perfect worden. zonder fake outs idd". Honderd procent zonder
fakeouts kan geen enkel systeem beloven; wat wel kan is dezelfde
bewezen striktheid toepassen die optie C al heeft, niet losser.

## Niet-doelen

- Geen detectie van complete driehoekpatronen (twee lijnen samen,
  convergentie, apex). Dit deelproject herkent één diagonale lijn
  tegelijk (steun óf weerstand). Een driehoek toont zich dan vanzelf als
  twee losse gemelde lijnen, maar wordt niet als zodanig herkend of
  benoemd. Expliciet gekozen boven volledige driehoekherkenning: een
  stuk eenvoudiger te toetsen, en dekt het aanleiding-voorbeeld al af
  (elke kant van een driehoek is zo'n lijn).
- Geen nieuwe score-factor in `confirms_direction`/`basic_factors`. Zelfde
  keuze als optie C: een los Telegram-kanaal, geen invloed op de
  bestaande vertrouwen-score. Voorkomt onbedoelde neveneffecten op
  signalen die al werken.
- Geen database-opslag van de lijn zelf. Live herberekend uit de candle-
  data, net als `detect_sr_zones`. Wel één nieuwe kolom voor de dedup-key
  (zie sectie 3), zelfde patroon als `coins.last_breakout_retest_key`.
- Geen wijziging aan de bestaande horizontale zone-detectie of optie C.
  Dit deelproject komt ernaast, niet in de plaats van.

## Sectie 1: Gedeelde pivot-detectie (`app/indicators.py`)

`detect_sr_zones` bepaalt nu zelf pivot-highs/-lows binnen zijn eigen
functie-body. De nieuwe trendlijn-detectie heeft exact dezelfde
pivot-punten nodig (index + prijs, niet alleen prijs zoals
`detect_sr_zones` nu teruggeeft). In plaats van die logica te dupliceren,
wordt ze in een gedeelde helper getrokken:

```python
@dataclass
class Pivot:
    index: int
    price: float
    kind: str  # "high" of "low"


def _find_pivots(window: pd.DataFrame) -> list[Pivot]:
    """Lokale keerpunten in een candle-venster: een candle die hoger/lager
    is dan SR_PIVOT_WINDOW candles aan beide kanten. Gedeeld tussen
    detect_sr_zones (clustert op prijs, index niet nodig) en
    detect_trendlines (past een lijn door index+prijs), zodat de
    pivot-definitie één keer bestaat."""
    n = len(window)
    pivots: list[Pivot] = []
    for i in range(SR_PIVOT_WINDOW, n - SR_PIVOT_WINDOW):
        high_i = window["high"].iloc[i]
        low_i = window["low"].iloc[i]
        left_highs = window["high"].iloc[i - SR_PIVOT_WINDOW:i]
        right_highs = window["high"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if high_i > left_highs.max() and high_i > right_highs.max():
            pivots.append(Pivot(index=i, price=float(high_i), kind="high"))
        left_lows = window["low"].iloc[i - SR_PIVOT_WINDOW:i]
        right_lows = window["low"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if low_i < left_lows.min() and low_i < right_lows.min():
            pivots.append(Pivot(index=i, price=float(low_i), kind="low"))
    return pivots
```

`detect_sr_zones` wordt herschreven om `_find_pivots` te gebruiken
(`pivots = [p.price for p in _find_pivots(window)]`, de rest van de
functie blijft ongewijzigd) in plaats van zijn eigen kopie van deze
loop.

## Sectie 2: Trendlijn-detectie (`app/indicators.py`)

**Nieuwe constanten:**

```python
# Minimaal aantal pivots dat op de lijn moet liggen (de twee punten die
# hem vastleggen niet meegerekend zijn dat nog "geen bewijs", zie
# TRENDLINE_FIT_TOLERANCE_PCT hieronder) voor hij als echte trendlijn
# telt, niet toeval. Strenger dan SR_ZONE_MIN_TOUCHES (2): een schuine
# lijn door twee punten legt geen enkele relatie vast, een derde
# bevestigende pivot wel.
TRENDLINE_MIN_TOUCHES = 3

# Hoe dicht een pivot bij de kandidaat-lijn moet liggen (als fractie van
# de prijs) om als treffer op die lijn te tellen. Zelfde soort marge als
# SR_ZONE_CLUSTER_TOLERANCE_PCT, iets ruimer: een diagonale lijn door
# candle-pivots past nooit zo exact als een horizontaal cluster.
TRENDLINE_FIT_TOLERANCE_PCT = 0.01

# Minimale helling (in ATR per candle) wil een lijn als "diagonaal" tellen
# in plaats van als verkapte horizontale zone. Zonder dit zou een bijna
# vlakke lijn hetzelfde patroon als detect_sr_zones vinden, dubbel werk
# met een andere naam.
TRENDLINE_MIN_SLOPE_ATR_MULTIPLE = 0.05


@dataclass
class Trendline:
    kind: str  # "resistance" (verbindt pivot-highs) of "support" (pivot-lows)
    slope: float  # prijsverandering per candle-index binnen het venster
    intercept: float  # lijnwaarde bij index 0 van het venster
    touches: int
    last_index: int  # index van de meest recente pivot op de lijn

    def value_at(self, index: int) -> float:
        return self.slope * index + self.intercept


def detect_trendlines(df: pd.DataFrame, atr: float, lookback: int = SR_ZONE_LOOKBACK) -> list[Trendline]:
    """Vindt maximaal twee diagonale trendlijnen (één weerstand door
    pivot-highs, één steun door pivot-lows) in de laatste `lookback`
    candles. Voor elk soort: alle paren pivots van dat soort vormen een
    kandidaat-lijn, tel per kandidaat hoeveel ANDERE pivots van hetzelfde
    soort binnen TRENDLINE_FIT_TOLERANCE_PCT van die lijn liggen, houd de
    lijn met de meeste treffers. Een lijn met te weinig treffers of een te
    vlakke helling wordt niet teruggegeven — geen kandidaat is dan ook
    geen fout, gewoon geen bruikbare lijn deze cyclus."""
    window = df.tail(lookback).reset_index(drop=True)
    pivots = _find_pivots(window)
    lines: list[Trendline] = []

    for kind, pivot_kind in [("resistance", "high"), ("support", "low")]:
        candidates = [p for p in pivots if p.kind == pivot_kind]
        if len(candidates) < TRENDLINE_MIN_TOUCHES:
            continue

        best: Optional[Trendline] = None
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                p1, p2 = candidates[i], candidates[j]
                if p1.index == p2.index:
                    continue
                slope = (p2.price - p1.price) / (p2.index - p1.index)
                intercept = p1.price - slope * p1.index

                inliers = [
                    p for p in candidates
                    if abs(p.price - (slope * p.index + intercept)) <= p.price * TRENDLINE_FIT_TOLERANCE_PCT
                ]
                if len(inliers) < TRENDLINE_MIN_TOUCHES:
                    continue
                if atr and abs(slope) < TRENDLINE_MIN_SLOPE_ATR_MULTIPLE * atr:
                    continue
                if best is None or len(inliers) > best.touches:
                    best = Trendline(
                        kind=kind, slope=slope, intercept=intercept,
                        touches=len(inliers), last_index=max(p.index for p in inliers),
                    )
        if best is not None:
            lines.append(best)

    return lines
```

**Nieuwe functie, uitbraak + terugtest:**

```python
def find_trendline_breakout_retest(
    df: pd.DataFrame, trendlines: list[Trendline], atr: float, direction: str,
) -> list[tuple[Trendline, int]]:
    """Zelfde patroon als find_breakout_retest: crossing-detectie op de
    laatste candle die van de verkeerde naar de goede kant van het niveau
    sloot, dan checken of dat sindsdien standhield — nu tegen een
    bewegende lijnwaarde in plaats van een vaste zone-grens. Werkt op
    hetzelfde geschoven venster (df.tail(SR_ZONE_LOOKBACK)) als
    detect_trendlines, zodat line.value_at(index) in beide functies
    dezelfde candle aanwijst. Alleen een uitbraak ná line.last_index
    telt: de lijn kan niet gebroken zijn vóór zijn eigen laatste
    bevestigende pivot. Geeft (lijn, candles_since_breakout) terug voor
    elke lijn die nu een geldige terugtest is."""
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    closes = window["close"]
    direction = direction.lower()
    hits: list[tuple[Trendline, int]] = []

    for line in trendlines:
        if (direction == "long") != (line.kind == "resistance"):
            continue

        line_values = pd.Series([line.value_at(i) for i in range(len(closes))])
        if direction == "long":
            broke = (closes.shift(1) <= line_values.shift(1)) & (closes > line_values)
        else:
            broke = (closes.shift(1) >= line_values.shift(1)) & (closes < line_values)

        breakout_indices = [idx for idx in closes.index[broke] if idx > line.last_index]
        if not breakout_indices:
            continue
        breakout_idx = breakout_indices[-1]
        since_breakout = closes.iloc[breakout_idx + 1:]
        since_line = line_values.iloc[breakout_idx + 1:]
        if direction == "long":
            if (since_breakout < since_line).any():
                continue
        else:
            if (since_breakout > since_line).any():
                continue

        last_index = len(closes) - 1
        last_close = closes.iloc[last_index]
        current_line_value = line.value_at(last_index)
        tolerance = BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
        candles_since = last_index - breakout_idx
        if abs(last_close - current_line_value) <= tolerance and candles_since > 0:
            hits.append((line, candles_since))

    return hits
```

`BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE` is de bestaande constante uit
optie C, hergebruikt zonder wijziging: zelfde "hoe dichtbij telt als
terugtest"-marge voor beide patronen.

## Sectie 3: Marktscan-koppeling (`app/market_scanner.py`)

Naast `_check_breakout_retest`, geen vervanging:

```python
async def _check_trendline_retest(coin: str, direction: str, df, ind) -> None:
    trendlines = indicators.detect_trendlines(df, ind.atr)
    hits = indicators.find_trendline_breakout_retest(df, trendlines, ind.atr, direction)
    if not hits:
        return
    line, candles_since = max(hits, key=lambda h: h[0].touches)

    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    last_index = len(window) - 1
    current_value = line.value_at(last_index)
    key = f"{direction}:{line.kind}:{current_value:.8f}"
    if _same_trendline(repo.get_trendline_retest_key(coin), direction, line, last_index, ind.atr):
        return

    stop_take = risk.compute_stop_take(
        direction, ind.price, ind.atr,
        swing_low=current_value if direction == "long" else None,
        swing_high=current_value if direction == "short" else None,
    )
    alert = {
        "coin": coin, "direction": direction, "price": ind.price,
        "line_value": current_value, "touches": line.touches,
        "candles_since": candles_since, "stop_loss": stop_take.stop_loss,
        "take_profit": stop_take.take_profit, "message_id": None,
    }
    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        if repo.is_coin_muted(user["id"], coin):
            continue
        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_trendline_retest_alert(
                alert, chat_id=user["telegram_chat_id"], force_silent=force_silent,
            )
        except Exception:
            logger.exception(
                "Trendlijn-terugtest-melding voor %s naar gebruiker %s is mislukt", coin, user["username"],
            )
    repo.set_trendline_retest_key(coin, key)
```

`_same_trendline` dedupliceert op de huidige lijnwaarde binnen 1x ATR,
zelfde patroon en zelfde reden als de dedup-verruiming die vandaag al op
optie C is toegepast: een opnieuw berekende lijn schuift een fractie mee
tussen scan-cycli zonder dat het om een echt andere lijn gaat.

```python
TRENDLINE_DEDUP_ATR_MULTIPLE = 1.0


def _same_trendline(existing_key: Optional[str], direction: str, line, last_index: int, atr: float) -> bool:
    if not existing_key:
        return False
    try:
        prev_direction, prev_kind, prev_value_s = existing_key.split(":")
        prev_value = float(prev_value_s)
    except (ValueError, AttributeError):
        return False
    if prev_direction != direction or prev_kind != line.kind or not atr:
        return False
    current_value = line.value_at(last_index)
    return abs(prev_value - current_value) <= TRENDLINE_DEDUP_ATR_MULTIPLE * atr
```

Aangeroepen in `scan_market()`, direct naast de bestaande
`await _check_breakout_retest(coin, direction, df, ind)`-regel:

```python
await _check_trendline_retest(coin, direction, df, ind)
```

**Schema/migratie** (`app/schema.sql`, `app/db.py:_migrate`): nieuwe
kolom `coins.last_trendline_retest_key TEXT`, zelfde stijl als
`last_breakout_retest_key`.

**Repo** (`app/repo.py`): `get_trendline_retest_key(coin)` en
`set_trendline_retest_key(coin, key)`, zelfde vorm als de bestaande
`get_breakout_retest_key`/`set_breakout_retest_key`.

## Sectie 4: Telegram-melding (`app/telegram_notify.py`)

Eigen berichttype, geen hergebruik van `format_breakout_retest_message`:
de tekst verwijst naar "trendlijn" in plaats van "zone", en er is geen
zone_low/zone_high, alleen één lijnwaarde. Icoon 📐 om optie C (🎯) en
dit type in Telegram meteen visueel te onderscheiden.

```python
def format_trendline_retest_message(alert: dict) -> str:
    kind_label = "weerstand" if alert["direction"] == "long" else "steun"
    lines = [
        f"{_direction_emoji(alert['direction'])} {_coin_label(alert['coin'])} · {_direction_label(alert['direction'])}",
        DIVIDER,
        "📐 TRENDLIJN-UITBRAAK-DAN-TERUGTEST",
        "",
        f"💰 Prijs nu: {alert['price']:.4f}",
        f"📍 Trendlijn ({alert['touches']}x eerder geraakt): {alert['line_value']:.4f}",
        f"🎯 Take profit: {alert['take_profit']:.4f}",
        f"🛑 Stop loss: {alert['stop_loss']:.4f}",
        _progress_bar(alert["price"], alert["stop_loss"], alert["take_profit"], alert["direction"]),
        DIVIDER,
        f"Deze lijn was eerder {kind_label}, is {alert['candles_since']} candle(s) geleden "
        "doorbroken en wordt nu opnieuw getest.",
        "",
        _trendline_link(alert["coin"]),
    ]
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)
```

`send_trendline_retest_alert(alert, chat_id, force_silent=False)`: zelfde
vorm als `send_breakout_retest_alert`.

`_trendline_link` linkt naar de coin-pagina zonder query-parameters: een
trendlijn heeft geen vaste zone-band om te markeren zoals optie C
(`?zone_low=`/`?zone_high=`), de lijn zelf toont zich al op de grafiek
(zie sectie 5).

```python
def _trendline_link(coin: str) -> str:
    url = f"{config.DASHBOARD_URL}/coins/{coin}"
    return f"🔎 Bekijk de trendlijn op de grafiek: {url}"
```

## Sectie 5: Grafiek (`web/main.py`, `web/static/coin.js`, `style.css`)

Een diagonale lijn past niet in het bestaande `.chart-zone-sr`-blok
(vaste top/hoogte per zone). lightweight-charts tekent zoiets als een
eigen lijnserie met twee punten (tijd, prijs).

`/api/candles/{symbol}` krijgt een nieuw veld `trendlines`, elk element
de twee punten om de lijn te tekenen (begin bij de vroegste pivot op de
lijn, eind bij de laatste candle, geëxtrapoleerd):

```python
ind = indicators.compute_indicators(df)
trendlines = indicators.detect_trendlines(df, ind.atr)
window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
trendline_data = [
    {
        "kind": t.kind,
        "touches": t.touches,
        "points": [
            {"time": candles[len(candles) - len(window) + t.last_index]["time"], "price": t.value_at(t.last_index)},
            {"time": candles[-1]["time"], "price": t.value_at(len(window) - 1)},
        ],
    }
    for t in trendlines
]
```

In `coin.js`: per trendlijn een `chart.addLineSeries(...)` met de twee
punten uit `points` als data, eigen kleur (amber, `#f5a623`, consistent
met de "gemelde zone"-highlight van optie C — ditzelfde kanaal, dezelfde
kleurtaal). Zelfde `?zone_low=`/`?zone_high=`-achtige linkaanpak als
optie C is hier niet van toepassing (geen vaste prijsband); in plaats
daarvan markeert de link simpelweg de coin-pagina, de lijn zelf toont
zich al als enige/nieuwste diagonale lijn op de grafiek.

## Testen

Zelfde patroon als de horizontale zones-implementatie: synthetische
candle-DataFrames voor `detect_trendlines`/`find_trendline_breakout_retest`
los (een bewuste, geconstrueerde dalende driehoek met een fakeout die
NIET als terugtest mag tellen, en een echte terugtest die wel moet
tellen), een pipeline-integratietest met gemockte exchange-calls voor
`_check_trendline_retest`, en een TestClient-test voor het nieuwe
`trendlines`-veld op `/api/candles/{symbol}`.
