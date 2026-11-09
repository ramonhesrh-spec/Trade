# HesPulse in TradingView

`hespulse_structuur.pine` tekent op je TradingView-grafiek wat "Groot" in de app tekent, op het tijdframe van je grafiek: dezelfde laatste 499
gesloten candles, dezelfde regels. `tests/test_tradingview_port.py` toetst een Python-versie in precies de stappen van het script tegen de
echte code van Groot.

## Zo zet je hem erop

1. Open TradingView en kies de perp van Binance, bijvoorbeeld `BINANCE:SOLUSDT.P`. De app rekent op die candles.
2. Open onderin de Pine Editor, wis wat er staat en plak de hele inhoud van `hespulse_structuur.pine`.
3. Klik op "Save" en dan op "Add to chart".
4. Rechtsboven staat de trendregel. Bij de instellingen (tandwiel) zet je lagen aan of uit.

## Wat hij tekent

- De richting van de dag, en welke kant het model zoekt.
- Per tijdframe zoals Groot: de laatste breuk in de richting van de dag (BOS, CHoCH of MSB), range high (RH), range low (RL), evenwicht
  (EQ), de laatste swing high en low (SH, SL) of gelijke toppen en bodems (EQH, EQL), het order block (OB) en de dichtste open FVG boven en
  onder de koers.
- De trend per tijdframe: D, 4u, 1u en 15m, met "herstel" als een breuk tegen de dag in ging. Een tijdframe onder dat van je grafiek krijgt
  een streepje.
- Het positievak: plak limiet, stop en doel uit de melding bij "Plan uit HesPulse".

## Wat hij niet doet

- Hij kent de plannen van het model niet. TradingView laat geen andere app lijnen op je grafiek zetten.
- Hij meldt niets. De melding komt uit de app.
- Pools, sweeps en de instappunten A, B, B0, R en K staan er niet in. Die staan op de kaart en op Groot.

Regels: `app/model.py` (swings, breuken, `Context4h` top-down, `DailyBias`) en `app/structure_levels.py` (FVG). Verandert daar een regel, dan
moet dit script mee.

## Bekende verschillen

Nagelopen op 2026-11-03 tegen `app/model.py` (`_pivot_flags`, `breaks`, `Context4h`, `DailyBias`) en `app/structure_levels.py` (`levels`,
`open_fvgs`). De swingregel (strikt links, gelijk of lager rechts, 3 candles op 1u, anders 2), de breukregel (slot voorbij de laatste
herkenbare, nog niet gebroken swing; een breuk verbruikt elke gepasseerde swing; BOS, CHoCH, MSB), de range (laagste low tussen top en
breuk, hoogste high sinds de top), de opgerekte range top-down, het order block, EQH/EQL binnen 0,1 ATR en de open FVG zijn gelijk aan
Groot. Deze verschillen blijven:

- Geen limiet van 60 candles op de range. Het model laat een 4u-range na `BIAS_MAX_BARS` (60 candles van 4u) vervallen. Groot en het
  script tekenen de laatste breuk hoe oud ook. Reden: Groot toont de structuur zoals een analist, niet het moment waarop het model zoekt.
- Elk tijdframe krijgt een range. Het model bouwt de range alleen op 4u (`Context4h`). Groot en het script doen het op 15m, 1u, 4u, 12u en
  D. Reden: Groot is een kaart per tijdframe.
- Zonder dagbreuk geen filter. Het model zoekt dan geen scenario. Groot en het script tekenen de laatste breuk in welke richting ook, en
  melden "Nog geen dagbreuk". Op de dag zelf (D) volgt de tekening ook geen richting van boven. Reden: er is geen richting om te volgen.
- Een slot door de verre rand van de range zonder dagrichting (op D) laat de range staan. Het model laat zonder top-down de range
  vervallen en rekt hem top-down op. Reden: Groot rekt alleen op als de dag een richting geeft, zoals in `levels(bias=)`.
- Andere geschiedenis voor de richting van de dag en de trendregel. De app rekent op de candles die hij ophaalt (`DAY_LIMIT` voor de dag).
  Het script rekent op alle candles die TradingView voor dat tijdframe geladen heeft, met hoogstens 400 open swings per kant. De laatste
  richting valt meestal samen. Ligt de laatste breuk ver terug, dan kan een andere beginhistorie een andere gebroken swing geven. Reden:
  `request.security` kent geen vast venster.
- Een tijdframe onder dat van je grafiek krijgt een streepje in de trendregel. De app toont daar wel een richting. Reden: TradingView geeft
  op een hoger tijdframe geen betrouwbare candles van een lager tijdframe.
- Op een tijdframe buiten 15m, 1u, 4u, 12u en D (bijvoorbeeld 5m) gebruikt het script 2 candles per swing. De app kent die tijdframes niet.
- De vlakken premium en discount staan niet in het script. Groot slaat ze ook over (`levelchart.js`); alleen de EQ-lijn staat erop.
- Candles komen van TradingView. Kleine verschillen met de candles van de app (een gemiste of herziene candle) kunnen een swing
  verschuiven. De tekening is dan een benadering.

## De kleuren van de app instellen

Rechtsklik op de grafiek, kies Settings.
- Symbol: Body omhoog #FFFFFF, omlaag #1B2324; Borders en Wick allebei #1B2324.
- Canvas: Background Solid #FFFFFF; Vert grid lines uit; Horz grid lines #0D1415 op 6% dekking; Scales text #3E4A4C.
- Onderaan: Template, Save as, "HesPulse".
Stop is #C42F3D, doel #0F7A45, lijnen #8A9698.

## HesPulse Clean (nieuw, `hespulse_clean.pine`)

Opvolger van `hespulse_structuur.pine`: dezelfde structuur als Groot, plus de liquiditeit van 1u en 4u en de sweep-aanduidingen. **Nog niet in
TradingView gecompileerd.** Plak hem in de Pine Editor, kijk of hij zonder fout op je grafiek komt en meld wat je ziet. Tot dan blijft het
oude script de geteste kopie van Groot.

Wat erbij kwam:
- **BSL en SSL van 1u en 4u** (`1u BSL`, `4u SSL`, `4u EQH`): de dichtstbijzijnde onaangeroerde swing high en low van gesloten candles, een pool
  is hoogstens 120 candles oud en vervalt bij de eerste aanraking van een latere candle (`Pools._touch`). De lijn begint bij de echte
  pivot-candle (tijd van het hogere tijdframe, `xloc.bar_time`). Een niveau van 1u binnen 0,1 ATR van dat van 4u blijft weg. Op een grafiek
  boven 4u of 1u verschijnt dat tijdframe niet.
- **L? en S?** (alleen op 15m): sweep van het model (4.8): prik minstens 0,1 en hoogstens 2,5 ATR door een onaangeroerde 1u-pool, slot terug
  binnen 6 candles van 15m. Een pool geeft hoogstens één sweep: elke aanraking, ook een ondiepe, verbruikt hem.
- **L+ en S+** (alleen op 15m): dezelfde keten tot en met shift (slot boven de laatste 15m-top vóór de prik, binnen 24 candles), displacement
  (1,0 ATR, 5 candles) en een ongevulde FVG (4.9 tot 4.11). Het signaal komt op de candle waar de keten sluit, nooit terug op de sweep.
- Alleen met de dagrichting: L? en L+ bij dag long, S? en S+ bij dag short.
- Labels vallen niet over elkaar (samengevoegd tot één regel), alle instellingen zijn `display.none`, SH of SL die samenvalt met RH of RL
  blijft weg, en de range rekt top-down op zoals Groot.

Wat er **niet** in zit en waarom de signalen geen modelplan zijn: de 4u-range (premium en discount), de groepering van gelijke pools tot één
pool, het doel en de BTC-poort. L+ is dus vaker dan een entry van het model. Het zijn geen A, B, B0, R of K. Experimenteel, niet getest op
winst, niet voor beslissingen over een trade zonder de kaart in de app.

Wat getest is: `tests/test_tradingview_signals.py` houdt een Python-versie van `f_sig` en `f_disp` bij en eist dat die op 60 willekeurige
reeksen, long en short, dezelfde sweep- en displacement-candles geeft als `_Run._step` van het model, bij dezelfde pools. Niet getest:
compileren, de HTF-aanroepen (`request.security`) in TradingView en het uiterlijk. De ATR rekent dezelfde Wilder-recursie, maar over de candles
die TradingView laadt, dus de eerste honderd candles kunnen een tik afwijken. De dagrichting en de pools komen uit `request.security` met de
vorige gesloten candle (`[1]` en `lookahead_on`); of die in TradingView niet herschrijven, moet je op een lopende candle bekijken.

Op ZEC 15m (2026-11-08) gaf L? en S? zes of zeven keer in één stijging, omdat de 4u-range (premium en discount) ontbreekt. Daarom staan L? en S? nu standaard uit (instelling "Ook L? en S? tonen"); L+ en S+ blijven aan. Labels van lijnen vlak bij de rechterrand staan links van de lijn, de trendregel staat rechtsonder en is korter.

ZEC 4H (2026-11-08): bij samengevoegde labels was niet te zien bij welke candle een niveau hoort. Namen staan nu rechts bij de laatste candle, een kleine stip markeert de candle waar het niveau begon, en de trendregel staat linksonder.

WLD 4H (2026-11-09): de stippen waren te groot en niet clean. Een kort verticaal streepje op de beginncandle vervangt ze, en de namen staan drie candles rechts van de laatste candle, buiten de koers.

## Clean 4 (2026-11-09)

Dezelfde motor als Clean (sweepketen getest tegen `app/model.py`, structuur zoals Groot), met de goede delen van de versie "Clean 3.2" uit de
sessie "TradingView script":
- De naam staat bij het begin van de lijn, boven of onder het niveau (BSL, RH, EQ, EQH en een breuk omhoog boven; SSL, RL, EQL en een breuk
  omlaag eronder). Zo hoort een naam bij de candle waar het niveau ontstond. Ligt dat begin links buiten beeld, dan staat de naam aan de
  linkerrand. Namen worden alleen samengevoegd als de prijs binnen een derde ATR ligt, ze aan dezelfde kant staan en hun begin hoogstens zes
  candles uit elkaar ligt.
- Vlakken (OB en FVG) eindigen vijf candles voorbij de laatste candle (instelling), niet aan het einde van de grafiek.
- Een regel linksonder "tussen 4u SSL en BSL: 62% · premium": de positie tussen de dichtstbijzijnde onaangeroerde 4u-pools. Een benadering,
  niet de 4u-range van het model.
- Instelling Labelgrootte (standaard, groot, extra groot).
- Niet overgenomen uit 3.2: de eigen sweep- en displacementregels (andere ATR, één pool per kant, geen 15m-aanraking, een andere displacement),
  RH en RL als laatste swing en niet als range van de beweging die brak, en de OB-regel. Reden: ze wijken af van het model en Groot en hebben geen
  test. De OB-voorwaarde van 3.2 (beweging van minstens een ATR) staat op de parkeerlijst.

Groot in de app (2026-11-09): dezelfde opmaak. De naam van een hoog niveau staat boven de lijn, van een laag niveau eronder, en de 4u- en 1u-pools staan als grijs gestippelde lijnen (`/api/structuur`, sleutel `pools`). Niet overgenomen in de app: de compacte vlakken (Groot scrolt, de vlakken lopen door) en de regel "tussen 4u SSL en BSL".

