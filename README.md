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
elke gebruiker heeft zijn eigen login, eigen portfolio, eigen risico
instelling, eigen pushmeldingen met zijn eigen risicobedrag, en zijn
eigen logboek: status, entry, exit en notities. De ene gebruiker kan het
logboek van de andere niet zien of wijzigen.

De website heeft een openbaar deel en een besloten deel. Op `/` staat een
publieke landingspagina, met een korte uitleg en een over ons sectie.
Iedereen die de site bezoekt kan via `/registreer` zelf een account
aanmaken, dat is een bewuste keuze, geen invite-only systeem. Na
registreren of inloggen kom je op `/dashboard`, het besloten logboek, dat
blijft voor elke gebruiker apart.

## Onderdelen

- `app/discord_bot.py` — leest DM's, alleen leesrechten
- `app/anthropic_interpret.py` — interpretatie van tekst en afbeeldingen
- `app/coinlist.py` — dynamische coinlijst
- `app/exchange.py`, `app/indicators.py` — live koersdata en indicatoren (4h)
- `app/risk.py` — stop loss, take profit, risicobedrag op basis van ATR
- `app/signal_processor.py` — verbindt alle stappen, met een paar
  herhaalpogingen bij een tijdelijke Anthropic storing, herkent dubbele
  berichten, en zet een nieuw signaal af tegen recente lange termijn context
- `app/push_notify.py` — Web Push meldingen (eigen VAPID-sleutelpaar, geen
  externe pushdienst), inclusief positiegrootte
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
loss, take profit, positiegrootte, pushmelding per gebruiker) is
exact dezelfde `process_day_trading_signal`-logica als een normaal, door
een gebruiker doorgestuurd signaal.

Een systeembrede noodrem staat op het dashboard (Instellingen): staat die
uit, doet de scan niets die cyclus. Er is geen noodrem per gebruiker, dit
is een systeembrede instelling.

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

Wil een vriend hetzelfde systeem gebruiken, met zijn eigen login, eigen
portfolio en eigen pushmeldingen, maar op basis van dezelfde
signalen die jij al binnenkrijgt via Discord? Hij gaat zelf naar
`https://jouw-domein.nl/registreer` en maakt daar zijn eigen account aan
met een gebruikersnaam en wachtwoord. Jij hoeft niets te doen.

Na het inloggen zet hij zelf, via de portfolio kaart op zijn dashboard,
zijn eigen portfolio in euro's en risicopercentage in, en klikt op
"Meldingen aanzetten" om zijn eigen pushmeldingen aan te zetten (zijn
browser vraagt eenmalig om toestemming, geen bot of chat ID nodig). Hij
ziet dezelfde signalen als jij, maar zijn eigen risicobedrag, zijn eigen
statusknoppen, en zijn eigen winrate en resultaat. Wat jij invult bij een
melding (genomen, entry, exit, notitie) is niet zichtbaar voor hem, en
andersom.

Registratie is open voor iedereen die de link heeft, dat is bewust zo
gekozen. Tegen geautomatiseerde spam-registraties zit een limiet van
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
  loss. Puur informatief, telt nergens mee in de toetsing, positiegrootte
  of trackrecord.
- Elke melding rekent ook een voorgestelde positiegrootte in coin eenheden
  uit: risicobedrag gedeeld door de afstand tussen entry en stop loss. Dat
  is de hoeveelheid die bij dat risicobedrag hoort, niet alleen het bedrag
  zelf. Te zien op het dashboard, de pushmelding zelf blijft kort (coin,
  richting, prijs, stop loss, take profit).
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
  resultaat in euro's en procenten per vertrouwen-niveau, en een
  trackrecord per coin, zodat je kan zien welke coin het goed doet met dit
  systeem en welke niet.

## Later uitbreidingen (bewust niet in deze versie)

- Patroonherkenning die zelf patronen probeert te ontdekken in ruwe
  koersdata.
- BTC paren naast USD paren per coin.
- Aparte trackrecord per bron.
