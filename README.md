# HesPulse

Crypto day trading alertsysteem. Combineert Discord DM berichten en live
technische data, en stuurt meldingen via Telegram. Het systeem voert geen
trades uit. Jij beslist zelf.

## Hoe het werkt

Jij stuurt zelf relevante berichten uit een betaalde Discord community door,
via Forward, naar de DM van je eigen bot account. Het systeem leest die DM,
interpreteert de tekst via de Anthropic API, toetst dat tegen live koersdata
op Binance, en stuurt een Telegram melding. Alles wordt gelogd in een sqlite
database en is terug te zien in het webdashboard.

Meerdere mensen kunnen hetzelfde systeem gebruiken. Iedereen ziet dezelfde
signalen (dezelfde Discord berichten, dezelfde technische toetsing), maar
elke gebruiker heeft zijn eigen login, eigen portfolio, eigen risico
instelling, eigen Telegram meldingen met zijn eigen risicobedrag, en zijn
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
- `app/telegram_notify.py` — Telegram meldingen, inclusief positiegrootte
  en een vaste disclaimer
- `app/repo.py`, `app/db.py`, `app/schema.sql` — sqlite logging
- `app/backup.py` — dagelijkse back-up, optioneel ook naar een externe locatie
- `app/heartbeat.py` — dagelijks levensteken via Telegram
- `app/level_check.py` — periodieke check: heeft een open trade zijn stop
  loss of take profit al geraakt, en is de prijs weer terug bij het niveau
  van een nog niet genomen signaal (proactief, niet alleen bij een nieuw
  Discord bericht)
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

### 2. Telegram bot aanmaken

1. Zoek in Telegram naar BotFather, stuur `/newbot`, bewaar de token. Dit is
   één bot voor iedereen, elke gebruiker krijgt straks zijn eigen chat ID.
2. Zet de token in `.env` als `TELEGRAM_BOT_TOKEN`.
3. Voor elke gebruiker apart: stuur zelf een bericht naar de nieuwe bot
   vanaf je eigen Telegram account, en haal je chat ID op, bijvoorbeeld via
   `@userinfobot`. Dit chat ID vul je zo in bij het aanmaken van het account
   (stap 4), niet in `.env`.

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
# met gebruikersnaam, wachtwoord, portfolio, risicopercentage en Telegram
# chat ID.
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
# en gemeld via Telegram
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

Stuurt elke ochtend om 09:00 een kort Telegram bericht naar elke gebruiker
met een ingevuld chat ID: "Goedemorgen trader. Nieuwe dag, nieuwe kansen.
HesPulse draait, laatste controle: ..." Zonder dit merk je een
crash pas op als er een tijd lang geen meldingen meer binnenkomen.

### Systeemzelfcheck

```bash
sudo cp deploy/crypto-health-check.service /etc/systemd/system/
sudo cp deploy/crypto-health-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-health-check.timer
```

Checkt elk uur of alle vijf systeemonderdelen (bot, dashboard, back-up,
levensteken, niveau-check) echt actief én enabled zijn, en stuurt een
Telegram bericht naar `ADMIN_TELEGRAM_CHAT_ID` (in `.env`, jouw eigen chat
ID) zodra er iets ontbreekt. Zonder `ADMIN_TELEGRAM_CHAT_ID` blijft dit
alleen in de serverlog staan. Dit is ontstaan doordat de back-up- en
levensteken-timer op deze VPS ooit nooit geïnstalleerd bleken te zijn,
zonder dat iemand dat opmerkte, zie ook `app/health_check.py`.

### Wekelijkse en maandelijkse samenvatting

```bash
sudo cp deploy/crypto-weekly-summary.service /etc/systemd/system/
sudo cp deploy/crypto-weekly-summary.timer /etc/systemd/system/
sudo cp deploy/crypto-monthly-summary.service /etc/systemd/system/
sudo cp deploy/crypto-monthly-summary.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-weekly-summary.timer crypto-monthly-summary.timer
```

Stuurt elke gebruiker met een gekoppelde Telegram chat een korte
samenvatting: aantal signalen, winrate, resultaat, beste en zwakste
trade. Wekelijks op zondagavond 20:00, maandelijks op de 1e van de maand
om 09:00. Geen bericht als er in die periode niks gebeurd is, dat
voorkomt een lege samenvatting.

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
Zo ja, dan krijg je daar één keer een Telegram bericht over, met het
verzoek om de trade zelf te sluiten in het dashboard. Er wordt niets
automatisch gesloten, en je krijgt niet elke 15 minuten opnieuw hetzelfde
seintje.

### Uitgebreide technische factoren (optioneel)

Naast de vier basisfactoren (trend, momentum, RSI, volume) kan het systeem
zes extra factoren toetsen: trendsterkte (ADX), volatiliteit (ATR t.o.v.
zijn eigen gemiddelde), BTC-trend als filter voor andere coins, bevestiging
op het 1 uur tijdsbestek naast de 4 uur, RSI/prijs-divergentie, en een
liquiditeitsgrens (24u handelsvolume). Trend, Momentum, 1u bevestiging en
BTC-trend meten in de kern allemaal "is er een trend" en tellen daarom als
groep: 3 van de 4 moet kloppen. De rest blijft allemaal apart hard vereist.

Staat standaard uit. De drempels (ADX 20, ATR moet stijgen, 2 miljoen
volume) zijn leerboek-standaarden, nog niet getoetst aan je eigen
signaalgeschiedenis. Draai eerst het backtest-script om te zien hoe streng
dat in de praktijk uitpakt voor jouw eigen signalen:

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
portfolio en eigen Telegram meldingen, maar op basis van dezelfde
signalen die jij al binnenkrijgt via Discord? Hij gaat zelf naar
`https://jouw-domein.nl/registreer` en maakt daar zijn eigen account aan
met een gebruikersnaam en wachtwoord. Jij hoeft niets te doen.

Na het inloggen zet hij zelf, via de portfolio kaart op zijn dashboard,
zijn eigen portfolio in euro's, risicopercentage en Telegram chat ID
(die hij zelf ophaalt via `@userinfobot` nadat hij een bericht naar
jullie gedeelde Telegram bot heeft gestuurd). Hij ziet dezelfde signalen
als jij, maar zijn eigen risicobedrag, zijn eigen statusknoppen, en zijn
eigen winrate en resultaat. Wat jij invult bij een melding (genomen,
entry, exit, notitie) is niet zichtbaar voor hem, en andersom.

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
- Elk Telegram bericht toont ook een voorgestelde positiegrootte in coin
  eenheden: risicobedrag gedeeld door de afstand tussen entry en stop loss.
  Dat is de hoeveelheid die bij dat risicobedrag hoort, niet alleen het
  bedrag zelf.
- Mislukt de Anthropic interpretatie door een tijdelijke fout (timeout,
  overbelasting), dan probeert het systeem het tot drie keer, met een
  oplopende pauze ertussen. Lukt het dan nog niet, dan wordt het bericht
  gelogd als onduidelijk met de foutmelding erbij, in plaats van stil
  onverwerkt te blijven. Zie dit terug op `/berichten` in het dashboard.
- Elk Telegram bericht en het dashboard tonen een vaste toelichting: geen
  advies, regels, geen garantie, jij beslist zelf.
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
  tweede signaal, geen dubbele Telegram melding. Het tweede bericht wordt
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
