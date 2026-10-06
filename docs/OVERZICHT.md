# HesPulse in één pagina

Stand op 6 oktober 2026. Dit is de pagina om mee te beginnen. De rest van `docs/` is onderbouwing.

## Visie

HesPulse is een eerlijke handelsassistent voor eigen trading. Geen belofte van winst. Elke melding heeft een soort en elke soort
heeft een status die de metingen bepalen: nog te weinig data, verlies, positief, of bewezen. Wat niets oplevert, blijft zichtbaar
en meetbaar, en jij kiest of de push aan blijft. HesPulse plaatst nooit zelf een trade.

Het onderscheid met een gewone signaalgroep: jij ziet bij elke kans een compleet plan (limietorder, stop, take, R:R, live status)
en jij ziet wat elk soort melding echt opleverde, in R na kosten.

## Wat draait

| Onderdeel | Wat het doet | Waar |
|---|---|---|
| SMC-melding | Limietorder op de zone-rand, stop, take, R:R. Stop minimaal 0,2% | push, `/smc` |
| Zone-melding | Eén push zodra de koers in de zone komt | push |
| Radar | Handelsplan per kans met prijsladder en live status | `/smc` |
| Bewijs | Uitkomst per soort in R na kosten, weekcurve, status | `/bewijs` |
| Samenval | SMC en community-call wijzen dezelfde kant op (ongetest, gaat zelf uit na 30 negatieve) | push, Bewijs |
| Patroon, day trading, swing | Draaien nog. Push uitzetten per soort met `SIGNAL_TYPE_INFO_ONLY` | push, Bewijs |
| Weekrapport | Zondag 19:47, wat werkt en wat niet | `/meldingen` |
| Derivatenverzamelaar | Funding, open interest, taker, long/short, elk uur | `data/derivs` |
| Vandaag | Startpagina: markt-script per coin, agenda, liquidaties, nieuws, eigen score | `/vandaag` |
| Markt-script | Claude schrijft elke 4 uur scenario's met voorwaarde, de motor meldt ze (ongetest) | push, `/vandaag` |
| Nieuws en liquidaties | Koppen gesorteerd door Haiku, gedwongen sluitingen live bewaard | `/vandaag` |
| Extra coins | `EXTRA_COINS=...`, alleen SMC. Staat standaard leeg | `.env` |

## Wat gemeten is

- SMC, 12 maanden, 7 coins, 591 setups: -0,09R bruto, -0,40R netto. Geen kenmerk hield stand in train en test.
- Setups die een signaal werden: +0,03R bruto. De rest: -0,13R. De regels filteren dus in de goede richting.
- SMC, laatste 29 dagen: +0,32R bruto, +0,04R netto op 57 setups. Eén marktfase, geen bewijs.
- Day trading -0,23R bruto. Patroon live 31% winst en -0,34R op 117 trades.
- Derivatenkenmerken: geen verschil op 57 setups.
- Kalendermomenten (funding, VS-opening, expiry): geen voordeel. De VS-opening beweegt wel 1,9x harder dan een gewoon uur.
- Community-calls: richtingshint op 4 uur, n=28, niet bewezen.

Een soort krijgt de status positief vanaf 30 afgeronde trades met winst na kosten, en bewezen vanaf 100.

## Wat open staat

1. Schaduwrun op HBAR, WLD, ONDO, XRP (`/tmp/shadow.txt`). Uitkomst bepaalt welke coins naar `EXTRA_COINS` gaan.
2. Derivatentoets opnieuw draaien over 4 tot 6 weken (`scripts/smc_derivs_check.py`).
3. Update-melding naar alle gebruikers is nog niet verstuurd (`scripts/announce_update.py`).
4. Weekrapport-timer en derivaten-timer staan alleen aan als je ze op de VPS hebt geactiveerd.

## Beslisregels

- Geen filter of coin live zonder positieve uitkomst na kosten in train en test, met minstens 30 trades per helft.
- Geen nieuwe soort alert zonder status en zonder plek op Bewijs.
- Een soort uitzetten doe jij zelf, op basis van Bewijs. HesPulse zet niets vanzelf uit, behalve samenval.
