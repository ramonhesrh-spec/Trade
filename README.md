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
publieke landingspagina, met een korte uitleg, een over ons sectie, en geen
open registratie. Na inloggen kom je op `/dashboard`, het besloten
logboek.

## Onderdelen

- `app/discord_bot.py` — leest DM's, alleen leesrechten
- `app/anthropic_interpret.py` — interpretatie van tekst en afbeeldingen
- `app/coinlist.py` — dynamische coinlijst
- `app/exchange.py`, `app/indicators.py` — live koersdata en indicatoren (4h)
- `app/risk.py` — stop loss, take profit, risicobedrag op basis van ATR
- `app/signal_processor.py` — verbindt alle stappen, met een paar
  herhaalpogingen bij een tijdelijke Anthropic storing
- `app/telegram_notify.py` — Telegram meldingen, inclusief positiegrootte
  en een vaste disclaimer
- `app/repo.py`, `app/db.py`, `app/schema.sql` — sqlite logging
- `app/backup.py` — dagelijkse back-up, optioneel ook naar een externe locatie
- `app/heartbeat.py` — dagelijks levensteken via Telegram
- `web/` — FastAPI dashboard met login, inclusief een berichtenoverzicht op
  `/berichten` van alles wat wel en niet tot een melding leidde

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
# maakt de database aan (als die nog niet bestaat) en vraagt om
# gebruikersnaam, wachtwoord, portfolio, risicopercentage en Telegram
# chat ID. Draai dit script nogmaals voor elke extra gebruiker, bijvoorbeeld
# een vriend die hetzelfde systeem gebruikt met zijn eigen logboek.
```

Geen open registratie: alleen accounts die jij zelf op de server aanmaakt
via dit script kunnen inloggen.

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
signalen die jij al binnenkrijgt via Discord? Draai op de VPS:

```bash
cd /opt/crypto-alerts
sudo -u crypto .venv/bin/python3 scripts/create_user.py
```

Vul zijn gebruikersnaam, wachtwoord, portfolio in euro's, risicopercentage
en Telegram chat ID in (die hij zelf ophaalt via `@userinfobot` nadat hij
een bericht naar jullie gedeelde Telegram bot heeft gestuurd). Hij logt
daarna in op dezelfde dashboard URL, met zijn eigen wachtwoord. Hij ziet
dezelfde meldingen als jij, maar zijn eigen risicobedrag, zijn eigen
statusknoppen, en zijn eigen winrate en resultaat. Wat jij invult bij een
melding (genomen, entry, exit, notitie) is niet zichtbaar voor hem, en
andersom.

Hij hoeft zelf niets te installeren of te forwarden, alleen jij stuurt
berichten door naar de bot.

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

## Later uitbreidingen (bewust niet in deze versie)

- Patroonherkenning die zelf patronen probeert te ontdekken in ruwe
  koersdata.
- BTC paren naast USD paren per coin.
- Aparte trackrecord per bron.
