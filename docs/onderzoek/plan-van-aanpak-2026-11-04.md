# Plan van aanpak HesPulse-model (4 november 2026)

Voor de CEO. Kritische terugblik op alle voorbeelden van 2 en 3 november, vergeleken met wat HesPulse nu doet.

## Wat ik bekeken heb

- 16 beelden die nog in deze sessie staan: BTC 12u (mainachad, 2x), BTC 1u vPOC, BTC 4u 18:47, BTC dag (RAGAZZI), PUMP 4u
  (RAGAZZI), goud dag en 4u, PUMP Groot, de Kansen-pagina van 20:52, ZEC 15m, ONDO, ETH (Groot en kaart), XRP 1u en 15m.
- 9 cases in `docs/onderzoek/cases/` (WLD, BTC 4u, goud, PUMP 3x, ZEC, BTC vPOC, DOGE).
- Niet meer beschikbaar: de beelden van vóór de herstarts van de container. Die staan alleen nog als samenvatting in de cases.

## Kort oordeel

De richting klopt. Elke trade die jij stuurde, is een short in een dalende dag met BTC bearish. Het model zoekt nu precies dat. Maar ik zie
vier zwakke plekken:

1. We hebben elke dag regels veranderd. Daardoor zegt geen enkele meting nog iets.
2. De grafiek "Groot" toont een andere range dan de kaart, en soms een tegengestelde trend.
3. Het model kijkt alleen naar de 4u-range. Jouw analisten kijken naar 12u en de dag.
4. Er staan te veel letters op de kaart (A, B, B0, R, V1, P). Dat is niet duidelijk.

## 1. Wat ik over het hoofd zag

**1.1 Geen meting is nog bruikbaar.**
- Sinds 2 november veranderde het model zes keer: top-down, B, B0, R, de opgerekte range en de luide meldingen voor B, B0 en R.
- Elke wijziging maakt de trades ervoor onvergelijkbaar met die erna.
- Ik heb nog geen enkele afgeronde modeltrade gezien. De stopregel van 50 trades per punt is dus weken weg.
- Dit had ik eerder moeten zeggen. Ik heb steeds gebouwd wat je vroeg zonder de prijs ervan te noemen.

**1.2 Groot en de kaart spreken elkaar tegen.**
- De kaart zegt "4u range high/low" van het model. Bij PUMP is dat ongeveer 0,0037 tot 0,0046.
- Groot op 4u tekent RH en RL van de laatste 4u-breuk in elke richting. Bij PUMP is dat de herstelpoot, ongeveer 0,00405 tot 0,0043.
- De trendregel bovenin zegt bij PUMP, XRP en ETH "4u ↑", terwijl het model short zoekt "met de 4u-range mee".
- Oorzaak: `structure_levels.py` telt elke breuk, het model telt sinds de top-down-regel alleen de breuken in de richting van de dag.
- Gevolg: jij ziet twee verschillende verhalen op hetzelfde scherm.

**1.3 V1 ligt bijna altijd op het evenwicht.**
- PUMP V1 0,004221 en UNI V1 6,886 liggen precies op het evenwicht (de Kansen-pagina van 20:52).
- De regel kiest de dichtste pool boven de koers in premium. Die ligt dus meestal aan de onderkant van premium.
- ONDO vulde niet (weggelopen, gecontroleerd in de database).
- Bij ZEC zei ik eerder dat V1 gevuld en gestopt zou zijn. Dat heb ik niet nagerekend. V1 vervalt zodra het scenario eindigt, en dat
  scenario eindigde al op 2 november rond 02:30. Mijn bewering was dus voorbarig.
- V1 maakt de kaart drukker en heeft in de voorbeelden niets opgeleverd. Dat is twee keer, geen meting.

**1.4 Hogere tijdframes ontbreken in de instap.**
- BTC 1u vPOC-short: de instap op 78.721 ligt precies aan de onderkant van de H12 FVG (78.800 tot 79.600) van mainachad.
- PUMP 4u RAGAZZI-short: de instap ligt onder de "Recent High" en het doel net boven de liquiditeit van 24 september (0,003748).
- Goud 4u: short pas vanaf premium van de grote range (0,5 tot de External High).
- BTC dag: doel op het 0,5-niveau van de dagrange en een "open prijs zonder lont".
- Het model kent premium alleen binnen de 4u-range, en een FVG of OB alleen op 15m. Een 12u- of dag-FVG of een breaker als aanbodzone kent
  het niet.

**1.5 Alle 28 scenario's zijn shorts op dezelfde BTC-beweging.**
- Draait BTC, dan lopen alle shorts tegelijk tegen hun stop.
- Het dagbudget van 8 meldingen beperkt het aantal meldingen, niet het risico.
- In de export van 2 november vielen 374 trades in 196 unieke uren (E1). Dat zal bij het model niet anders zijn.

**1.6 Een plan leeft 6 uur, de analisten laten een order staan.**
- ETH: plan B stond nog 12 minuten. Een analist laat zijn limiet staan tot de stop of het doel eerst geraakt wordt.
- De 6 uur komt uit de preregistratie en is nooit getoetst.
- We meten niet wat een vervallen plan daarna had gedaan.

**1.7 Open punten die bleven liggen.**
- ONDO scenario 2 werd 4,5 uur te laat opgeslagen (08:00 tegen 12:30 UTC). De oorzaak is niet vastgesteld.
- Of B0 bij ONDO vulde en het doel haalde, is niet gecontroleerd.
- De uitkomsten van V1, B en B0 op de VPS heb ik nooit gezien.

## 2. Wat er bij moet (voorstel, op volgorde)

1. **Groot gelijk aan het model.** De range, het evenwicht en de trendregel komen van het model zelf, top-down. Bij een tegenbreuk staat er
   "4u ↑ herstel" in plaats van "4u ↑". Alleen weergave. Klein werk.
2. **Meten wat een vervallen plan had gedaan.** Stil, zonder melding. Na 50 vervallen plannen weten we of 6 uur te kort is.
3. **Samenhang zichtbaar maken.** Bovenaan Kansen: "28 scenario's, allemaal short, allemaal met BTC". Bij een nieuwe melding: "4 andere
   shorts open". Geen filter, alleen zichtbaar.
4. **Hogere-tijdframezone als kenmerk.** Per plan vastleggen of de limiet in een 12u- of dag-FVG of breaker ligt. Alleen meten, geen
   filter. Na 50 trades zien we of die plannen beter zijn. Dit is de vraag uit 1.4, eerlijk getoetst.

## 3. Wat eruit kan

1. **V1 van de kaart.** Hij blijft stil gemeten, maar staat niet meer op de kaart of in Groot. Komt hij na 50 trades goed uit, dan kan hij
   terug.
2. **P van de kaart.** Hij verschijnt zelden en zonder uitleg. Hij blijft stil gemeten.
3. **Letters alleen in het blad.** Op de kaart staat alleen het ene plan dat nu geldt. B, B0 en R heten daar "Plan" met in het blad de
   letter en de basis.

## 4. De belangrijkste: bevriezen

- Voorstel: vanaf vandaag drie weken geen nieuwe instapregels.
- Alleen weergave en meting mogen veranderen (punten 2.1 tot 2.4 en 3.1 tot 3.3).
- Een nieuw voorbeeld wordt een case met een vooraf vastgelegde hypothese, geen regel.
- Na drie weken: per instappunt de stand op Bewijs, en dan beslissen wat blijft.
- Zonder dit kunnen we nooit zeggen of HesPulse een legitieme kans geeft.

## 5. Wat ik van de VPS nodig heb

```
cd /opt/crypto-alerts
sqlite3 data/trading.db "SELECT code, state, COUNT(*), ROUND(AVG(r_gross),2) FROM model_entries GROUP BY code, state;"
sqlite3 data/trading.db "SELECT state, COUNT(*), ROUND(AVG(r_gross),2) FROM model_v1 GROUP BY state;"
sqlite3 data/trading.db "SELECT entry_state, COUNT(*) FROM model_scenarios GROUP BY entry_state;"
sqlite3 data/trading.db "SELECT id, coin, discovered_at, detected_at FROM model_scenarios ORDER BY id DESC LIMIT 20;"
```

De eerste drie geven de eerste cijfers per instappunt. De laatste laat zien of het opslaan vaker uren te laat is (ONDO).

## 6. Jouw besluiten

1. Bevriezen we de instapregels drie weken? Mijn advies: ja.
2. V1 en P van de kaart, wel stil gemeten? Mijn advies: ja.
3. Groot gelijk aan het model (punt 2.1)? Mijn advies: ja, eerst.
4. Hogere-tijdframezone als kenmerk meten (punt 2.4)? Mijn advies: ja, alleen meten.
