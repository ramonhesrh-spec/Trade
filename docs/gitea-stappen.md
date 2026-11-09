# Gitea op de VPS: stappen (voorstel, nog niet uitgevoerd)

Doel (blueprint onderdeel 7): code en data in eigen beheer, privérepo, een tag per release. Het kiezen van de plek en wie toegang heeft is een besluit
van Ramon. Dit bestand beschrijft de stappen; Claude voert ze niet uit. Plak elk blok apart en meld de uitvoer.

Waarschuwing vooraf: staan code én Gitea op dezelfde VPS, dan gaat bij een kapotte server alles weg. Houd een tweede kopie buiten de VPS (de bestaande
back-up of GitHub als spiegel). Beslis dat vóór je GitHub loslaat.

## 1. Gitea installeren (binair, systemd)
```
sudo adduser --system --shell /bin/bash --group --disabled-password --home /home/git git
sudo mkdir -p /var/lib/gitea/{custom,data,log} /etc/gitea
sudo chown -R git:git /var/lib/gitea && sudo chown root:git /etc/gitea && sudo chmod 770 /etc/gitea
# Zoek de laatste versie op https://dl.gitea.com/gitea/ en vul die hieronder in:
V=<versie>
sudo wget -O /usr/local/bin/gitea https://dl.gitea.com/gitea/$V/gitea-$V-linux-amd64
sudo chmod +x /usr/local/bin/gitea
```
Maak `/etc/systemd/system/gitea.service` volgens de officiële voorbeeldunit (docs.gitea.com, "Install from binary"), daarna:
```
sudo systemctl daemon-reload && sudo systemctl enable --now gitea
```

## 2. Bereikbaar en afgeschermd
- Poort 3000 alleen op localhost; HTTPS via dezelfde proxy als het dashboard (README, "HTTPS"), bijvoorbeeld `git.<jouw-domein>`.
- Open de installatiepagina één keer, kies SQLite, zet registratie uit (`DISABLE_REGISTRATION = true` in `/etc/gitea/app.ini`) en maak één beheerder.

## 3. Privérepo en eerste push (vanaf de VPS of je laptop)
```
# Maak in Gitea de lege privérepo "hespulse". Dan:
git remote add gitea https://git.<jouw-domein>/<gebruiker>/hespulse.git
git push gitea --all
git push gitea --tags
```
Gebruik een toegangstoken van Gitea (Instellingen, Toepassingen) in plaats van je wachtwoord. Zet het token nergens in git.

## 4. Stand van zaken (2026-11-09): Gitea is een spiegel, geen vervanging
Uitgevoerd door Ramon op de VPS: Gitea 28.3.0 op `https://git.hespulse.duckdns.org` (nginx en certbot, registratie uit, aanmelden verplicht), gebruiker `doalhof`,
privérepo `hespulse` met alle branches (`claude/crypto-day-trading-alerts-5p8w6v`, `claude/crypto-day-trading-alerts-geb2v7`, `hespulse-data`). Er zijn geen tags.
- GitHub blijft `origin`. Claude-sessies hebben alleen toegang tot GitHub en lezen de nachtexport van de tak `hespulse-data` daar. Verplaats de nachtexport en de VPS-updates dus niet,
  anders ziet Claude de export niet meer en loopt de controle van 2026-11-24 stuk.
- De kopie in Gitea loopt achter tot hij wordt bijgewerkt. Werk hem bij vanaf de VPS: `cd /tmp/trade-mirror && git fetch --prune origin && git push https://git.hespulse.duckdns.org/doalhof/hespulse.git --all`
  (of stel in Gitea een pull-spiegel van GitHub in).
- Het token `vps-push` staat alleen in de wachtwoordmanager van Ramon. Draai het rond als het ooit in een chat of bestand belandt.

## 5. Releases
Een tag per release: `git tag -a v2026.11.1 -m "wat en waarom" && git push gitea --tags`. Schrijf de tag in `docs/register/leveringen.md`.

## 6. Terugdraaien
Zet `origin` terug naar GitHub (`git remote set-url origin <GitHub-url>`). Er is niets verwijderd.

## Open keuzes voor Ramon
- GitHub houden als spiegel of stoppen?
- Domein of subdomein voor Gitea?
- Wie krijgt toegang (alleen jij, of ook een tweede beheerder)?
