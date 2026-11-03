# Model live controleren (H2)

Status: wacht op uitvoer van de CEO
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

## Checklist voor de CEO (op de VPS)

Het script leest alleen. Het schrijft niets in de database en stuurt geen melding.

1. Ga naar de map van de repository en haal de laatste code op van deze branch.
2. Draai, met de venv van de VPS:

```bash
.venv/bin/python3 scripts/model_kaarten.py --dagen 14 --aantal 30 --tekst --uit data/model_kaarten.html > data/model_kaarten.txt 2>&1
```

   - `--dagen 14` en `--aantal 30` zijn de standaardwaarden uit H2. Laat ze staan.
   - Zet geen `--coins` en geen `--zonder-controle`. De herberekening zonder latere candles is de toets zelf.
   - `--tekst` geeft elk scenario ook als tekst. Zo hoef je geen screenshots te sturen.
3. Draai de nachtexport-sectie voor de uitvoerbaarheid. De kaarten tonen niet of de koers bij de melding al door de limiet stond:

```bash
.venv/bin/python3 scripts/nacht_export.py --zonder-missers
```

   Plak daarna de sectie "HesPulse-model (ongetest)" uit het `.md`-bestand in `data/export/`.
4. Plak terug in de chat:
   - de eerste regel van de uitvoer (`N scenario's getekend ...; M met een afwijking`);
   - de volledige tekst uit `data/model_kaarten.txt`;
   - de sectie "HesPulse-model (ongetest)": trechter, "Vulbaar bij melding", "niet vulbaar", "terugtest al geweest", "vertraging entry";
   - de datum en tijd van de run, en de commit (`git rev-parse --short HEAD`) op de VPS.
5. Meld ook een fout, zoals een coin zonder candles of een lege POC-database. Zonder POC-meting draait het script zonder POC-kandidaten.

## Toetsplan voor Claude (zodra de uitvoer er is)

- Prefix-vast: elke regel `!! afwijking zonder latere candles` is een rode stap. Per rode stap: oorzaak vinden, regressietest, dan pas verder (beslisregel H2).
- Tel het aantal scenario's. Staan er minder dan 30, noteer dat als feit, niet als fout.
- Entry al voorbij bij de melding: komt uit de modelsectie van de export (`niet_vulbaar`, `terugtest_al_geweest`) en uit de regels `✕ poging ... terugtest_al_geweest` in de tekst. Het kaartenscript kent de koers bij publicatie niet.
- Per scenario noteren: stap, tijdstip, afwijking ja of nee, oorzaak.
- Een afwijking die de spec breekt is een fout in de code. Geen afstelling van regels, geen aanpassing van `app/model.py` (bevroren).
- Geen regel afstellen op een voorbeeld.

## Stand van nu
Nog niet gedraaid. Dit blokkeert het vertrouwen in taak 02 tot 05. Alleen de CEO kan dit op de VPS doen. Script, preregistratie en tests gelezen; checklist voor de CEO staat hierboven. De tests in `tests/hespulse_model/` draaiden niet in de ontwikkelcontainer (ontbrekende pakketten, zoals `ta`), dus daar is niets mee aangetoond.

## Besluiten en bronnen
`docs/onderzoek/hypotheses.md` (H2), `docs/onderzoek/hespulse-model/preregistratie.md`, `tests/hespulse_model/`.

## Volgende stap
CEO volgt de checklist, draait `scripts/model_kaarten.py` met `--tekst` op de VPS en plakt de uitvoer plus de modelsectie van de export in de chat.
