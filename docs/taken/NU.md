# Nu aan het werk

Eén taak tegelijk. Lees dit bestand aan het begin van elke sessie.

## Actieve taak
06 TradingView-indicator (HesPulse Clean): `06-tradingview-script.md`

## Wacht op de VPS, data of tijd
- 01 Model live controleren (H2): `01-model-live-controle.md` (VPS nodig)
- 02 Bevriezing bewaken: `02-bevriezing-bewaken.md`
- 03 4u-context (H1): `03-context-4u-h1.md`
- 04 Controle op de modelcijfers: `04-cijfers-controle.md`
- 05 Ordertype vergelijken: `05-ordertype-vergelijking.md`

## Op afroep
- 07 Verbeterlus en schaduw: `07-verbeterlus-schaduw.md`
- 08 Backtesten: `08-backtesten.md` (start na 01)

## Regels
- Werk alleen aan de actieve taak.
- Een nieuw idee komt hieronder in de parkeerlijst. Het start geen werk.
- Wissel de actieve taak alleen na een besluit van de CEO. Noteer het in `docs/onderzoek/besluiten.md`.
- Sluit elke sessie af met een regel in het taakbestand onder "Stand van nu" en "Volgende stap".

## Parkeerlijst
- Short in discount na een lange daling (NEAR, 2026-11-03): het model heeft geen scenario als geen pool in premium binnen 6% ligt. Meten met een stille arm en een eigen preregistratie, pas na de bevriezing. Case: `docs/onderzoek/cases/2026-11-03-near-short-discount.md`. Tweede geval: ZEC 4u short (2026-11-07), case `docs/onderzoek/cases/2026-11-07-zec-4u-short-eigen-trade.md`; 85 van 157 missers die het model niet zag hebben deze reden. Uitkomst van beide CEO-trades nog invullen.
- Conformatie zichtbaar in het TradingView-script (WLD en BTC, 2026-11-04): na een prik onder een bodem toont het script geen sweep en geen 15m-CHoCH tegen de dag in als lijn, alleen "herstel" in de trendregel (`tradingview/hespulse_structuur.pine`, `tradingview/README.md` "Wat hij niet doet"). Besluit CEO nodig: alleen tekenen, geen motorregel, geen melding.
- Ideeën voor HesPulse Clean (2026-11-08), pas na de eerste compileerrapportage van de CEO: (1) statusregel rechtsboven met de stap van de keten ("sweep gezien, wacht op shift 14 van 24"); (2) na L+ het plan van het model tekenen (limiet in de FVG of de overlap met het OB, stop 0,25 ATR achter de prik, doel de range-rand) in het bestaande positievak, zonder handmatige invoer; (3) de 4u-range als poort op L+ en S+ (premium en discount), zodat ze dichter bij entry A liggen; (4) gelijke pools groeperen tot één pool; (5) de keten van 15m ook op 5m en 1m tonen via `request.security`; (6) een gesweept niveau een korte tijd markeren; (7) per setup één alert, L? stil en L+ luid. Geen TradingView-strategy voor winst: dat is taak 08.
