# Vaste opdracht: wekelijkse verbetersessie

Deze opdracht draait één keer per week als geplande Claude-sessie op de repository. Het doel: HesPulse verbetert zichzelf rond de setups
(Structuur, Zone-radar, Zone-sweep, POC-radar) zonder dat de CEO trades instuurt. Eerlijkheid gaat voor: geen afstellen op data, elke variant
vooraf vastgelegd, alles netto na kosten. Lees eerst `CLAUDE.md` (alinea "Automatische verbeterlus").

## Stappen

1. **Lees de nieuwste export.** `git fetch origin hespulse-data` en lees het nieuwste `export/hespulse-JJJJ-MM-DD.json` en `.md` op die tak
   (`git show origin/hespulse-data:export/<naam>`). Is de nieuwste export ouder dan twee dagen, meld dat en stop: dan draait de nacht niet.
2. **Kies per soort het grootste lek.** Per soort in `lekken["30d"]` (en ter controle `7d`): kaarten die vervielen (per reden), stops die binnen
   24 uur toch het doel haalden (`stop_dan_doel`), de MAE van winnaars en verliezers, de dagcap, de vertraging en de auto-missers per
   weigerreden. Kies één lek per soort en noem het getal waarop je het kiest. Geen lek dat duidelijk groter is? Dan geen variant voor die soort.
3. **Kijk naar de schaduw die er al is.** `export["schaduw"]`: heeft de soort een actieve schaduw (status `schaduw`), dan komt er geen tweede
   bij; hoogstens één per soort. Een gepromoveerde of afgevallen variant komt niet terug met dezelfde waarde.
4. **Leg één variant vooraf vast.** Alleen met een parameter die aansluitbaar is (`app/shadow.py`, `PARAMS`): zone-radar `stop_atr` en
   `max_distance_pct`, zone-sweep `stop_buffer_atr`, POC-radar `stop_atr`, Structuur `stop_atr`. Kies de waarde uit een redenering over het
   lek, niet door waarden op de export door te rekenen tot er een mooi getal uitkomt; één waarde, geen reeks. Leg hem vast door één entry
   toe te voegen aan `SEEDS` in `app/shadow.py` (`id`, `trade_type`, `description`, `reason`, `params`); de nacht
   (`scripts/schaduw.py --auto`) legt hem in het register vast zodra de soort vrij is, en vanaf dan draait hij mee. Haal nooit een entry
   weg of verander er een: het register is de geschiedenis. De reden noemt het lek en het getal uit de export. `tests/test_shadow.py`
   (`test_seeds_in_code_zijn_geldig`) toetst elke entry.
   Is een nieuwe parameter nodig, maak hem dan eerst aansluitbaar zoals de bestaande: een optioneel argument in de planfunctie met de
   constante als standaard, een `_shadow_plan(s)` in de live motor via `shadow_live.observe`, en een test dat de standaard niets verandert.
5. **Bouw, test, push.** TDD; draai `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .` en eis groen, inclusief de golden tests.
   Commit klein, push naar de werktak.
6. **Rapporteer kort.** Per soort: het gekozen lek met getal, de vastgelegde variant (of waarom geen), de stand van de lopende schaduw
   (n per arm, netto R, verdict) en wat je niet kon doen.

## Nooit

- Een gewone motorregel of constante direct wijzigen. De enige route naar een andere waarde in de motor is een schaduw die volgens de vaste
  regel promoveert (`scripts/schaduw.py --auto`, elke nacht) of een uitdrukkelijk verzoek van de CEO.
- De promotieregel, `MIN_TRADES`, `MAX_TRADES`, de kosten of de meting van de schaduw aanpassen.
- Meer dan één actieve schaduw per soort, of een variant zonder vooraf vastgelegde reden.
- Gegevens van gebruikers in de export of in een commit.
- Promoveren met `--toch`.
