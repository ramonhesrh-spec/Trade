# Ontwerp V2, fase 2: wat nog open staat

## Besluiten

De CEO gaf op 26 oktober 2026 het startsein voor fase 2 en liet de keuzes aan de bouwer. Deze besluiten gelden:

- **R1 Overslaan** staat in de database per gebruiker met tijdstip (tabel `plan_skips`, `repo.record_plan_skip`/`list_plan_skips`), naast de
  cookie `hp_skip` die voor het toestel blijft. Nu telt beide (een dag). Het Logboek toont overgeslagen plannen.
- **R2 Checklist** bewaart geopend en afgerond per gebruiker en plan (tabel `checklist_runs`). "Checklist in 1 min 12 s" staat er alleen als
  beide tijden bestaan.
- **R3 Logboek** (`/signalen`) wordt een dagtijdlijn: wat de app zag, wat jij deed, de uitkomst met R. Elke R komt uit
  `track_record.signal_r`, nooit afgeleid. Dagtotaal in R, oudere dagen samengevouwen. Het Journaal blijft bereikbaar en werkt. Alleen eigen
  data; oefentrades tellen nooit mee.
- **R4 Replay** per afgeronde trade: 5m-candles van instap tot sluiting met een uur ervoor, niveaus als lijnen, een cursor met schuifbalk en
  knoppen per moment uit echte tijdstempels. R op een moment alleen na de vulling, gemeten uit de candle-sluiting.
- **R5 Weekterugblik** op Bewijs: één groot getal (gemeten R van de week), acht weken in grijs met deze week in accent, getallen eronder, en
  hoogstens één telbare observatie. "Volgens plan" alleen als het meetbaar is, anders weg.
- **R6 Beheer** (alleen eigenaar, achter het initiaal; `/ceo` blijft): leerlingen, volg-sets en uitnodigingen per code. Een volg-set filtert
  alleen de pushmeldingen van die gebruiker. Registratie blijft open tenzij `REGISTRATION_REQUIRES_INVITE=true`. Uitnodigen per e-mail is
  overgeslagen. Leerlingen zien elkaar of elkaars resultaten nooit.
- **R7 Niet bouwen:** de widget, de trilpatronen (de optie blijft hieronder staan) en de lettertypekeuze voor de oude pagina's.

Fase 1 (navigatie met vier tabs, Nu in rust en met één kaart, de order-checklist, licht thema en Geist) staat in de app. Dit zijn de
onderdelen uit `hespulse_v2.dc.html` die bewust nog niet gebouwd zijn, met de keuzes die eerst gemaakt moeten worden.

- **Vergrendelscherm-widget (ontwerp C).** Een PWA kan op iOS geen widget op het vergrendelscherm zetten, en op Android ook niet zonder
  een eigen app. Open keuze: een native schil (bijvoorbeeld een kleine iOS/Android-app die alleen `/api/radar` leest) of afzien en de
  melding bij "in zone" als enige seintje houden. Wat het ontwerp toont (coin, richting, afstand) staat al op Nu in rust.
- **Trilpatronen per stand (ontwerp C).** iOS-webapps hebben geen haptics. Op Android kan alleen `navigator.vibrate([...])`, en dat
  werkt alleen na een tik van de gebruiker of in een melding (`vibrate` in de opties van `showNotification`, door Chrome op Android
  deels genegeerd). Optie: de vijf ritmes uit het ontwerp (wacht stil, in zone twee korte, gevuld één lange, doel drie oplopend, stop één
  zware) als `vibrate` in de pushmelding voor Android, met een schakelaar in Account. Open keuze: of dit het waard is zonder iOS.
- **Logboek als dagtijdlijn met Replay (ontwerp D).** Vraagt per dag een tijdlijn van wat de app zag, wat jij deed en de R, inclusief
  overgeslagen plannen. Open keuzes: overslaan staat nu alleen in een cookie op het toestel (`hp_skip`, een dag) en moet dan naar de
  database (per gebruiker, met tijdstip) om in het logboek te kunnen staan; "checklist in 1 min 12 s" vraagt dat de checklist zijn
  tijden bewaart; de replay heeft candles per moment nodig (5m uit de beurs, of bewaard bij het sluiten). Elke R op een moment moet
  gemeten zijn, nooit afgeleid uit een schatting.
- **Weekterugblik met R-trend (ontwerp E).** Eén groot getal (gemeten R van de week), acht weken in grijs met deze week in accent, en
  één observatie. Open keuze: welke observaties mogen (alleen telbare, zoals "3 van je 5 overgeslagen plannen haalden doel 1", en dat
  vraagt weer de overgeslagen plannen in de database). `/week` (Kwartaalcijfers) blijft tot dan de plek.
- **Beheer voor de eigenaar (ontwerp E).** Leerlingen, volg-sets en uitnodigingen op één pagina achter het initiaal. Open keuzes:
  uitnodigingen per e-mail of per code (nu is registreren open, `/registreer`), wat een volg-set is in de data (coins per groep
  leerlingen, dus filteren in de meldingen), en dat leerlingen elkaar nooit zien. Tot dan blijft `/ceo` de pagina van de eigenaar.
- **Kleinere punten uit fase 1.** De statuspil "In zone" toont geen resterende minuten zoals het ontwerp ("nog 22 min"): een zone-radar-
  kaart heeft geen vervaltijd, dus dat getal bestaat niet. De regel "4 van 6 kenmerken" staat er niet: de Radar-kaarten hebben geen
  gemeten kenmerken (`app/chance_checks.py` dekt Structuur). De oudere pagina's gebruiken nog Big Shoulders Display voor koppen;
  open keuze of die ook naar Geist gaan.
