# HesPulse: het fundament voor bouwen met AI

Voor Ramon Hes. Dit document legt vast hoe je met Claude Code bouwt zodat het niet misgaat. Het gaat niet over de handelslogica; het plan daarvoor
is sterk (voorregistratie, bevriezing, netto meten, stopregel per instappunt). Het gaat over de afspraken eromheen, die in het project zelf moeten staan.

Bron: tekst van Ramon, 2026-11-09. De plakactie brak af in onderdeel 0 en liet onderdeel 1 weg ("1." staat alleen als mapstructuur). Wat ontbreekt
is hier niet aangevuld.

## 0. Het belangrijkste inzicht
Claude onthoudt niets tussen sessies. Het CLAUDE.md in je project is het enige geheugen dat elke sessie meekrijgt. Wat daar niet staat, bestaat
voor Claude niet. Wat er te veel in staat, kost bij elke beurt opnieuw tokens en verdrinkt de regels die ertoe doen.

Twee gevolgen:
- Het CLAUDE.md is een voorpagina, geen handboek: maximaal ongeveer 10 kB. Geschiedenis en uitleg horen in `docs/`.
- Een reg... (afgebroken in de plakactie)

## 1. Structuur
```
hespulse/
├── CLAUDE.md              voorpagina, max. 10 kB
├── config/                ALLE vaste waarden
│   ├── instapregels.yaml  A, B, B0, R, K ... met hun getallen
│   ├── poorten.yaml       BTC-poort, dagbudget, conflictregel
│   ├── meting.yaml        bevriezing, aantallen, stopregels
│   └── coins.yaml         de lijst coins
├── src/                   logica: leest config, bevat zelf geen getallen
├── tests/
│   └── fixtures/          vaste testcandles en verwachte uitkomsten
├── .claude/skills/        de vaste werkwijzen (zie 4)
└── docs/
    ├── blueprint.md       deze structuur en het waarom
    └── register/          het centrale register (zie 5)
```

## 2. Geen hard-coded waarden: config is de enige plek
Elk getal, elke drempel, lijst, coin, kost en tekstlabel staat in `config/`. De code zegt hoe, de config zegt wat.
- De toets: kan iemand die de code niet begrijpt een waarde veilig aanpassen door alleen een configbestand te openen? Zo niet, dan staat de waarde op de verkeerde plek.
- Geen uitzondering voor "het algoritme". Ook de getallen die de regels zelf uitvoeren (0,25 ATR, 6 candles herstel, 120 candles oud) staan in config.
- Afdwingen met een test, niet alleen met een regel: een test die faalt zodra er een los getal of een coinlijst in `src/` opduikt.
- De voorregistratie wordt uit de config gegenereerd of ertegen gecontroleerd. Dan kan het document nooit afwijken van wat draait.
- Elke wijziging van een configwaarde komt met datum en reden in het register (`wijzigingen-config.md`).

## 3. Zelfbevraging, en Ramon wordt altijd bevraagd
Bij elk plan en elke wijziging die niet triviaal is, werkt Claude in deze volgorde:
1. Zelfbevraging. Claude stelt zichzelf kritische vragen: wat kan hier misgaan, wat is slimmer, wat ontbreekt?
2. Gerichte vragen aan Ramon voor keuzes die alleen hij kan maken.
3. Score van 1 tot 100, met onderbouwing van wat punten kost.
4. Gate: onder de 95 geen go. Het plan wordt geoptimaliseerd tot het voldoet.
5. Go pas na een score van 95 of hoger én akkoord van Ramon.

Kleine routineklussen (typo, tekstwijziging) hebben geen formele score nodig.

Claude beslist nooit zelf over:
- een regel of een getal wijzigen
- wat "bewezen" is, of een hypothese promoveren
- juridische, fiscale of financiële zaken, en betalingen
- de scope, of een nieuwe feature
- de plek van de repo en wie toegang heeft

Bij elk van deze: stoppen en Ramon vragen. Een AI-oordeel of een AI-voorstel is nooit een besluit.

## 4. Skills: de vaste werkwijzen
Skills zijn vaste werkwijzen in `.claude/skills/<naam>/SKILL.md` die Claude op een bepaald moment oppakt. Begin met deze vijf:

| Skill | Wanneer | Wat |
|---|---|---|
| plan-gate | vóór elke grotere wijziging | zelfbevraging, vragen aan Ramon, score, wachten op akkoord |
| besluit-vastleggen | na elk akkoord of besluit | schrijft datum, besluit, reden en wie akkoord gaf in het register |
| smoketest | na elke wijziging, vóór release | draait de end-to-end keten, toont de uitvoer, meldt wat rood is |
| meting-draaien | na een wijziging in regels of config | draait tests en meetinstrumenten en vergelijkt met vorige uitkomst |
| sessie-afsluiten | einde van elke sessie | werkt stand en taken bij, vult het register aan en commit |

Elke skill staat zelf ook in het register (`skills.md`): wat hij doet, wanneer hij draait en waarom hij bestaat.

## 5. Het centrale register
Eén plek, `docs/register/`, met één index zodat Claude met één bestand weet waar alles staat:

| Bestand | Inhoud |
|---|---|
| index.md | overzicht van alle registers, één regel per bestand |
| besluiten.md | datum, besluit, reden, wie akkoord gaf |
| hypotheses.md | idee, status (open, gemeten, verworpen), bewijs |
| bewijs.md | meetresultaten per instappunt, smoketest-uitslagen met datum en commit |
| skills.md | welke skills er zijn, wanneer gebruikt, waarom |
| wijzigingen-config.md | elke wijziging van een vaste waarde met reden |
| taken.md | één actieve taak |
| parkeerlijst.md | nieuwe ideeën; die starten geen werk |
| leveringen.md | wat wanneer is uitgeleverd of live gezet, met versie en commit |

Het CLAUDE.md verwijst naar `index.md` en bevat zelf geen inhoud van het register.

## 6. Smoketest: altijd, end-to-end
De keten staat al in het plan (candles, model, plan, melding, vulling, uitkomst, kosten, bewijs, export). Dat is het pad dat de smoketest loopt.
- Eén commando draait de hele keten met vaste testcandles en vergelijkt de uitkomst met een vooraf vastgelegde verwachting. Geen live data, geen echte order, geen echte betaling.
- Vergelijken is de standaard. De verwachte uitkomst vastleggen is een aparte, bewuste handeling met een besluit in het register. Een rode smoketest wordt nooit stilletjes bijgewerkt om groen te worden.
- Wanneer: na elke wijziging aan regels, config of code, vóór elke inhoudelijke commit en vóór elke release.
- Rood = geen commit en geen go. Claude toont de uitvoer en zegt niet "klaar" zonder die.
- Een aparte live-smoketest tegen de echte databron, zonder orders en met betalingen in testmodus. Die draait Ramon zelf vóór een release.
- De uitslag gaat in `bewijs.md`, met datum en commit.

## 7. Versiebeheer
Alles in git. Commit per afgeronde, logische stap. Berichten kort, in het Nederlands: wat en waarom.
- Voorkeur: Gitea (zelf gehost, privérepo), zodat code en data in eigen beheer blijven. Een tag per release.
- Geen geheimen in git. Sleutels, wallet-gegevens en toegangscodes staan in `.gitignore` en in een apart, niet-gecommit bestand. Een automatische controle op geheimen vóór elke commit is verplicht, omdat er betalingen in SOL in het spel zijn.
- De plek van de repo (lokaal of Gitea) en wie toegang heeft is een besluit van Ramon, vastgelegd in het register.

## 8. Werkafspraken met Claude
- Eén sessie per klus. Een ander onderwerp is een nieuwe sessie; geen marathonsessies.
- Klaar = gemeten. Claude toont de testuitvoer voordat het "klaar" zegt.
- Nieuw idee = parkeerlijst. Een nieuw idee start geen werk.
- Zwaar meetwerk draai je zelf in de terminal en plak je alleen de uitslag of de rode regel.
- Geen grote bestanden of logs integraal plakken. Zoek gericht en lees een uittreksel.
- Plakcode altijd compleet. Bij code die je moet plakken: het hele blok, ook bij één gewijzigde regel.

## Verschil met nu (2026-11-09)
| Document | Nu | Besluit |
|---|---|---|
| CLAUDE.md max 10 kB | 63 kB | inkorten is een aparte taak (parkeerlijst) |
| `config/*.yaml` met alle getallen | constanten in `app/*.py` en `.env` | niet nu: bevroren model en golden tests; eigen taak na 2026-11-24 |
| Register in `docs/register/` | `docs/onderzoek/` en `docs/taken/` | `docs/register/index.md` wijst ernaar; geen verhuizing |
| Smoketest end-to-end | golden tests en `tests/` | de skill `smoketest` draait de bestaande tests; een keten met vaste candles is een aparte taak |
| Gitea | GitHub | besluit van Ramon |
| Geheimenscan voor commit | niet aanwezig | parkeerlijst |
