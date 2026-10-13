# Herkomst van de coinlogo's

Alle bestanden zijn ongewijzigde logo's; alleen XML-kop, commentaar, metadata en witruimte tussen tags zijn weggehaald.
Een coin zonder bestand hier krijgt in de app zijn letters (`coin_avatar` in `web/templates/_macros.html`).

| Bron | Licentie | Bestanden |
|---|---|---|
| [spothq/cryptocurrency-icons](https://github.com/spothq/cryptocurrency-icons), `svg/color/<sym>.svg` (branch master) | CC0 1.0 Universal | aave, ada, atom, avax, bch, bnb, btc, doge, dot, etc, eth, fil, link, ltc, matic, sol, trx, uni, xlm, xrp |
| npm-pakket [@bitgo-forks/cryptocurrency-icons](https://www.npmjs.com/package/@bitgo-forks/cryptocurrency-icons) 0.158.0, een fork van het pakket hierboven, `svg/color/<sym>.svg` | CC0 1.0 Universal (LICENSE.md in het pakket) | apt, arb, hbar, inj, near, ondo, op, pepe, pol, sei, shib, sui, tao, tia, ton, wld |

De fork is alleen gebruikt voor coins die spothq niet heeft. tao.svg en pol.svg bevatten in de bron een ingebed bitmapbeeld en zijn
daardoor groter (72 en 31 kB); ze laden alleen als die coin op het scherm staat (`loading="lazy"`).

Logo's waarvan meer dan 40% te donker is tegen de achtergrond #0a0e0f (gemeten op een contactblad) staan op een licht rond plaatje:
ada, apt, atom, hbar, wld, xlm, xrp (`DARK_COIN_LOGOS` in `web/main.py`).

Merknamen en logo's blijven van hun eigenaars; de CC0-licentie dekt de tekening, niet het merk.
