# Crypto day trading alertsysteem

Combineert Discord DM berichten en live technische data, en stuurt meldingen
via Telegram. Het systeem voert geen trades uit. Jij beslist zelf.

## Hoe het werkt

Jij stuurt zelf relevante berichten uit een betaalde Discord community door,
via Forward, naar de DM van je eigen bot account. Het systeem leest die DM,
interpreteert de tekst via de Anthropic API, toetst dat tegen live koersdata
op Binance, en stuurt een Telegram melding. Alles wordt gelogd in een sqlite
database en is terug te zien in het webdashboard.

## Onderdelen

- `app/discord_bot.py` — leest DM's, alleen leesrechten
- `app/anthropic_interpret.py` — interpretatie van tekst en afbeeldingen
- `app/coinlist.py` — dynamische coinlijst
- `app/exchange.py`, `app/indicators.py` — live koersdata en indicatoren (4h)
- `app/risk.py` — stop loss, take profit, risicobedrag op basis van ATR
- `app/signal_processor.py` — verbindt alle stappen
- `app/telegram_notify.py` — Telegram meldingen
- `app/repo.py`, `app/db.py`, `app/schema.sql` — sqlite logging
- `app/backup.py` — dagelijkse back-up
- `web/` — FastAPI dashboard met login

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

1. Zoek in Telegram naar BotFather, stuur `/newbot`, bewaar de token.
2. Stuur zelf een bericht naar je nieuwe bot.
3. Haal je chat ID op, bijvoorbeeld via `@userinfobot`.
4. Zet token en chat ID in `.env` als `TELEGRAM_BOT_TOKEN` en
   `TELEGRAM_CHAT_ID`.

### 3. Anthropic API sleutel

Zet je Anthropic API sleutel in `.env` als `ANTHROPIC_API_KEY`.

### 4. Lokale installatie en dashboard wachtwoord

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# vul .env verder aan met je tokens

python3 scripts/create_user.py
# zet de output als DASHBOARD_PASSWORD_HASH in .env, en kies een lange
# willekeurige JWT_SECRET

python3 -m app.db
# maakt de sqlite database en tabellen aan
```

### 5. Testen, per bouwstap

```bash
# Stap 1: technische data en indicatoren voor bitcoin, los van Discord
python3 scripts/test_step1_bitcoin.py

# Stap 2 t/m 5: bot starten, DM's worden gelezen, geïnterpreteerd, getoetst
# en gemeld via Telegram
python3 main.py

# Stap 6 t/m 8: dashboard starten
uvicorn web.main:app --reload
# open http://127.0.0.1:8000 en log in met je dashboard wachtwoord
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
sudo -u crypto .venv/bin/python3 -m app.db
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
en bewaart de laatste 30 back-ups. Kopieer die map ook periodiek naar een
andere locatie (bijvoorbeeld met `rsync` naar je eigen computer of een
andere server), zodat je niet afhankelijk bent van alleen deze ene VPS.

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

## Later uitbreidingen (bewust niet in deze versie)

- Patroonherkenning die zelf patronen probeert te ontdekken in ruwe
  koersdata.
- BTC paren naast USD paren per coin.
- Aparte trackrecord per bron.
