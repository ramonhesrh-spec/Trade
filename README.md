# HesPulse

Crypto day trading alertsysteem. Combineert Discord DM berichten en live
technische data, en stuurt pushmeldingen naar je telefoon of browser. Het
systeem voert geen trades uit. Jij beslist zelf.

## Hoe het werkt

Jij stuurt zelf relevante berichten uit een betaalde Discord community door,
via Forward, naar de DM van je eigen bot account. Het systeem leest die DM,
interpreteert de tekst via de Anthropic API, toetst dat tegen live koersdata
op Binance, en stuurt een pushmelding. Alles wordt gelogd in een sqlite
database en is terug te zien in het webdashboard, inclusief een rustige
meldingenlijst op `/meldingen`.

Meerdere mensen kunnen hetzelfde systeem gebruiken. Iedereen ziet dezelfde
signalen (dezelfde Discord berichten, dezelfde technische toetsing), maar
elke gebruiker heeft zijn eigen login, eigen instellingen (stille uren,
bevestigingsdrempel, verplichte factoren), eigen pushmeldingen, en zijn
eigen logboek: status, entry, exit en notities. De ene gebruiker kan het
logboek van de andere niet zien of wijzigen.

De website heeft een openbaar deel en een besloten deel. Op `/` staat een
publieke landingspagina, met een korte uitleg en een over ons sectie.
Iedereen die de site bezoekt kan via `/registreer` zelf een account
aanmaken, dat is een bewuste keuze, geen invite-only systeem. Na
registreren of inloggen kom je op `/dashboard`, het besloten logboek, dat
blijft voor elke gebruiker apart.

## Focus: welke soorten nu melden

Sinds oktober 2026 zoeken en melden alleen drie soorten nog nieuwe kansen: Structuur A/B (`structuur`), Structuur C (`structuur_c`) en de
zone-radar (`zone_radar`). De zone-sweep draait live en ongetest (op verzoek van de eigenaar, zonder labrun). Alle andere soorten staan uit, zodat de app overzichtelijk blijft
en ze later één voor één verbeterd kunnen worden: day trading via Discord, patroon (uitbraak, trendlijn, chart-patroon), trend, rejectie,
het markt-script, SMC en SMC met waarschuwing, swing, samenval, de range sweep en range-watch, en de proefmotor (`don55_trend`).

Uitzetten is geen weggooien: code en data blijven, en `ENGINE_FOCUS=false` in `.env` zet alles terug zoals het was (herstart `crypto-bot`,
`crypto-web` en de timers pakken het bij hun volgende ronde op). De bron van waarheid is `app/focus.py`.

- **Motoren:** een uitgezette motor zoekt niets nieuws en stuurt geen nieuwe melding. Zijn hartslag zegt `uit door focus`
  (`scripts/push_diag.py` toont ze). Een eigen vlag zoals `TREND_ENABLED` of `RANGE_SWEEP_ENABLED` geldt daarnaast gewoon.
- **Discord:** een doorgestuurd bericht wordt nog opgeslagen en gededupliceerd, maar niet meer aan Anthropic voorgelegd; er komt geen
  signaal, journaalregel of push uit.
- **Lopende trades:** `app/level_check.py`, `rule_live.update_open` en het volgen van de range sweep blijven open posities, stops en doelen
  volgen en melden hun uitkomst tot ze sluiten. Een wachtende SMC-setup wordt geen signaal meer en staat niet meer op de Radar.
- **Weergave:** Kansen en de tellers (dok, appicoon) tonen alleen nieuwe en wachtende kansen van de focus-soorten; een open trade van
  een uitgezette soort blijft staan onder zijn eigen naam (een eigen tab op Kansen, of Verder open op Markt). Het markt-script verdwijnt van Markt.
- **Bewijs:** de focus-soorten staan bovenaan en open, de andere onder "Uitgezet, ter verbetering" met hun eindcijfers (n, doel, stop,
  netto R). Niets verdwijnt.
- **Pushbudget:** de regels van `push_policy` zijn niet veranderd; omdat alleen de focus-soorten nog iets nieuws melden, gaat het dagbudget
  in de praktijk alleen naar hen.

## Onderdelen

- `app/discord_bot.py` — leest DM's, alleen leesrechten
- `app/anthropic_interpret.py` — interpretatie van tekst en afbeeldingen
- `app/coinlist.py` — dynamische coinlijst
- `app/exchange.py`, `app/indicators.py` — live koersdata en indicatoren (4h)
- `app/risk.py` — stop loss, take profit op basis van ATR
- `app/signal_processor.py` — verbindt alle stappen, met een paar
  herhaalpogingen bij een tijdelijke Anthropic storing, herkent dubbele
  berichten, en zet een nieuw signaal af tegen recente lange termijn context
- `app/push_notify.py` — Web Push meldingen (eigen VAPID-sleutelpaar, geen
  externe pushdienst)
- `app/repo.py`, `app/db.py`, `app/schema.sql` — sqlite logging
- `app/backup.py` — dagelijkse back-up, optioneel ook naar een externe locatie
- `app/heartbeat.py` — dagelijks levensteken via pushmelding
- `app/level_check.py` — periodieke check: heeft een open trade zijn stop
  loss of take profit al geraakt, en is de prijs weer terug bij het niveau
  van een nog niet genomen signaal (proactief, niet alleen bij een nieuw
  Discord bericht)
- `app/market_scanner.py` — autonome marktscan: ontdekt zelf een
  day-trading kans in de dynamische coinlijst, zonder dat een gebruiker
  eerst een Discord bericht doorstuurt, elke 20 minuten via een eigen systemd timer
  (hergebruikt dezelfde toetsings- en fan-out-logica als een normaal
  signaal)
- `web/` — FastAPI dashboard met login, inclusief een berichtenoverzicht op
  `/berichten` van alles wat wel en niet tot een melding leidde, een
  trackrecord per coin, en een csv export van je logboek

## Opzet, stap voor stap

### 1. Discord bot aanmaken

1. Ga naar https://discord.com/developers/applications en maak een nieuwe
   applicatie aan.
2. Tabblad Bot, klik Add Bot, kopieer de token direct naar een veilige plek.
   Deel deze token met niemand.
3. Zet bij Privileged Gateway Intents de optie **Message Content Intent** aan.
4. Maak een klein eigen Discord servertje aan, alleen voor jezelf, en nodig
   de bot daar uit via OAuth2 > URL Generator, met scope `bot` en
   permissions `View Channels` en `Read Message History`.
5. Zet de token in `.env` als `DISCORD_BOT_TOKEN`.

### 2. VAPID-sleutelpaar genereren (Web Push)

Eén keer genereren, hetzelfde sleutelpaar geldt voor alle gebruikers. Bewijst
aan Apple/Google dat een melding echt van HesPulse komt (RFC 8292), geen
account of registratie bij een externe partij nodig.

```bash
python3 -c "
from py_vapid import Vapid02
v = Vapid02()
v.generate_keys()
print('VAPID_PUBLIC_KEY=' + v.public_key_str())
print('VAPID_PRIVATE_KEY=' + v.private_key_str())
"
```

Zet beide waarden in `.env` als `VAPID_PUBLIC_KEY` en `VAPID_PRIVATE_KEY`,
en vul `VAPID_CLAIM_EMAIL` in (een contactadres, verplicht door de Web
Push-standaard). Elke gebruiker zet daarna zelf, na het inloggen, zijn eigen
pushmeldingen aan via de knop "Meldingen aanzetten" op zijn dashboard, geen
losse token of chat ID per gebruiker nodig.

### 3. Anthropic API sleutel

Zet je Anthropic API sleutel in `.env` als `ANTHROPIC_API_KEY`.

### 4. Lokale installatie en accounts aanmaken

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# vul .env verder aan met je tokens, en kies een lange willekeurige JWT_SECRET

python3 scripts/create_user.py
# maakt de database aan (als die nog niet bestaat) en je eigen account,
# met gebruikersnaam, wachtwoord, portfolio en risicopercentage.
```

Dit script is voor jou als beheerder: handig om je eigen eerste account
aan te maken, of om iemands wachtwoord of instellingen te herstellen.
Voor je vrienden hoeft dat niet, die maken zelf een account aan via
`/registreer` op de site zelf, zie hieronder.

### 5. Testen, per bouwstap

```bash
# Stap 1: technische data en indicatoren voor bitcoin, los van Discord
python3 scripts/test_step1_bitcoin.py

# Stap 2 t/m 5: bot starten, DM's worden gelezen, geïnterpreteerd, getoetst
# en gemeld via een pushmelding
python3 main.py

# Stap 6 t/m 8: dashboard starten
uvicorn web.main:app --reload
# open http://127.0.0.1:8000, dat is de openbare landingspagina.
# Klik op Inloggen, of ga direct naar /login, en log in met je wachtwoord.
```

Stuur daarna een testbericht (eventueel met een screenshot van een
grafiek met ingetekende niveaus) naar de DM van je bot om de hele keten te
zien werken.

## Hosting op een VPS

Zet dit hele project op een kleine VPS (bijvoorbeeld Hetzner of
DigitalOcean, een paar euro per maand, altijd aan). Draai de bot, de
verwerking en het dashboard op die ene VPS, zodat alles blijft werken
vanaf je telefoon, waar je ook bent, zonder dat je eigen computer aan
hoeft te staan.

```bash
sudo adduser --system --group crypto
sudo mkdir -p /opt/crypto-alerts
sudo chown crypto:crypto /opt/crypto-alerts
# kopieer het project naar /opt/crypto-alerts, of clone via git
cd /opt/crypto-alerts
sudo -u crypto python3 -m venv .venv
sudo -u crypto .venv/bin/pip install -r requirements.txt
sudo -u crypto cp .env.example .env
# vul .env in als vaste gebruiker crypto
sudo -u crypto .venv/bin/python3 scripts/create_user.py
# maakt de database aan en je eigen account. Draai dit nogmaals voor elke
# extra gebruiker.
```

### Achtergrondprocessen met automatisch herstarten

```bash
sudo cp deploy/crypto-bot.service /etc/systemd/system/
sudo cp deploy/crypto-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-bot crypto-web
```

`Restart=always` zorgt dat beide processen automatisch herstarten bij een
crash.

### Dagelijkse back-up

```bash
sudo cp deploy/crypto-backup.service /etc/systemd/system/
sudo cp deploy/crypto-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-backup.timer
```

Dit maakt elke nacht om 03:00 een kopie van de database in `data/backups/`,
en bewaart de laatste 30 back-ups.

Een lokale kopie op dezelfde VPS beschermt niet tegen schijfschade op die
VPS. Zet daarom ook `BACKUP_REMOTE` in `.env`, bijvoorbeeld
`user@andere-server:/pad/naar/backups/`. Elke back-up wordt dan automatisch
ook naar die locatie gestuurd via `rsync` over SSH. Dit vereist een SSH
sleutel zonder wachtwoord tussen de VPS en die andere locatie:

```bash
sudo -u crypto ssh-keygen -t ed25519 -f /opt/crypto-alerts/.ssh/id_ed25519 -N ""
sudo -u crypto ssh-copy-id -i /opt/crypto-alerts/.ssh/id_ed25519.pub user@andere-server
```

Zonder `BACKUP_REMOTE` blijft de back-up alleen lokaal staan, dat werkt
prima om per ongeluk verwijderde data terug te halen, maar niet als de VPS
zelf uitvalt.

### Levensteken

```bash
sudo cp deploy/crypto-heartbeat.service /etc/systemd/system/
sudo cp deploy/crypto-heartbeat.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-heartbeat.timer
```

Stuurt elke ochtend om 09:00 een korte pushmelding naar elke gebruiker:
"Goedemorgen trader. Nieuwe dag, nieuwe kansen. HesPulse draait, laatste
controle: ..." Zonder dit merk je een crash pas op als er een tijd lang
geen meldingen meer binnenkomen.

### Systeemzelfcheck

```bash
sudo cp deploy/crypto-health-check.service /etc/systemd/system/
sudo cp deploy/crypto-health-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-health-check.timer
```

Checkt elk uur of alle vijf systeemonderdelen (bot, dashboard, back-up,
levensteken, niveau-check) echt actief én enabled zijn, en legt zodra er
iets ontbreekt een admin-only rij vast op `/meldingen` (zichtbaar voor het
account waarvan de gebruikersnaam gelijk is aan `ADMIN_USERNAME` in
`.env`). Zonder `ADMIN_USERNAME` blijft dit alleen in de serverlog staan.
Dit is ontstaan doordat de back-up- en levensteken-timer op deze VPS ooit
nooit geïnstalleerd bleken te zijn, zonder dat iemand dat opmerkte, zie ook
`app/health_check.py`.

Dezelfde `ADMIN_USERNAME` bepaalt ook welk account op het dashboard de
"niet herkende berichten" sectie te zien krijgt: dat is een
operator-signaal (staat de AI-interpretatie goed?), geen bruikbare
informatie voor een gewone gebruiker, zie `web/main.py:dashboard()`.

### Wekelijkse en maandelijkse samenvatting

```bash
sudo cp deploy/crypto-weekly-summary.service /etc/systemd/system/
sudo cp deploy/crypto-weekly-summary.timer /etc/systemd/system/
sudo cp deploy/crypto-monthly-summary.service /etc/systemd/system/
sudo cp deploy/crypto-monthly-summary.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-weekly-summary.timer crypto-monthly-summary.timer
```

Zet voor elke gebruiker een korte samenvatting klaar op `/meldingen`:
aantal signalen, winrate, resultaat, beste en zwakste trade. Een rustige
melding, geen pushmelding: hij staat te wachten tot je zelf de pagina
opent. Wekelijks op zondagavond 20:00, maandelijks op de 1e van de maand
om 09:00. Geen rij als er in die periode niks gebeurd is, dat voorkomt een
lege samenvatting.

### Seintje bij geraakte stop loss of take profit

```bash
sudo cp deploy/crypto-level-check.service /etc/systemd/system/
sudo cp deploy/crypto-level-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-level-check.timer
```

Checkt elke 15 minuten twee dingen:
- Heeft een open trade (eigen entry ingevuld, nog niet gesloten) de stop
  loss of take profit al geraakt op de live prijs.
- Is de prijs weer terug binnen 0,5x ATR van het niveau van een signaal dat
  nog niet als eigen trade genomen is. Zo krijg je ook een seintje als een
  eerder gemiste kans weer interessant wordt, niet alleen op het moment
  dat het bericht zelf binnenkomt.

Beide sturen één keer een seintje per logboekregel, geen herhaling zolang
er niets verandert. Een reset in het dashboard maakt een nieuw seintje
weer mogelijk.
Zo ja, dan krijg je daar één keer een pushmelding over, met het
verzoek om de trade zelf te sluiten in het dashboard. Er wordt niets
automatisch gesloten, en je krijgt niet elke 15 minuten opnieuw hetzelfde
seintje.

### Autonome marktscan

```bash
sudo cp deploy/crypto-market-scan.service /etc/systemd/system/
sudo cp deploy/crypto-market-scan.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-market-scan.timer
```

Draait elke 20 minuten (op minuten 07/27/47, niet op het `*:0/15`-grid van
`crypto-level-check.timer` hierboven) en toetst zelf elke coin uit de
dynamische coinlijst op een day-trading kans, zonder dat er
eerst een Discord bericht doorgestuurd hoeft te worden. Richting komt uit
de EMA9/EMA21 trend, de rest van de toetsing (technische factoren, stop
loss, take profit, pushmelding per gebruiker) is exact dezelfde
`process_day_trading_signal`-logica als een normaal, door een gebruiker
doorgestuurd signaal.

Een systeembrede noodrem staat op het dashboard (Instellingen): staat die
uit, doet de scan niets die cyclus. Er is geen noodrem per gebruiker, dit
is een systeembrede instelling.

### Snelle SMC-check

```bash
sudo cp deploy/crypto-market-scan-smc.service /etc/systemd/system/
sudo cp deploy/crypto-market-scan-smc.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-market-scan-smc.timer
```

Draait los van de marktscan hierboven, elke 5 minuten (op minuten
03/08/13/.../58, buiten zowel `crypto-level-check.timer`'s als
`crypto-market-scan.timer`'s eigen grid). Alleen de SMC-structuurbreuk-
check, niets van de drie 4u-detectoren: SMC reageert op 15m-candles en
heeft dus veel meer baat bij een korte cyclus dan die 4u-detectoren, die
toch pas om de 4 uur nieuwe data krijgen. Gebruikt dezelfde
systeembrede noodrem hierboven.

Een stop dichter dan `SMC_MIN_STOP_PCT` (standaard 0,4% van de entry) wordt verbreed tot die afstand, niet geweigerd. Dit geldt voor
SMC, Structuur, Trend en het markt-script. Uit het meetraam: stops onder 0,1% wonnen 6% en verloren gemiddeld -0,73R, omdat ze binnen de
ruis van een minuutcandle liggen, en een stop van 0,2% wordt al geraakt door een prijsverschil tussen twee beurzen. De R:R zakt mee en
de kans valt af als die onder 2 komt. Zet de waarde op 0 in `.env` om het uit te zetten. De timers starten elke keer een nieuw
proces en lezen `.env` opnieuw, dus daarvoor is geen herstart nodig.

### Wekelijks kwaliteitsrapport

```bash
sudo cp deploy/crypto-quality-report.service /etc/systemd/system/
sudo cp deploy/crypto-quality-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-quality-report.timer
```

Elke zondag om 19:47 meet `app/quality_report.py` zelf wat werkt: de uitkomst per type scan-signaal (smc, patroon,
day_trading, swing) in R, en de community-calls (gaat de koers na een bericht de kant van het bericht op, tegen een
controle van dezelfde coin en richting op willekeurige momenten, en wat levert elke call als vaste trade). Het rapport
komt als rustige melding op `/meldingen` bij `ADMIN_USERNAME` (of `--user`). Een oordeel over de community staat er
pas bij 60 onafhankelijke calls. Het script haalt 1m-candles op voor coins met minstens 8 calls en houdt die bij.
Direct proberen: `sudo -u crypto /opt/crypto-alerts/.venv/bin/python3 -m app.quality_report` in `/opt/crypto-alerts`.

### Derivatendata verzamelen

```bash
sudo cp deploy/crypto-derivs.service deploy/crypto-derivs.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-derivs.timer
sudo systemctl start crypto-derivs.service   # eerste keer: haalt 29 dagen terug op
```

`app/derivs.py` bewaart per coin funding, open interest, taker-verhouding en long/short (5 minuten) in
`data/derivs/<COIN>.csv`. Candle-kenmerken zijn uitgeput, dit is nieuwe informatie om SMC en day trading mee te
toetsen. Binance geeft maar ~30 dagen history; elke dag zonder verzamelaar is voorgoed kwijt.

### Extra coins

`EXTRA_COINS=XRP,HBAR` in `.env` voegt coins toe aan de vaste zeven. Daarop draait alleen de SMC-check, niet de 4u-detectoren
(patroon, uitbraak, trendlijn). Community-berichten over die coins worden wel herkend. Toets eerst met
`scripts/replay_smc_report.py --coins XRP,HBAR` en `scripts/replay_smc_setup_analysis.py` of SMC er na kosten positief is.
Herstart `crypto-bot` en `crypto-web` na een wijziging. De derivatenverzamelaar pakt de nieuwe coins vanzelf mee. Een coin
weghalen kan door hem uit `EXTRA_COINS` te halen: de coin gaat op inactief, er gaat niets verloren.

Voor de range sweep-proef (hieronder) moeten ARB, APT, AAVE en WLD in de coinlijst staan: `EXTRA_COINS=ARB,APT,AAVE,WLD`. Op een verse
database bestaan alleen de vaste zeven, dus ARB ontbreekt; zonder de coin in de lijst bestaat zijn coinpagina niet (404) en weigert het
prijsalarm hem. De range sweep-motor zelf scant de 20 coins van `trendlab.LAB_COINS` (daar staan ARB, APT en AAVE in, WLD niet) en
gebruikt `EXTRA_COINS` niet om coins te kiezen; WLD krijgt dus een coinpagina en prijsalarm, maar geen automatische kaart.

### Range sweep en range-watch (proef)

Onze lezing van een range-sweep-strategie: een echte range, een zone als vak (aanbod of vraag), een limiet in de zone en een stop voorbij de
buitenkant. Er is geen vast doel: de proef meet de kwaliteit van de stop (hoe vaak de stop raakt, hoe ver de koers meeliep, de kans op +1R
tot +6R vóór de stop, de kosten in R). Alles staat vooraf vastgelegd in `docs/onderzoek/range-sweep/preregistratie.md`, de labrun op de VPS
staat in `docs/onderzoek/range-sweep/vps-protocol.md`. De motor (`app/range_sweep_live.py`) en de range-watch (`app/range_watch.py`) draaien in
de snelle SMC-check (`crypto-market-scan-smc`, zie hierboven); een extra systemd-unit is niet nodig. Beide zijn standaard uit:

| Instelling | Standaard | Wat het doet |
|---|---|---|
| `RANGE_SWEEP_ENABLED` | `false` | Zoekt nieuwe setups. Pas aan na een geslaagde toets op stopkwaliteit (`scripts/strategy_lab.py --familie rangesweep --opslaan`); gemelde setups en open trades worden altijd afgemaakt. |
| `RANGE_WATCH_ENABLED` | `false` | Volgt ranges en meldt stil dat een range gevonden is of de koers bij een rand komt. Informatie, geen kans. |
| `RANGE_SWEEP_PUBLIC` | `false` | `false`: alleen de CEO ziet de kansen, de ranges, de kanspagina en de cijfers op Bewijs, en de signalen staan niet in de openbare `/keten`. `true`: ook leerlingen. Herstart `crypto-web` en `crypto-bot` na een wijziging. |
| `RANGE_SWEEP_MAX_PER_DAY` | `6` | Hoeveel setups per 24 uur gemeld worden; de rest blijft zichtbaar als "niet gemeld". |
| `RANGE_WATCH_MAX_PER_DAY` | `3` | Eigen budget voor stille range-meldingen per gebruiker per 24 uur, los van het kansbudget. |
| `RANGE_SWEEP_MAX_NEGATIVE` | `30` | De motor zet zichzelf uit na zoveel afgeronde proeftrades die samen negatief zijn bij de referentie-uitgang. |

Op Bewijs (tab Regels) staat de stopkwaliteit uit het lab naast dezelfde cijfers uit de live metingen, met het oordeel van het lab
(stopkwaliteit geslaagd of niet, de strenge toets op een voordeel ernaast, 30 toetsen en een register van 64). De status is "In proef" zodra de
stopkwaliteit geslaagd is; "Bewezen" vraagt ook de strenge toets en de live bewaking. De R die Bewijs telt is de R bij de referentie-uitgang
(meelopende stop van 3 ATR op 1u), niet bij jouw eigen doel; lopende en niet gevulde setups staan als aantal ernaast. De score 40/60 op een
kaart en de doelkans zijn historisch en beschrijvend, geen voorspeller.

### Marktbrein, deel A: liquidaties en kalender

```bash
sudo cp deploy/crypto-liq.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-liq.service
```

`app/liquidations.py` bewaart gedwongen sluitingen op Binance futures per coin per 5 minuten in `liquidations_5m`. De stroom
bestaat alleen live, dus laat dit proces altijd draaien. `app/market_calendar.py` levert voorspelbare momenten (funding,
opening VS-beurs, opties-expiry); CPI en FOMC zet je zelf in `data/macro_events.csv` (kolommen `at`, `label`). Toets de
momenten met `python3 scripts/calendar_scan.py`. Zie `docs/superpowers/specs/2026-10-06-marktbrein-design.md`.

### Marktbrein, deel B: markt-script, nieuws en Vandaag

```bash
sudo cp deploy/crypto-script.service deploy/crypto-script.timer deploy/crypto-news.service deploy/crypto-news.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-script.timer crypto-news.timer
sudo systemctl start crypto-news.service crypto-script.service
```

- `app/market_script.py`: elke 4 uur schrijft Claude per coin een duiding en maximaal twee scenario's met een voorwaarde. De code
  toetst elk scenario (stop minimaal `SMC_MIN_STOP_PCT`, R:R minimaal 2, niveaus dicht bij de prijs). De motor draait mee in de
  SMC-snelcyclus: een voorwaarde die klopt wordt een gewoon signaal met `trade_type = 'script'` en het label ongetest. Max
  `SCRIPT_MAX_ALERTS_PER_DAY` (6) meldingen per dag. Gaat vanzelf uit als de laatste `SCRIPT_MAX_NEGATIVE` (30) afgeronde
  scenario's samen negatief zijn. `SCRIPT_ENABLED=false` zet het uit. Model: `SCRIPT_MODEL` (standaard `claude-haiku-5-5`).
- `app/structure_live.py`: breuk van een lijn of range op 30m (detector uit `app/replay/breakretest.py`, alleen gesloten candles).
  Claude geeft een oordeel A, B of C, maar dat is alleen nog een meting: het filtert niets en staat op geen scherm. De code berekent niveau, stop
  en doelen. Elke breuk met een plan krijgt dezelfde luide melding; bij een volle dagcap gaat de kans die het dichtst bij zijn limiet ligt voor.
  Bewijs houdt de vullingen met oordeel C apart als `structuur_c`, naar buiten heten beide Structuur. Het plan staat in de melding en op de pagina Setups (`/structuur#structuur-<id>`), vóórdat de limiet vult. Raakt de koers het niveau,
  dan volgt een signaal met `trade_type = 'structuur'` (label ongetest, score op Bewijs). Max `STRUCTURE_MAX_ALERTS_PER_DAY` (30)
  per dag. Gaat vanzelf uit na `STRUCTURE_MAX_NEGATIVE` (30) afgeronde signalen die samen negatief zijn. `STRUCTURE_ENABLED=false`
  zet het uit. De mechanische versie scoorde -0,16R netto op een jaar candles (`scripts/breakretest_scan.py`): het oordeel van
  Claude moet dat verschil maken, en dat is een hypothese die Bewijs toetst. Komen er minder kansen dan je verwacht, draai dan
  `.venv/bin/python3 scripts/structuur_check.py` (alleen-lezen): per dag breuken, plannen, gemeld, gevuld, doel/stop/open en of de
  dagcap geraakt werd, de hartslag ("33 van 35 coins gecontroleerd in 41 s; mislukt: ...") en welke coins geen enkel plan kregen.
- `app/zone_radar_live.py` (rekenregels in `app/zone_radar.py`): per coin de dichtstbijzijnde actieve vraagzone onder en aanbodzone boven de koers
  op 1u en 4u (binnen 6%), als limietplan op de Radar (`/smc`): limiet op de binnenrand, stop een kwart ATR voorbij de buitenrand (minstens
  `SMC_MIN_STOP_PCT`), doel de rand van de eerstvolgende tegenovergestelde zone, minimaal 2R. Melding bij een nieuwe kaart en bij de vulling;
  gevuld wordt het een signaal met `trade_type = 'zone_radar'` (ongetest, apart op Bewijs). Max `ZONE_RADAR_MAX_PER_DAY` (20, de kaarten dichtst bij de koers gaan voor) nieuwe kaarten
  per dag, `ZONE_RADAR_ENABLED=false` zet het uit. Handmatig draaien: `python3 -m app.zone_radar_live`.
- `app/zone_sweep_live.py` (kaart in `app/zone_sweep.py`, detector `app/replay/zonesweep.py`): de koers prikt door een actieve vraagzone (long) of
  aanbodzone (short) en sluit binnen 6 candles op 1u terug. Live vóór de labrun, op verzoek van de gebruiker, altijd ongetest (zie
  `docs/onderzoek/zone-sweep/preregistratie.md`, "Aanvullende besluiten"). Varianten ZS_1H, ZS_2H en ZS_4H, limiet op de binnenrand, stop een
  kwart ATR voorbij de prik, doel de rand van de eerstvolgende tegenovergestelde zone bij minstens 2R, anders geen doel (dan telt Bewijs de R bij de
  referentie-uitgang, zoals bij de range sweep). Kaart op de Radar, melding bij een nieuwe kaart en bij de vulling, gevuld een signaal met
  `trade_type = 'zone_sweep'` buiten de `/keten`. `ZONE_SWEEP_ENABLED` (standaard `true`), `ZONE_SWEEP_PUBLIC` (standaard `true`; `false` is
  alleen de CEO), `ZONE_SWEEP_MAX_PER_DAY` (10 gemelde kaarten per 24 uur, de rest staat stil op de Radar). Draait in de snelle SMC-check, geen
  eigen unit. Handmatig: `python3 -m app.zone_sweep_live`.
- `app/calendar_alerts.py`: herinnering 30 minuten vóór de opening van de VS-beurs (stil) en vóór een macro-uitslag uit
  `data/macro_events.csv` (met geluid). De agenda toont alleen momenten die de toets als duidelijk anders mat, plus macro;
  funding-resets en opties-expiry stonden er eerst bij maar bewegen de markt niet meetbaar. De agenda is niet volledig
  automatisch: CPI en FOMC komen uit het csv-bestand dat jij vult.
- Structuur-setups sturen na de vulling een melding bij elk doel dat raakt. Bij T1 hoort de instructie: stop naar de instap.
  Een motor die zichzelf uitzet na een negatieve score meldt dat aan de beheerder (tabel `sent_alerts` voorkomt dubbele meldingen).
- `app/trend_live.py`: trend plus pullback (4u en 1u trend, impuls op 15m, zone, bevestiging op 5m), dezelfde detector als de toets
  `scripts/trendpullback_scan.py`. Gemeten op een jaar en 7 coins: bruto +0,03R, netto -0,06R. Daarom altijd ongetest, alleen stille meldingen
  (max `TREND_MAX_PER_DAY`, 6) en `trade_type = 'trend'` zodat Bewijs de score toont. Gaat uit na `TREND_MAX_NEGATIVE` (40) negatieve afgeronde signalen.
- `app/news.py`: RSS (CoinDesk, Cointelegraph, The Block) en Binance-aankondigingen, elke 10 minuten, gesorteerd door
  `ANTHROPIC_EXPLAIN_MODEL`. Een bron die niet antwoordt wordt overgeslagen.
- `/vandaag` (Markt): scripts, agenda van 24 uur, liquidaties van het laatste uur, nieuws en de score van
  de eigen voorspellingen. `/api/vandaag` ververst koersen en scenario's elke 15 seconden (`web/static/vandaag.js`).
- Bewijs en het weekrapport tonen de soort `script` apart.

### Marktcontext: funding, OI, Fear and Greed en stablecoins (alleen weergave)

Geen eigen service: `app/market_context_live.py` draait in de snelle SMC-cyclus (`crypto-market-scan-smc.timer`, elke 5 minuten),
naast de motoren en hooguit 20 seconden. Bronnen, allemaal publiek en zonder sleutel: Binance (`/fapi/v1/premiumIndex`,
`/fapi/v1/fundingInfo`, `/futures/data/openInterestHist`), Hyperliquid (`POST https://api.hyperliquid.xyz/info`, `metaAndAssetCtxs`),
Bybit (`/v5/market/tickers?category=linear`), OKX (`/api/v5/public/funding-rate`), alternative.me (`/fng/`) en DefiLlama
(`stablecoins.llama.fi/stablecoincharts/all`). Funding en OI worden elke cyclus opgehaald, Fear and Greed en stablecoins elke 6 uur;
een bron die faalt schrijft niets, de oude waarde blijft met zijn tijd staan. Metingen staan in de tabel `market_context` (30 dagen).

Wat je ziet: een blok Context op elke Radar-kaart en kanspagina (funding per 8u met wie betaalt, het grootste verschil met Binance,
OI over 24 uur, met bron en leeftijd), Marktcontext op Vandaag (tab Markt) en op Bewijs een tabel per kaartsoort: kaarten met extreme
funding bij het ontstaan (vaste grenzen +0,05% en -0,03% per 8u) naast de rest. Een zone-radar-kaart bewaart de stand bij zijn ontstaan
(`ctx_funding`, `ctx_oi_change_24h`, `ctx_spread`). Geen motor, filter of melding leest iets hiervan. `MARKET_CONTEXT_ENABLED=false` zet het uit.

Controleren op de VPS:

```bash
cd /opt/crypto-alerts && source .venv/bin/activate
python3 -m app.market_context_live                      # één ronde met logregels per bron
sqlite3 data/trading.db "SELECT name, at, detail FROM engine_heartbeat WHERE name = 'marktcontext'"
sqlite3 data/trading.db "SELECT bron, metric, COUNT(*), MAX(gemeten_op) FROM market_context GROUP BY bron, metric"
```

### Samenval en alleen-informatie per soort

Samenval (`app/samenval.py`): een SMC-signaal en een community-call (day_trading) op dezelfde coin en kant binnen
`SAMENVAL_WINDOW_HOURS` (6) geven één extra pushmelding met het label ongetest. `/bewijs` en het weekrapport tonen de
uitkomst apart. De detector gaat vanzelf uit zodra de laatste `SAMENVAL_MAX_NEGATIVE` (30) afgeronde samenvallen samen
negatief zijn in R. De check draait mee in de SMC-snelcyclus.

`SIGNAL_TYPE_INFO_ONLY` in `.env` (bijvoorbeeld `patroon,day_trading`) zet de push voor die soorten uit. Het signaal blijft
bestaan, in het journaal en op Bewijs, dus het meten gaat door. De timers en de bot lezen `.env` opnieuw bij de volgende
start; herstart `crypto-bot` na een wijziging.

### Trade Radar en Bewijs (dashboard)

`/smc` heet in de navigatie **Kansen** (zie hieronder): elke wachtende kans en elke open trade staat als kaart met grafiek in de tab van
zijn soort, met een live status die elke 15 seconden meebeweegt (`/api/radar`, `web/static/radar.js`; koersen staan 10 seconden in een cache).
De rekenlaag zit in `app/trade_plan.py` en `app/radar.py`. Zodra de koers in de zone komt stuurt de SMC-check eenmalig een
melding "koers in de zone" (`market_scanner._notify_zone_touches`, kolom `smc_setups.zone_alert_sent`), en de SMC-melding zelf
begint met de limietorder en de R:R vanaf die prijs.

`/bewijs` toont per soort melding de automatisch gemeten uitkomst in R na kosten (`app/track_record.py`, kosten uit
`TRACK_RECORD_COST_PCT`): aantal afgeronde trades, winrate, gemiddelde R met en zonder kosten, een curve per week en een status
die een vaste regel volgt (onder 30 afgeronde trades "nog te weinig data", daarboven positief of negatief na kosten, "voordeel
gemeten" pas bij 100 trades en een positief gemiddelde). Vervallen en open signalen staan er bewust bij maar tellen niet mee.

### Navigatie, Kansen en thema (ontwerp V4)

Vier tabs: **Kansen** (`/smc`), **Logboek** (`/signalen`), **Bewijs** (`/bewijs`) en **Markt** (`/vandaag`); geen url veranderde, de
oude `/structuur` stuurt door naar de tab Structuur op Kansen. Account, Meldingen, Handleiding, Zone-radar uitleg, Kwartaalcijfers,
Galerij en CEO (alleen de eigenaar) staan in het menu achter je initiaal rechtsboven. Het getal op Kansen telt de kansen die nu in de
zone staan.

Kansen (`app/kansen.py`) heeft een tab per soort: Structuur, Zone-radar en Zone-sweep (met `ENGINE_FOCUS=false` ook SMC). Boven de
tabs staat het totaal over alle tabs ("12 kansen klaar · 2 in de zone · 3 open", alleen wat er is; "Geen kansen" als er niets is), naast
elke tabnaam het aantal wachtende kansen en zolang er iets in de zone staat een accentbadge met dat aantal; elke tab herhaalt zijn eigen
regel. Wisselt een kaart van stand terwijl de pagina openstaat, dan tellen de getallen mee (`kaarten.js` na elke `/api/radar`). De tab met
de meeste kansen in de zone gaat vanzelf open. Een kaart toont coin en richting, de stand (Wacht, In zone, Open), het label ongetest of
in proef en een grafiek die per soort anders is: Structuur zijn eigen momentopname bij de breuk (`setup_chart.setup_svg`: de gebroken
lijn of range, het retest-niveau, de stop en T1 tot T3, ook voor een open Structuur-trade), Zone-radar en Zone-sweep een tekening in de
stijl van de galerij op het tijdframe van de zone (`app/card_chart.py`, lazy via `/api/kaart_svg/<sleutel>`: de zone als vlak vanaf de
ontstaanscandle met een markering, de doelzone, bij de zone-sweep ook de prik en het herstel, en limiet, stop en doel met prijs rechts;
"Groot" opent de schermvullende grafiek). Dubbele kaarten (zelfde soort, coin en richting, instap binnen 0,2%) staan één keer, de oudste;
het blad zegt "Nog 1 vergelijkbaar signaal". Dat geldt alleen voor deze weergave: Bewijs, Logboek en meldingen houden elk signaal.
In de zone staat bovenaan, daarna op gemeten afstand tot de instap; open trades staan onder Open.
Wat niet meer actief is, en onder Structuur ook wat uitviel, de trend-trades en de range sweep (proef), staat als inklapbare regel
onder de lijst. Een tik op de kop van een kaart opent het **detailblad**: de prijs als ladder (koerslabel links, lijnen in het midden,
alleen de namen Stop, Instap en Doel rechts, zodat tekst nooit botst; `app/ladder.py`, live in `web/static/ladder.js`), daaronder de
getallen één keer (houd vast om te kopiëren, de bel zet een prijsalarm), de herkomst, de gemeten context en vast onderaan
"Zet de order, stap voor stap" naar de order-checklist (`/nu/order/<sleutel>`: instrument en richting, limietprijs, stop, doel; geen
positiegrootte) of "Bekijk de trade". "Sla over voor vandaag" zet een kans een dag achteraan (cookie `hp_skip` en `plan_skips`, ook in
het Logboek).

**Verbergen.** Elke kaart op Kansen (wachtend plan of open trade, in elke tab) heeft een kruisje naast de kop en in het blad de knop
"Verberg"; onder Wachtend en onder Open staat bij twee of meer kaarten "Verberg alles". De kaart klapt meteen weg en een balk van 5 s
biedt "Ongedaan" ("HYPE short verborgen · Ongedaan"), zonder bevestigingsvraag. Verborgen kaarten staan onderaan hun tab onder
"Verborgen (N)" met "Toon weer" per rij en "Toon alles weer". Het is per gebruiker op de server bewaard (tabel `kans_hidden`, routes
`POST /api/kans/verberg` en `/api/kans/toon` met `{"keys": [...]}`, alleen voor wie ingelogd is) en alleen een weergavekeuze: een
verborgen kaart telt niet mee in het tab-getal, de badge, de totaalregel, het getal op Kansen in het dok en op het appicoon
(`radar.in_zone_count(..., hidden)`), en niet als "vergelijkbaar". Het signaal zelf, de uitkomst, Bewijs, Logboek, Replay, het journaal
en de meldingen veranderen niet: een verborgen open trade wordt gevolgd zoals altijd en een vulling of uitkomst geeft nog steeds een
melding. Een verborgen plan dat vult, komt als nieuwe open trade terug (andere kaart). Verbergen is sterker dan overslaan: overslaan
houdt de kaart een dag achteraan, verbergen haalt hem weg tot je hem terugzet.
Prijzen staan overal met een komma en zoveel decimalen als bij de prijs past (`app/price_text.py`: 80,92 voor HYPE); kopiëren geeft
hetzelfde getal met een punt. Pushteksten houden hun oude notatie (golden tests).

**Markt** (`/vandaag`) is de oude Vandaag zonder het scherm Nu: marktcontext, agenda, liquidaties, nieuws, scenario's (zolang het
markt-script aan staat) en de score; open meldingen van soorten zonder eigen tab staan er onder Verder open.

Thema: donker is de standaard. In Account kies je Systeem, Donker of Licht; de keuze staat in de cookie `hp_theme` (en in
localStorage), zodat de server de pagina meteen in het goede thema schrijft. Controleer het contrast na een kleurwijziging voor beide:
`python3 scripts/layout_check.py --base http://127.0.0.1:8000 --user <naam> --out /tmp/lc --theme dark` en daarna `--theme light`.
Letters: Geist en Geist Mono (Google Fonts); offline valt de pagina terug op de systeemletters.

### Logboek, replay, week en Beheer (ontwerp V2, fase 2)

**Logboek** (`/signalen`) is een dagtijdlijn: per dag wat de app zag (nieuwe plannen, in de zone), wat jij deed (checklist afgerond
met de gemeten duur, gevuld, genomen, overgeslagen) en de uitkomst met R. Een trade is een plan waarvan je de checklist afrondde en
dat vulde, of een melding die je in het Journaal als genomen of aangepast markeerde. R komt uit de uitkomst van het signaal (doel of
stop), zonder kosten; oefentrades tellen nooit mee. Overslaan op Kansen en de tijden van de checklist staan per gebruiker in de database
(`plan_skips`, `checklist_runs`). De oude signalenlijst staat onder de tabs Open en Alle; het Journaal (status, sluiten, terugzetten,
export) staat op Account. Bij elke afgeronde trade opent **Bekijk replay** de 5m-candles van een uur voor de vulling tot de uitkomst,
met stop, instap en doel, een schuifbalk, een knop per moment en Speel af.

**Week** is een tab op Bewijs: de R van jouw trades deze week, acht weken ernaast, gemiddelde en grootste verlies, en hoogstens één
telbare observatie over overgeslagen plannen.

**Beheer** (`/beheer`, alleen de eigenaar, via het initiaal): leerlingen met hun set, week-R en wanneer ze laatst keken; volg-sets
(een naam en coins; een set filtert alleen de pushmeldingen van die leerling); uitnodigingen per code met aantal keer en
verloopdatum. Registreren blijft open; zet `REGISTRATION_REQUIRES_INVITE=true` in `.env` om alleen met een geldige code toe te
laten. Een code kent zijn set toe. Leerlingen zien elkaar of elkaars resultaten nooit.

### Een update aankondigen (/nieuw)

`/nieuw` is openbaar en deelbaar (Discord, WhatsApp; linkvoorbeeld `web/static/og/nieuw.png`, opnieuw maken met
`python3 scripts/make_og.py`). Vóór het gekozen moment telt hij af, daarna toont hij wat er live is met een knop naar HesPulse.
Na het moment ziet elke ingelogde gebruiker één keer het verhaal "Wat is nieuw" (zes kaarten: alle kansen op één plek, zones en
Structuur, de order stap voor stap, Logboek en Replay, licht en donker, op je beginscherm; opnieuw te openen via het initiaal),
en gaat er in de snelle cyclus (`crypto-market-scan-smc.timer`) precies één pushmelding uit naar iedereen met een abonnement
(pauze telt, binnen stille uren stil). Het moment staat in de database, dus geen herstart nodig:

```bash
python3 scripts/aankondiging.py --zet 2026-11-02T18:00   # Amsterdamse tijd
python3 scripts/aankondiging.py --zet +30m               # vanaf nu, ook +2u of +1u30m: direct na een update laten afgaan
python3 scripts/aankondiging.py --toon                   # het moment en hoe lang nog
python3 scripts/aankondiging.py --test-push              # alleen naar de eigenaar
python3 scripts/aankondiging.py --wis
```

`ANNOUNCEMENT_AT` in `.env` is alleen een startwaarde. Het verhaal en de push horen bij `announce.STORY_VERSION`: een tijd verzetten
geeft niemand iets twee keer; een volgende update met nieuwe kaarten krijgt een nieuwe versie.

### App op het beginscherm (PWA)

HesPulse is te installeren als app (`web/static/manifest.json`, `service-worker.js`, `pwa.js`, `install.js`). De app start voor
iedereen op Kansen (`start_url` `/smc`, sinds ontwerp V4; een oude installatie die nog `/vandaag?bron=app` opent, wordt doorgestuurd
naar `/smc`); het manifest houdt `id` `/ceo` zodat bestaande installaties dezelfde app blijven. Een gewijzigde `start_url` neemt een
telefoon pas over als hij het manifest opnieuw ophaalt. Lang drukken op het icoon geeft snelkoppelingen naar Kansen, Markt en Bewijs.
Account toont de installatiehulp (iPhone: Delen, Zet op beginscherm, open de app; Android en Chrome: een eigen knop), Vandaag
een rustige banner die je kunt wegklikken; beide verdwijnen in de geïnstalleerde app. Offline toont de app de laatst bekende
Radar en Vandaag met de balk "Offline, laatst bijgewerkt om HH:MM": de service worker bewaart alleen die twee pagina's, per pad
en alleen met de kijker-kop `X-HP-Viewer` van een ingelogde gebruiker; een andere kijker, uitloggen of een omleiding naar
`/login` wist ze. `/api`, POST en push gaan nooit door een cache. Na een wijziging aan `service-worker.js` verhoog je
`SW_VERSION` (de test `tests/test_pwa.py` bewaakt dat); gebruikers krijgen dan "Nieuwe versie beschikbaar, tik om te laden".
De opstartbeelden voor iPhone en de snelkoppelingsiconen maak je opnieuw met `python3 scripts/make_splash.py` (Pillow, komt mee
met matplotlib); de formaten staan in `web/splash.py`. Na een deploy is alleen `crypto-web` herstarten nodig.

### Periodieke factor-drift-check

```bash
sudo cp deploy/crypto-factor-check.service /etc/systemd/system/
sudo cp deploy/crypto-factor-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-factor-check.timer
```

Draait elke zondagavond om 21:00 (`scripts/backtest_factors.py` handmatig
draaien blijft mogelijk, maar dit doet dezelfde berekening automatisch en
waarschuwt zelf). Vergelijkt per technische factor de pass-rate over de
laatste 50 signalen met zijn bredere historische gemiddelde; zakt een
factor 15 procentpunt of meer daaronder, dan komt er een admin-only rij op
`/meldingen` (zichtbaar voor `ADMIN_USERNAME`, zie "Systeemzelfcheck"
hierboven), als signaal dat de markt mogelijk veranderd is voor die factor.

Een nieuwe database-migratie in deze release (de `signals`-tabel rebuild
in `app/db.py`, nodig voor autonome signalen zonder brongbericht) draait
bij het opstarten van `crypto-bot`. Herstart daarom bij deze release
`crypto-bot` en `crypto-web` NA ELKAAR, niet gelijktijdig: `crypto-web`
mag pas herstarten nadat `crypto-bot` de migratie heeft voltooid, anders
kan het dashboard tijdens de rebuild tegen een tijdelijk inconsistente
`signals`-tabel aanlopen.

### Uitgebreide technische factoren (optioneel)

Naast de vijf basisfactoren (trend, momentum, RSI, volume, uitgerektheid)
kan het systeem
vijftien extra factoren toetsen: trendsterkte (ADX), volatiliteit (ATR t.o.v.
zijn eigen gemiddelde), volume-percentiel, BTC-trend als filter voor andere
coins, daily-RSI, bevestiging op het 1 uur tijdsbestek
(trend en RSI) naast de 4 uur, RSI/prijs-divergentie, een candlestick-
patroonherkenning, een liquiditeitsgrens (24u handelsvolume), zelf-
gedetecteerde steun/weerstand-zones uit de prijsgeschiedenis, premium/
discount-zones (ligt de entry in de goedkope of dure helft van de recente
swing-range?) en liquidity sweeps (een stop-hunt: een eerdere swing-low/
-high met de pen doorbroken en teruggesloten aan de goede kant) — de
laatste twee elk zowel op 4 uur als op de dagcandle. RSI wordt op alle
drie tijdsbestekken (4u, 1u, daily) symmetrisch getoetst: zowel overbought
als oversold telt tegen zowel een long als een short. Dagtrend (dezelfde
trendcheck als de basisfactor Trend, maar op de dagcandle) hoort hier niet
bij: die draait, sinds de kritischere signaaltoetsing, altijd als eigen
harde eis, los van of deze uitgebreide toetsing aan staat — zie de bullet
hierover bij "Praktische keuzes in deze versie" hieronder.

Van deze vijftien factoren is alleen BTC-trend (voor altcoins met een
duidelijk trending BTC) apart hard vereist, net als de basisfactor
Uitgerektheid buiten deze vijftien om — die twee moeten allebei altijd
kloppen, ongeacht de rest. De overige achttien factoren (4 basis + 3 vast +
11 uitgebreid) tellen gezamenlijk mee, en minstens 60% moet kloppen (zie
`CONFIRM_THRESHOLD` in `app/indicators.py`).

Staat standaard uit. De drempels (ADX minimaal 15, ATR mag tot 10% onder
het 20-candle-gemiddelde zakken, 2 miljoen volume) zijn leerboek-standaarden,
nog niet getoetst aan je eigen signaalgeschiedenis. Draai eerst het
backtest-script om te zien hoe streng dat in de praktijk uitpakt voor jouw
eigen signalen:

```bash
python3 scripts/backtest_factors.py --limit 50
```

Bevalt het beeld, zet dan in `.env`:

```
ENABLE_ADVANCED_FACTORS=true
```

en herstart `crypto-bot`. Terug naar de basisversie kan altijd door de
regel weer op `false` te zetten of te verwijderen.

### Meetraam (replay)

`scripts/replay_report.py` speelt de dagtrading-beslislogica af over historische
Binance-candles en toont winrate en verwachting in R (na kosten) per coin,
kwartaal en train/test. `scripts/replay_compare_live.py` controleert het raam
tegen de echte signalen uit de database (op de VPS met `DATABASE_PATH=/opt/crypto-alerts/data/trading.db /opt/crypto-alerts/.venv/bin/python3 scripts/replay_compare_live.py --since 2026-10-01 --until 2026-10-05`; `--until` is exclusief en alleen `day_trading` telt). Candles staan in `data/candles/`
(niet in git). Zie `docs/superpowers/specs/2026-10-04-signaalkwaliteit-design.md`.
Tests: `python3 -m unittest discover -s tests -t . -v`.

Het SMC-raam draai je met `scripts/replay_smc_report.py --months 12`. Het
rapport toont de trechter (waarom setups doodlopen), de uitkomst in R, de
snelheid en de break-even kosten. De eerste keer downloadt hij 1m-candles; reken
op enkele uren voor 7 coins met `--workers 2` (ongeveer 45 tot 60 minuten rekentijd per coin). Draai het op de VPS met
`nohup nice -n 10 python3 -u scripts/replay_smc_report.py --months 12 --workers 2 > /tmp/smc12.txt 2>&1 &`
(de voortgangsregels worden direct geflusht). De scanmomenten staan 3 minuten
na een vijfminutengrens (`--offset-minutes`), zodat ze nooit op een kwartiersgrens
vallen. Controle tegen de echte SMC-signalen (minstens 70% moet terugkomen; `--until` is exclusief):
`DATABASE_PATH=/opt/crypto-alerts/data/trading.db /opt/crypto-alerts/.venv/bin/python3 scripts/replay_smc_compare_live.py --since 2026-09-01 --until 2026-10-04T10:00`.
Het rapport schrijft naast de signalen-CSV ook `data/replay/smc_setups_*.csv` met alle setups. `scripts/replay_smc_analyze.py` (kosten, stopafstand, vaste take met `--grid`) werkt op de signalen. `scripts/replay_smc_setup_analysis.py` speelt elke setup na als vaste limietorder op de zonerand en toetst kenmerken (4u- en dagtrend, sweepdiepte, zonegrootte, tijdblok) op train en test.
`scripts/replay_lab.py` is een testbank voor eenvoudige instap-regels op 15m en 30m (pullback naar de EMA in de 4u-trend, uitbraak met volume, sweep en terugkeer, RSI-uitersten, sessie-opening, plus een willekeurige controle). Per regel en take toont het trades per jaar, winrate en R bruto en netto op train en test, en markeert kandidaten. Het raakt het live systeem niet aan.
Met `scripts/replay_lab.py --positioning` test je regels op positioneringsdata van Binance (open interest, top-traders, takers, funding), gratis van data.binance.vision. Dat is informatie die niet in een candle zit.
De trage equivalentietest (`tests/test_smc_equivalence.py`, enkele minuten) sla je over met `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`.

### HTTPS met Let's Encrypt

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/crypto-alerts
sudo ln -s /etc/nginx/sites-available/crypto-alerts /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d jouw-domein.nl
```

Vervang `jouw-domein.nl` in het nginx bestand door je eigen domeinnaam,
die je naar het IP adres van je VPS laat wijzen. Certbot regelt daarna
automatische vernieuwing van het certificaat.

Het dashboard beperkt zelf ook het aantal inlogpogingen: na een aantal
mislukte pogingen (instelbaar via `MAX_LOGIN_ATTEMPTS` in `.env`) wordt
inloggen tijdelijk geblokkeerd.

### Een tweede gebruiker toevoegen

Wil een vriend hetzelfde systeem gebruiken, met zijn eigen login en eigen
pushmeldingen, maar op basis van dezelfde signalen die jij al
binnenkrijgt via Discord? Hij gaat zelf naar
`https://jouw-domein.nl/registreer` en maakt daar zijn eigen account aan
met een gebruikersnaam en wachtwoord. Jij hoeft niets te doen.

Na het inloggen klikt hij zelf, via de instellingenkaart op zijn
accountpagina, op "Meldingen aanzetten" om zijn eigen pushmeldingen aan
te zetten (zijn browser vraagt eenmalig om toestemming, geen bot of chat
ID nodig). Hij ziet dezelfde signalen als jij, maar zijn eigen
statusknoppen, en zijn eigen winrate en resultaat. Wat jij invult bij een
melding (genomen, entry, exit, notitie) is niet zichtbaar voor hem, en
andersom.

Registratie is open voor iedereen die de link heeft, dat is bewust zo
gekozen (met `REGISTRATION_REQUIRES_INVITE=true` alleen met een code uit
`/beheer`). Tegen geautomatiseerde spam-registraties zit een limiet van
`MAX_REGISTRATIONS_PER_HOUR` (standaard 5) per IP-adres per uur, in te
stellen in `.env`.

Wil je zelf iemands wachtwoord herstellen, of een account beheren zonder
dat diegene toegang tot zijn eigen account heeft, gebruik dan nog steeds
`scripts/create_user.py` op de VPS, dat werkt voor elk account, ook een
dat via `/registreer` is aangemaakt.

## Dagelijkse werkwijze

Zie je een relevant bericht in de betaalde community, hou het ingedrukt op
mobiel of hover eroverheen op desktop, kies Forward, en stuur het door naar
de DM van je eigen bot. Bijgevoegde afbeeldingen gaan mee en worden
verwerkt, de daarin getekende niveaus verschijnen als stippellijn op de
grafiekpagina van die coin. Alles daarna gaat automatisch.

## Belangrijke beperking

Het systeem geeft meldingen op basis van regels. Het voorspelt niets met
zekerheid. Er is geen enkele functie die automatisch trades uitvoert. Elke
trade blijft een handmatige beslissing.

## Praktische keuzes in deze versie

- Als quote paar wordt standaard `USDT` gebruikt (instelbaar via
  `QUOTE_CURRENCY` in `.env`), omdat Binance daar de meeste liquiditeit op
  heeft. Dit is het praktische equivalent van een dollar paar.
- Stop loss staat op 1,5x ATR van de entry, take profit op 3x ATR
  (risk:reward van 1:2). Aanpasbaar in `app/risk.py`.
- Technische bevestiging kijkt naar EMA9/EMA21 trend, MACD momentum, RSI
  extremen en volume ten opzichte van het gemiddelde. Aanpasbaar in
  `app/indicators.py`.
- Daarnaast gelden drie harde eisen die, elk los van de rest, een signaal
  naar laag vertrouwen kunnen sturen: de eigen dagtrend van de coin
  (Dagtrend, altijd actief, ook zonder `ENABLE_ADVANCED_FACTORS`), een
  minimale risico/rendement-verhouding van 1.5 tegen 1 (Risico/rendement),
  en geen recent gefaalde steun/weerstand-zone binnen bereik
  (Zone-cooldown: een zone die de laatste 3 dagen al een stop loss
  veroorzaakte, blokkeert een nieuw signaal daar). Zichtbaar als losse
  ✗-regel op de signaalkaart zodra een van de drie een melding blokkeert.
- Een melding kan naast de entry op de live prijs ook "Mogelijk betere
  entry" tonen: een steun/weerstand-zone tussen de live prijs en de stop
  loss. Puur informatief, telt nergens mee in de toetsing of het
  trackrecord.
- Mislukt de Anthropic interpretatie door een tijdelijke fout (timeout,
  overbelasting), dan probeert het systeem het tot drie keer, met een
  oplopende pauze ertussen. Lukt het dan nog niet, dan wordt het bericht
  gelogd als onduidelijk met de foutmelding erbij, in plaats van stil
  onverwerkt te blijven. Zie dit terug op `/berichten` in het dashboard.
- Het dashboard toont overal een vaste toelichting: geen advies, regels,
  geen garantie, jij beslist zelf.
- Lange termijn berichten (categorie `lange_termijn`) worden niet getoond
  in een aparte pagina, ze blijven op de achtergrond in de database staan.
  Komt er daarna een nieuw day trading signaal voor dezelfde coin, dan
  wordt dat afgezet tegen de meest recente lange termijn richting: sluit
  het aan, dan staat dat in de melding, wijkt het af, dan ook. Het
  hoog/laag vertrouwen label zelf verandert hier niet door, dat blijft
  puur op de vier technische factoren gebaseerd. Zie `app/signal_processor.py`
  (`_build_context_note`).
- Stuur je hetzelfde bericht binnen 24 uur nogmaals door (bijvoorbeeld per
  ongeluk twee keer geforward), dan herkent het systeem dat aan de exacte
  tekst en verwerkt het niet opnieuw: geen tweede Anthropic aanroep, geen
  tweede signaal, geen dubbele pushmelding. Het tweede bericht wordt
  wel gelogd, met een verwijzing naar het eerste.
- Winrate alleen zegt weinig over hoe goed het systeem werkt, een hoge
  winrate met kleine winsten en een paar grote verliezen kan alsnog
  verlieslatend zijn. Het dashboard toont daarom ook het gemiddelde
  resultaat in procenten per vertrouwen-niveau, en een trackrecord per
  coin, zodat je kan zien welke coin het goed doet met dit systeem en
  welke niet.

## Later uitbreidingen (bewust niet in deze versie)

- Patroonherkenning die zelf patronen probeert te ontdekken in ruwe
  koersdata.
- BTC paren naast USD paren per coin.
- Aparte trackrecord per bron.
