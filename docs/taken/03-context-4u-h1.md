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
Loopt automatisch via de nachtexport (`context_4u`, `btc_4u`), telt vanaf 2026-11-03. Geen oordeel mogelijk.

## Besluiten en bronnen
`docs/onderzoek/hypotheses.md` (H1, H1b), `app/context_split.py`.

## Volgende stap
Wachten op data. Eerste beoordeling na 8 weken.
