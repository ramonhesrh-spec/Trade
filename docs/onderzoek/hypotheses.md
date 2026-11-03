# Hypotheses

Elke hypothese ligt vast vóór de toets: de meting, de data die meetelt, de beslisregel en wat er gebeurt bij elke uitkomst. Een hypothese
wordt niet herschreven na het zien van de uitkomst; een nieuwe versie krijgt een nieuw nummer.

## H1. De 4u-context bepaalt of een trade netto iets oplevert (vastgelegd 2026-11-02)

**Aanleiding (bewijsregister E1).** In de export van 2026-11-02 deden shorts het in drie van de vijf soorten beter dan longs: zone-sweep
short +0,60R tegen long −0,28R, zone-radar short −0,02R tegen long −0,81R, Structuur C short +0,49R tegen long −0,06R. Die data leverde
het idee op en telt dus niet als bevestiging.

**Waarom dit telt.** Het HesPulse-model neemt alleen trades mee met de 4u-context (`model.Context4h`). Als trades mee met die context niet
beter zijn dan trades ertegen, heeft de kernfilter van het model geen steun in onze eigen data.

**Tegenverklaring die de toets moet uitsluiten.** Oktober en begin november 2026 daalden de meeste coins. Dan is "mee met de context"
grotendeels hetzelfde als "short", en meet je de maand, niet de regel.

**Meting.** `app/context_split.py` geeft per signaal `mee`, `tegen`, `neutraal` of `onbekend` voor de eigen coin (`context_4u`) en voor BTC
(`btc_4u`), met precies de regel van het model en alleen candles die op het signaalmoment gesloten waren. De nachtexport schrijft het per
signaal en per soort (`context_4u` in de JSON, sectie "Context 4u (H1)" in de Markdown). Lezen: `scripts/export_analyse.py --tak <datum>
--vanaf 2026-11-03`.

**Data die meetelt.** Alleen afgeronde signalen (doel of stop) van de focus-soorten en het model, aangemaakt vanaf 2026-11-03, netto na
kosten en funding.

**Beslisregel.** Eerste beoordeling zodra mee en tegen elk minstens 50 afgeronde trades hebben, over minstens 8 ISO-weken. H1 is gesteund als
alle drie gelden:

1. het verschil netto R mee min tegen heeft een 95%-interval boven 0 bij een bootstrap per ISO-week;
2. het verschil heeft hetzelfde teken in de eerste en de tweede helft (op tijd);
3. het verschil is positief binnen de longs én binnen de shorts afzonderlijk. Dit sluit de tegenverklaring uit.

H1 is weerlegd als het interval onder 0 ligt, of als het verschil na 150 trades per groep binnen ±0,05R ligt. Anders: wachten. Vijftig
trades is een tussenstand, geen bewijs.

**Gevolgen.** Gesteund: de kernfilter van het model houdt stand; geen wijziging. Weerlegd: dat is tegenbewijs tegen het model; ik leg
het voor aan de CEO met de cijfers, geen stille wijziging. Bij "tegen" met een positieve netto R is er steun om een herstel-long tegen de
4u-context (goud, `cases/2026-11-02-goud.md`) als aparte variant te toetsen.

**H1b (BTC).** Dezelfde regel met `btc_4u` in plaats van `context_4u`. BTC-context is alleen een kenmerk tot H1b gesteund is. Een filter op
BTC zonder deze toets is niet toegestaan (besluit B-2026-11-02-05). *Herzien door B-2026-11-02-10: op besluit van de CEO is de BTC-poort live vóór deze toets. De stille arm meet wat hij tegenhoudt.*

**Stand 2026-11-02 (B-2026-11-02-11).** De oude soorten zoeken niet meer, dus H1 krijgt geen nieuwe trades van hen. Het model neemt alleen
trades mee met de 4u-context, dus de groep "tegen" blijft leeg. H1 staat daarmee stil. H1b wordt deels vervangen door de stille arm van de
BTC-poort (`model_measure.gate`): die laat zien wat entries tegen BTC hadden gedaan.

## H2. Het model doet live wat de spec zegt (vastgelegd 2026-11-02)

**Meting.** `scripts/model_kaarten.py` op de VPS: de eerste 30 modelkaarten van 14 dagen, elke stap opnieuw berekend zonder latere candles.
Plus de modelsectie van de nachtexport: vulbaar bij melding, terugtest al geweest, vertraging entry.

**Beslisregel.** Eén rode stap (een stap die anders uitkomt zonder latere candles) is een fout: eerst oorzaak vinden, regressietest erbij,
dan pas verder meten. Geen drempel voor winst; die komt uit de preregistratie §8.

## Geparkeerd

- **H4. Een 15m-omkeer tegen de dag in na een sweep van de bodem levert netto iets op** (vastgelegd 2026-11-03,
  `cases/2026-11-03-goud-15m-long.md`). Lezing vooraf: de dag wijst omlaag, de 15m maakt een nieuwe bodem die een gelijke bodem of SL
  wegneemt en sluit terug, daarna een 15m-breuk omhoog; limiet op het gebroken niveau, stop onder de sweep met de 0,4%-vloer, doel de
  dichtste van de 4u-range-rand en een naakte POC. Spiegelbeeld voor short. Zou een stille arm worden, zoals de arm tegen de dagtrend,
  maar op 15m in plaats van 4u. Pas na de bevriezing en pas als de arm tegen de dagtrend een eerste beoordeling heeft; nooit afstellen op
  dit ene voorbeeld. Beslisregel dan: dezelfde als de arm tegen de dagtrend (50 afgeronde trades, weekinterval van de netto R).

- **H3. Vroege limiet op een naakte POC/vPOC bij een lagere top, met 4u- en BTC-context mee** (`cases/2026-11-btc-1u-vpoc.md`). Eerst
  vastleggen van welke periode het volumeniveau komt. Een niveau uit een periode die de beweging zelf bevat, is vooruitkijken. Pas
  toetsen als B een eerste beoordeling heeft. De POC-niveaus worden nog bijgewerkt (`poc_radar_live.refresh_levels`), dus de data
  is er.

- **Bevestigde entry tegen vroege limiet (DOGE).** Wordt al gemeten als V1 (vroege limiet) tegen H in `model_measure`. Geen nieuwe
  variant nodig; eerst de bestaande meting laten lopen.
- **Goud als instrument.** Niet in `FIXED_COINS`. Of Binance USDⓈ-M een goudcontract heeft, kon ik vanuit deze container niet controleren
  (geen netwerk naar Binance). Productvraag aan de CEO, geen onderzoeksvraag.
