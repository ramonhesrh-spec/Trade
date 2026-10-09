# HesPulse: visie en plan

Status: voorstel, wacht op beoordeling door de eigenaar. Gemaakt na een reeks vragen in de sessie van 9 oktober 2026.

## 1. Visie

HesPulse is een persoonlijke signaaldienst voor een kleine kring: de CEO en zijn leerlingen. Elke melding wordt vastgelegd, is achteraf na te rekenen en wordt eerlijk gescoord. We melden wat we hebben en claimen niet wat we niet kunnen bewijzen.

Het doel is korte swings, uren tot een dag of twee, met een voordeel dat na kosten gemeten is. HesPulse plaatst nooit een order; elke trade is een eigen beslissing.

## 2. Beslissingen uit de vragenronde

| Vraag | Keuze |
|---|---|
| Waar moet HesPulse vooral goed in zijn | Een signaaldienst voor de vrienden |
| Wie kiest de signalen | De app kiest automatisch |
| Wanneer mag een regel naar leerlingen | Gelaagd: bewezen regels naar leerlingen, regels in proef alleen voor de CEO |
| Kosten per rondreis | Onder 0,1% (futures met lage vergoeding) |
| Stijl van de trades | Kort en snel: swings van uren tot een dag of twee |
| Volgorde van het onderzoek | Eerst de trendregel inkorten, dan een breed swing-lab, met trades van de CEO als bron van ideeën |
| Meldingen tijdens het onderzoek | Alles blijft pushen, begrensd door de pushregels, het label van de soort en een dagbudget van standaard 6 |

Gevolg van de laatste keuze: leerlingen krijgen ook meldingen van regels met een gemeten verlies. Dat wordt begrensd, niet weggenomen (zie 5).

## 3. Stand van zaken, gemeten

| Regel | Meting | Lezing |
|---|---|---|
| Structuur (breuk en terugkeer, 30 minuten) | 0 van 18 combinaties slagen; per gezien breuk -0,07R bij de huidige instap; alle vijf instapvormen negatief in beide helften | Bruto rond nul, kosten van ongeveer 0,15R per trade bij een stop van 0,4% eten de rest |
| Rejectie op een niveau | 2175 trades op een half jaar, gemiddeld -0,09R per trade, marge -0,14 tot -0,05R | Gemeten verlies; de detector is te los (79% prikt door het niveau) |
| Trend op 30 minuten | -0,06R netto op een jaar | Gemeten verlies |
| Sweeps van dag- en weekniveau (1 uur) | -0,06R tot -0,11R | Gemeten verlies |
| Trendvolgen op 4 uur (uitbraak van 20 of 55 candles, terugval in een trend), stop ongeveer 5% | 5 van 10 varianten slagen; +0,07R tot +0,12R netto per trade; winst 36%; gemiddelde winnaar +1,5R; beste trade +18,6R; 3 jaar, 20 coins | Een eerste kandidaat. De controle met willekeurige instappen scoort +0,03R tot +0,11R: een groot deel zit in de uitgang (meelopende stop), niet in het signaal |

Beperkingen van het lab die we meenemen:
- Overlevingsfout: de 20 coins bestaan nu nog; verdwenen coins ontbreken.
- De trades liggen dicht bij elkaar in de tijd (alle coins volgen BTC), dus de getoonde marges per trade zijn te smal.
- De vijf geslaagde varianten lijken sterk op elkaar: eerder één of twee bevindingen dan vijf.
- Kosten van 0,06% per rondreis zijn aangenomen; de echte kosten moeten onder 0,1% blijven.

## 4. Onderzoeksspoor (fase 1, ongeveer een week)

1. De geslaagde trendregel inkorten naar 1 uur, met een stop van 1,5% tot 2,5% en een uitgang binnen een dag of twee. Vraag: blijft het voordeel bij kortere trades bestaan.
2. Een breed swing-lab: een handvol vooraf vastgelegde families op 1 en 4 uur (terugval in een trend, uitbraak uit een rustige fase, uitbraak met een trendfilter op een hogere tijdframe). Strengere statistiek dan nu: marges per week (clusteren), een controle waarbij de regel willekeurige instappen met een duidelijke marge moet verslaan, en een controle op overlevingsfout (alleen coins die in de hele periode bestonden).
3. Trades van de CEO als bron van ideeën: twintig tot dertig swings met coin, richting, tijd (Nederlandse tijd), instap, stop, doel en uitkomst. Het script `scripts/misser_check.py` toont per motor wat hij zag.

Vooraf vastgelegde regels: geen afstelling op de data; elke variant staat in code vóór de toets; het aantal varianten wordt in de uitvoer genoemd.

## 5. Meldingen

Uitgangspunt: alles blijft pushen, met deze begrenzing (grotendeels al gebouwd):
- Een nieuwe kans krijgt geen push als er in de laatste 6 uur een push over dezelfde coin de andere kant op ging.
- Dagbudget per gebruiker, standaard 6 pushes per 24 uur voor nieuwe kansen (instelbaar op Account; 0 zet het uit). Wat boven het budget valt komt op de meldingenpagina.
- Updates van een lopende trade, stop en doel, agenda en dagbrief komen altijd.
- Elke melding draagt het label van zijn soort en de proefbalk staat bij de kans.
- Een regel zet zichzelf uit na 30 negatieve afgeronde trades.
- Eén lopende melding per trade (de volgberichten vervangen elkaar).

## 6. Naar live en wat bewezen betekent

Fase 2: een geslaagde regel loopt als proefmotor, met trades op papier ernaast om sneller aan aantallen te komen. Alleen de CEO ziet de proefregel als "In proef".

Fase 3: promotie naar "Bewezen" bij alle drie:
1. De regel slaagt in het lab met minstens 500 trades, beide helften positief, een marge per week boven 0 en een duidelijke marge boven de controle met willekeurige instappen.
2. Minstens 50 afgeronde live trades met een netto gemiddelde van 0 of hoger na echte kosten.
3. Doorlopende bewaking: zakt het gemiddelde over de laatste 100 live trades met een marge onder 0, dan gaat de regel terug naar "In proef".

Eerlijke kanttekening: 50 live trades kunnen een voordeel van 0,1R per trade niet bewijzen. Bij een spreiding van ongeveer 1,5R zijn dan ongeveer 900 trades nodig. De live fase is daarom een controle op afwijking van het lab, geen bewijs. Het bewijs komt uit de historie; de live cijfers maken zichtbaar of de werkelijkheid ervan afwijkt. Zo staat het ook op Bewijs en in de communicatie.

## 7. Wat we niet doen

- Geen nieuwe regel live zonder lab-toets.
- Geen belofte van resultaat; een voordeel van ongeveer 0,1R per trade is klein en vraagt geduld en positiegrootte.
- Geen orders namens iemand.
- Geen werkwijze op de openbare pagina.

## 8. Succescriteria

- Minstens één regel bereikt "Bewezen" binnen drie maanden.
- De klachten over te veel en tegenstrijdige meldingen verdwijnen.
- De soorten die pushen scoren samen netto positief op Bewijs, of gaan vanzelf uit.

## 9. Risico's en open punten

- Er is nog geen regel die bewezen voordeel heeft bij korte swings. Het onderzoek kan uitkomen op "geen", en dan blijft de dienst een marktbeeld met in proef gemelde kansen.
- Het label "In proef" naar leerlingen blijft het eerlijke middel; dagbudget en pushregels beperken de schade maar nemen haar niet weg.
- De echte kosten van de CEO en zijn leerlingen moeten per gebruiker bekend zijn; boven 0,4% per rondreis verdwijnt het voordeel van de trendkandidaat.
- Een voordeel van +0,1R per trade met 36% winst betekent lange reeksen verliezen (6 tot 8 achter elkaar is normaal). Dat moet in de communicatie naar leerlingen staan.

## 10. Fasen

| Fase | Inhoud | Klaar als |
|---|---|---|
| 1 | Onderzoek (stap 1, 2, 3 uit sectie 4); pushbudget standaard 6 | Een lijst kandidaten met de lab-uitkomst, of de vaststelling dat er geen is |
| 2 | Proefmotor voor de beste kandidaat, trades op papier, Bewijs per regel met proefbalk | De regel heeft 50 afgeronde live of papieren trades |
| 3 | Promotie naar "Bewezen" volgens sectie 6, korte meldingen met bewijs en ketting | Eén regel is bewezen en gepromoveerd |
