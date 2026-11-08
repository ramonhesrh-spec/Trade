# 4u-context mee of tegen (H1)

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
Toetsen of een entry met de 4u-context van coin en BTC beter loopt dan tegen die context.

## Klaar wanneer
- Minstens 8 weken data en 50 trades per groep.
- De beslisregel uit `hypotheses.md` geeft een uitkomst, ook als die negatief is.

## Stappen
- [ ] Wekelijks `scripts/export_analyse.py` op de nieuwste export draaien
- [ ] Unieke uren en weken tellen, niet alleen trades
- [ ] Na 8 weken de beslisregel toepassen

## Stand van nu
Status: wacht. Beoordeling 2026-11-03, export `export/hespulse-2026-11-03.json` (gemaakt 2026-11-03T03:17Z, branch `hespulse-data`).
`scripts/export_analyse.py --vanaf 2026-11-03`: 0 afgeronde signalen. In de export staat geen signaal met `created_at` vanaf 2026-11-03.

Telling per groep (afgeronde trades vanaf 2026-11-03):

| Groep | Trades | Unieke uren | Unieke weken |
|---|---|---|---|
| coin mee | 0 | 0 | 0 |
| coin tegen | 0 | 0 | 0 |
| BTC mee | 0 | 0 | 0 |
| BTC tegen | 0 | 0 | 0 |

Vereist: 50 trades per groep over 8 ISO-weken. Beslisregel niet toegepast. Geen conclusie.

Let op: de sectie `context_4u` in de export telt alle signalen van voor 2026-11-03 (oude soorten). Die data telt volgens H1 niet mee.
Het model neemt alleen trades mee met de 4u-context (stand B-2026-11-02-11), dus de groep "tegen" blijft naar verwachting leeg.

## Besluiten en bronnen
`docs/onderzoek/hypotheses.md` (H1, H1b), `app/context_split.py`.

## Volgende stap
Wekelijks de nieuwste export ophalen en dezelfde telling herhalen. Eerste beoordeling na 8 weken en 50 trades per groep (vroegst 2026-12-29).
