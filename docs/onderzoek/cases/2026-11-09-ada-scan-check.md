# ADA-case: scant HesPulse dit, en is de uitleg duidelijk? (2026-11-09)

Alleen gelezen. Geen regel, constante of code gewijzigd. Case: `2026-11-09-ada-15m-short-stop-op-de-pool.md`.
Peil: branch `claude/crypto-day-trading-alerts-geb2v7` op 5530ac6, export `hespulse-2026-11-09.json` (gemaakt 03:17 UTC, vóór de case).

## Vraag 1. Scannen we dit? Gedeeltelijk.

Alleen het HesPulse-model meldt. Structuur, zone-radar, zone-sweep en POC-radar zoeken niets meer en melden niets
(`app/focus.py:27-33` `engine_on`, `:45-48` `alerts_on`; met `HESPULSE_MODEL_ENABLED` en `MODEL_ONLY_ALERTS` aan). Zij vallen dus af, ook
als hun regel de situatie zou passen.

Het model heeft voor een short na een prik boven een 4u-top wel een pad. Per stap, voor de situatie op ~15:50 UTC:

- Dagrichting (`DailyBias`, `app/model.py:227-243`): dag omlaag. Voldaan, short is toegestaan.
- Context 4u (`Context4h`, `:191-224`, top-down): 4u omlaag, dus een range uit de laatste 4u-breuk. Voldaan.
- Pool (`Pools.valid`, `:301-304`; `MAX_DISTANCE_PCT` 6%, `:38`): de pool is de 4u-BSL op 0,1823 uit de case. Voor short moet hij tussen EQ en H
  liggen (premium, gespiegeld) en onaangeraakt zijn. De case noemt "113% premium", dus de ligging klopt. Of de pool een 1u-swing is
  (het model gebruikt 1u-pools, `:36`) staat niet in de case. Niet vast te stellen.
- Sweep (`_step` fase prik, `:648-676`; `PRIK_MIN_ATR` 0,1, `PRIK_MAX_ATR` 2,5, `HERSTEL_BARS` 6, `:39-41`): de prik tot ~0,1853 is 0,0030 boven
  de pool. Of dat tussen 0,1 en 2,5 ATR(15m) ligt hangt van de ATR; die staat niet in de case. Het herstel (slot terug onder 0,1823) was er
  op het moment van de entry niet: de koers stond op 0,1825. Niet voldaan.
- Shift (`:679-686`, `SHIFT_BARS` 24, `:42`): een 15m-slot onder de laatste 15m-bodem van vóór de prik. Niet voldaan (geen breuk omlaag).
- Displacement en gap (`displacement` `:351`, `DISP_ATR` 1,0 in 5 candles, `:43-44`): niet voldaan.
- Entry en stop (`_plan` `:614`; `STOP_ATR` 0,25, `MIN_STOP_PCT` 0,4%, `:45-46`, `_floor` `:335`): het model zou de stop 0,25 ATR boven het
  prikuiterste zetten (>= ~0,1853), niet op 0,1823. De eigen stop lag dus op de pool, het model zet hem erachter.

Conclusie: de entry kwam vóór sweep-herstel, shift en displacement. Er kon op dat moment geen modelplan bestaan. Het model had een
scenario in wachtstand kunnen hebben (status `wacht_sweep` of `prik`), geen entry.

## Vraag 2. Had het model een ADA-scenario? Niet vast te stellen.

- De export van 2026-11-10 staat niet op `origin/hespulse-data`. Die van 2026-11-09 is van vóór de case.
- Het veld `model` bevat alleen aggregaten (trechter, meting), geen scenario's per coin. `signalen` bevat voor ADA alleen vier oude
  zone-sweep- en zone-radar-shorts van 2026-10-28 en 29.
- `auto_missers` heeft 18 ADA-regels, geen over deze case. Een voorbeeld (long, 8 nov 21:00 UTC, 4,5%): het model zocht geen long omdat de dag
  short wees. Dat is de dagregel, niet deze case.
- De live database op de VPS (`model_scenarios`, `alt_log`) is niet gelezen.

## Vraag 3. Is het voor een gebruiker duidelijk? Gedeeltelijk.

- Wat het model afwacht: ja, bij een bestaand scenario. `app/model_card.py:20` (`STATE_SHORT`) en `waiting_text` `:189-200` noemen prik,
  slot terug binnen 6 candles, slot voorbij de top van vóór de sweep, displacement en gap. `STEP_NAMES` `:21`.
- Dat een entry vóór bevestiging buiten het model valt: nee. Geen tekst in `model_card.py`, `chance_steps.py`, `kansen.py`, de templates of
  `order.js` zegt dat een eigen entry vóór sweep-herstel en shift geen modelplan is.
- Waarschuwing bij een eigen stop op een pool of BSL/SSL: nee. `chance_steps.py:36,37,142` en `kans.html:50` tonen alleen het stopafstand-
  percentage van het plan. Er is geen invoer voor een eigen stop, dus ook geen controle.
- Het TradingView-script `tradingview/hespulse_structuur.pine` toont de conformatie niet. Alleen " herstel" in de trendregel (`:379`).
  README `:24-28` zegt dat pools, sweeps en instappunten er niet in staan. `hespulse_clean.pine` (Clean 4) heeft wel BSL/SSL en L?/S?/L+/S+,
  maar geen 15m-CHoCH tegen de dag als aparte markering en is nog niet in TradingView gecompileerd (README `:70`).

## Bevindingen, op gevolg voor de gebruiker

1. Geen tekst zegt dat een entry vóór de bevestiging buiten het model valt. Alleen tekst/weergave (kaart, detailblad, handleiding).
2. Geen waarschuwing als een stop op een pool of BSL/SSL ligt. In de app bestaat geen eigen-stop-invoer; alleen een tekst bij de checklist
   of in de handleiding is mogelijk. Tekst/weergave. Een regel in het model hoort hier niet bij.
3. De staat "prik bezig, wacht op slot terug" bestaat in de kaart (`waiting_text`), maar alleen voor een bestaand scenario. De case had een
   zichtbaar vooraf-signaal nodig: de pool en de wachtregel. Of het scenario op ADA bestond is onbekend (vraag 2).
4. Het TradingView-structuurscript toont geen conformatie. Clean 4 toont de keten wel (L?, L+). Tekst/weergave, al op de parkeerlijst.
5. Scenario's per coin staan niet in de nachtexport. Daardoor is zo'n case achteraf niet uit de export te controleren. Meting, geen modelregel.

Er is geen modelregel die ik wijzig of voorstel om te wijzigen. Het model gedraagt zich zoals vastgelegd.

## Niet gecontroleerd

- De live database op de VPS en het scenario van ADA op dat moment.
- De export van 2026-11-10.
- ADA-candledata van 9 november (ATR(15m), exacte prikdiepte, of de 4u-BSL ook een 1u-swing-pool was). De tijd 15:50 UTC volgt uit een
  telefoonklok en is een aanname.
- Clean 4 in TradingView.
