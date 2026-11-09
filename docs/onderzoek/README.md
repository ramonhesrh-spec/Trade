# Onderzoeksgeheugen HesPulse

Startpunt voor elke onderzoeks- of ontwikkelsessie. Lees in deze volgorde, en alleen wat bij de taak hoort:

1. `voortgang.md`: wat is af, wat blokkeert, wat is de volgende stap.
2. `besluiten.md`: aangenomen en verworpen wijzigingen met reden en versie. Een besluit wordt nooit stil overschreven; een herziening krijgt
   een nieuwe regel die naar de oude verwijst.
3. `hypotheses.md`: open vragen met hun toets en beslisregel, vastgelegd vóór de toets.
4. `bewijsregister.md`: uitkomsten met bron, commando om ze te reproduceren en beperkingen.
5. `cases/`: één bestand per voorbeeld (screenshot, rapport, trade, correctie), met bron, waarneming, timing, vergelijking met HesPulse en
   wat nog ontbreekt.

Bestaande onderzoeksstukken blijven waar ze staan en worden hier alleen genoemd:

- `hespulse-model/preregistratie.md`: de bindende spec van het enige model dat meldt.
- `range-sweep/`, `zone-sweep/`: preregistraties, VPS-protocollen, handtrades en resultaten.
- `Crypto edges na kosten onderzoek.md` en `notities/`: literatuuronderzoek (oktober 2026).
- `../verbeterlus.md`: de vaste wekelijkse verbetersessie op de nachtexport (tak `hespulse-data`).

Werkregels voor elke stap:

- Scheid feit (gezien of uit data aantoonbaar), interpretatie, hypothese, bevinding binnen één dataset en onbekend.
- Een screenshot bewijst het moment van de screenshot, niet het moment waarop een setup bekend werd. Een open candle is geen bevestiging.
- Leg de regel en de beslisregel vast vóór de vergelijking. Data die de hypothese opleverde, telt niet als bevestiging ervan.
- Elke bevestigde fout wordt een regressietest plus een tegenvoorbeeld waarin dezelfde correctie geen trade mag geven.
- Bij een bijlage eerst tellen: tekstlengte, aantal beelden en verborgen inhoud. Per beeld noteren of het bekeken is. Nooit "alles gelezen"
  zonder die telling (ronde 4: twee van vijf beelden bekeken en "alle vijf" gemeld).
- Verzin geen controles. Schrijf op wat wel en niet te controleren was, en waarom.
