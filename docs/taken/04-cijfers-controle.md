# Controle op de modelcijfers (M1 tot M4)

Status: wacht
Laatst bijgewerkt: 2026-11-03

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
Gebouwd in B-2026-11-03-12. Er zijn nog geen afgeronde trades na de bevriezing.

## Besluiten en bronnen
B-2026-11-03-12, `tests/test_model_controls.py`, `app/model_measure.py`, `app/model_placebo.py`.

## Volgende stap
Wachten op 30 trades per punt.
