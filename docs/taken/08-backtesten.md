# Backtesten van het model en de regels

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
Het HesPulse-model en elke nieuwe regel historisch toetsen zonder af te stellen op de data.

## Klaar wanneer
- Elke toets heeft vooraf vastgelegde regels, een tellend aantal toetsen en netto R na kosten.
- Uitkomst voldoet aan de eisen van `app/replay/stats.py`: minstens `MIN_TRADES`, beide helften boven 0, bootstrap per week boven 0, placebo-marge.
- Resultaat staat met commando in `bewijsregister.md`.

## Stappen
- [ ] Vastleggen wat het model-backtest moet beantwoorden (preregistratie vóór de run)
- [ ] Bepalen of `scripts/model_kaarten.py` (14 dagen) genoeg is of dat een langere replay nodig is op `app/replay/`
- [ ] Draaien op de VPS met de 5m-, 15m-, 1u-, 4u- en dagcandles
- [ ] Resultaat per instappunt (A, B, B0, R, K) netto na kosten en funding
- [ ] Perps-tijdperk apart houden (vanaf 2026-11-01)

## Stand van nu
Beschikbaar: `app/replay/` (engine, stats, lab), `scripts/strategy_lab.py`, `scripts/model_kaarten.py` (14 dagen, controle achteraf), `scripts/backtest_factors.py`, `scripts/model_placebo.py`. Een volledige backtest van het model over meerdere maanden bestaat niet. Voorgaande lab-uitkomsten hielden stand in E1: de steekproef is klein en geclusterd.

## Besluiten en bronnen
`CLAUDE.md` (Lab en proefmotor), `docs/onderzoek/range-sweep/vps-protocol.md`, `docs/onderzoek/Crypto edges na kosten onderzoek.md`.

## Volgende stap
Eerst taak 01 afronden. Daarna de vraag en de regels van de backtest vastleggen.
