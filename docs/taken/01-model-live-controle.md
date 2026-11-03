# Model live controleren (H2)

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
Vaststellen of het HesPulse-model op echte candles doet wat de spec zegt.

## Klaar wanneer
- Per scenario van de laatste 14 dagen staat vast of elke stap prefix-vast is.
- Per scenario staat vast of de entry al voorbij was bij de melding.
- De uitkomst staat in `docs/onderzoek/bewijsregister.md` met het commando.

## Stappen
- [ ] `scripts/model_kaarten.py` op de VPS draaien (14 dagen, eerste 30)
- [ ] Uitvoer delen en per afwijking een oorzaak noteren
- [ ] Afwijkingen die de spec breken als fout melden, nooit als afstelling

## Stand van nu
Nog niet gedraaid. Dit blokkeert het vertrouwen in taak 02 tot 05. Alleen de CEO kan dit op de VPS doen.

## Besluiten en bronnen
`docs/onderzoek/hypotheses.md` (H2), `docs/onderzoek/hespulse-model/preregistratie.md`, `tests/hespulse_model/`.

## Volgende stap
CEO draait `scripts/model_kaarten.py` op de VPS en deelt de uitvoer.
