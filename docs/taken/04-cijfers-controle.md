# Controle op de modelcijfers (M1 tot M4)

Status: wacht
Laatst bijgewerkt: 2026-11-03 (nachtexport 2026-11-03)

## Doel
Controleren of de modelcijfers niet te mooi zijn: strenge vulling, MAE/MFE, placebo, auto-misser.

## Klaar wanneer
- Per instappunt 30 afgeronde trades.
- De drie tabellen onder "Controle op de cijfers" op Bewijs zijn gelezen en samengevat.

## Stappen
- [ ] Wachten tot 30 trades per punt
- [ ] Strenge versus gewone vulling vergelijken (`strict_compare`)
- [ ] Placebo en MAE/MFE naast de stopregel leggen
- [ ] Uitkomst noteren in `bewijsregister.md`

## Stand van nu
Gebouwd in B-2026-11-03-12. Telling uit `export/hespulse-2026-11-03.json` (tak `hespulse-data`, onderdeel `model`), afgeronde trades na de bevriezing:

| Punt | Gevonden | Gevuld | Afgerond (arm n) | Doel |
|---|---|---|---|---|
| A (kop `h`) | n.v.t. | 0 | 0 | 30 |
| B lagere top | 1 | 0 | 0 | 30 |
| B0 zonder premium-eis | 3 | 0 | 0 | 30 |
| R breuk en terugtest | 0 | 0 | 0 | 30 |
| P POC-limiet | 6 | 0 | 0 | 30 |

Trechter: 53 ontdekt, 14 sweep, 7 shift, 0 entry, 0 gevuld, 0 uitkomst. `first_eval_ready` en `decision_ready` zijn false.
V1 heeft 6 afgeronde trades, maar staat verborgen en telt niet mee. Onder de 30 per punt: geen vergelijking gedaan.

## Besluiten en bronnen
B-2026-11-03-12, `tests/test_model_controls.py`, `app/model_measure.py`, `app/model_placebo.py`.

## Volgende stap
Volgende nachtexport lezen. Pas bij 30 afgeronde trades per punt de stappen hierboven uitvoeren.
