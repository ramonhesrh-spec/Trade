# Evaluatie: stop loss inperken voor een klein evaluatiesaldo

## Aanleiding

De vorige deelproject (evaluatie-volledige-regels) maakte het risicobedrag
per trade evaluatie-bewust: de POSITIEGROOTTE past zich al aan aan een
klein evaluatiesaldo. Maar de STOP LOSS zelf (marktstructuur: swing low/
high + ATR-buffer, of bron-niveaus) doet dat niet. Bij een kleine evaluatie
kan een marktstructuur-stop relatief ver van de entry liggen; ook al is het
eurobedrag per trade begrensd, een reeks van dat soort trades kost meer
"trefkans-ruimte" op een klein saldo dan op een groot saldo, en verhoogt zo
de kans dat het dagbudget of de drawdown-ruimte sneller opraakt dan de
gebruiker wil. De gebruiker wil dat de stop loss zelf krapper wordt
naarmate de evaluatie kleiner is, specifiek om evaluaties zo veilig
mogelijk te kunnen voltooien.

## Niet-doelen

- Geen wijziging aan de marktstructuur-berekening zelf
  (`compute_stop_take`/`compute_stop_take_from_levels`): die logica blijft
  precies zoals hij is. Dit deelproject VOEGT een bovengrens toe die er ná
  die berekening overheen gelegd wordt, het herschrijft de berekening niet.
- Geen wijziging aan het GEDEELDE signaal (`signals`-tabel): iedereen blijft
  hetzelfde signaal met dezelfde stop loss/take profit zien op het
  dashboard en in de brontekst van het bericht. CLAUDE.md: "signalen zijn
  global, voor iedereen hetzelfde" — dat blijft zo.
- Geen wijziging voor een gebruiker zonder actieve, niet-geblokkeerde
  evaluatie: exact het bestaande gedrag.
- Geen wijziging aan de sizing-formule uit het vorige deelproject
  (`compute_eval_risk_eur`, dagbudget/drawdown-aandelen, hefboomcap): die
  blijft ongewijzigd, alleen de STOP LOSS waarmee die formule rekent kan nu
  al vooraf ingeperkt zijn.

## Sectie 1: de inperkingsformule

Nieuwe pure functie in `app/risk.py`:

```python
# Bij dit evaluatiesaldo (of hoger) wordt de stop loss niet meer ingeperkt:
# het maximum groeit dan naar STOP_CAP_MAX_PCT, wat in de praktijk geen
# enkele normale marktstructuur-stop meer raakt (die liggen vrijwel altijd
# onder de 5%).
STOP_CAP_REFERENCE_TIER = 10_000.0
# Bij een evaluatiesaldo van (bijna) nul mag de stop nog maar dit percentage
# van de entry-prijs zijn.
STOP_CAP_MIN_PCT = 0.01
# Vanaf STOP_CAP_REFERENCE_TIER: dit percentage, functioneel "geen grens".
STOP_CAP_MAX_PCT = 0.10


def eval_max_stop_pct(tier_amount: float) -> float:
    """Maximale stop-afstand als fractie van de entry-prijs, lineair
    oplopend van STOP_CAP_MIN_PCT (bij tier_amount 0) tot STOP_CAP_MAX_PCT
    (bij STOP_CAP_REFERENCE_TIER en hoger). Geen harde knip: een evaluatie
    net onder de referentie-tier krijgt bijna dezelfde ruimte als er net
    boven, in plaats van een plotselinge sprong."""
    fraction = min(max(tier_amount, 0.0) / STOP_CAP_REFERENCE_TIER, 1.0)
    return STOP_CAP_MIN_PCT + (STOP_CAP_MAX_PCT - STOP_CAP_MIN_PCT) * fraction
```

## Sectie 2: de stop/target inperken zonder de berekening te herhalen

Nieuwe pure functie in `app/risk.py`, werkt op een AL BEREKENDE `StopTake`
(swing-, ATR- of niveau-gebaseerd, maakt niet uit welke) in plaats van de
onderliggende logica te herhalen:

```python
def apply_eval_stop_cap(
    direction: str, entry_price: float, stop_loss: float, take_profit: float, max_stop_pct: float,
) -> StopTake:
    """Trekt een te brede stop loss in tot max_stop_pct van de entry-prijs.
    Take profit schaalt evenredig mee, zodat de risk:reward-verhouding van
    de oorspronkelijke berekening exact behouden blijft (in plaats van een
    aparte doelberekening te herhalen, die bij een niveau-gebaseerd target
    andere aannames zou maken dan de oorspronkelijke keuze). Geen wijziging
    als de bestaande stop al binnen de grens valt — dit is een bovengrens,
    geen streefwaarde."""
    direction = direction.lower()
    max_distance = entry_price * max_stop_pct
    if direction == "long":
        current_distance = entry_price - stop_loss
        if current_distance <= max_distance or current_distance <= 0:
            return StopTake(stop_loss=stop_loss, take_profit=take_profit)
        scale = max_distance / current_distance
        reward_distance = take_profit - entry_price
        return StopTake(
            stop_loss=entry_price - max_distance,
            take_profit=entry_price + reward_distance * scale,
        )
    elif direction == "short":
        current_distance = stop_loss - entry_price
        if current_distance <= max_distance or current_distance <= 0:
            return StopTake(stop_loss=stop_loss, take_profit=take_profit)
        scale = max_distance / current_distance
        reward_distance = entry_price - take_profit
        return StopTake(
            stop_loss=entry_price + max_distance,
            take_profit=entry_price - reward_distance * scale,
        )
    else:
        raise ValueError(f"onbekende richting: {direction}")
```

## Sectie 3: waar dit wordt toegepast — per gebruiker, via de bestaande override-kolommen

`journal_entries` heeft al `stop_loss_override`/`take_profit_override`
(bestaande kolommen, gebruikt voor "dit is mijn eigen versie, afwijkend
van het gedeelde signaal") en `repo.update_journal_levels(entry_id,
user_id, stop_loss, take_profit, position_size)` (bestaande functie) om ze
te zetten. `_JOURNAL_SELECT` leest ze al met `COALESCE(je.stop_loss_override,
s.stop_loss)` — elke bestaande consument (dashboard, coin-pagina,
`close_journal_trade`'s `risk_per_unit`-berekening, de risicogauge) ziet de
override al automatisch, zonder dat er iets anders hoeft te veranderen.

`_resolve_signal_risk` in `app/signal_processor.py` (bestaande functie uit
het vorige deelproject) wordt uitgebreid om, wanneer een evaluatie actief
en niet geblokkeerd is, ook de ingeperkte stop/target te berekenen en terug
te geven — dezelfde ene plek die al weet "is er een bruikbare evaluatie",
in plaats van die check te dupliceren:

```python
def _resolve_signal_risk(
    user: dict, direction: str, entry_price: float, stop_loss: float, take_profit: float,
) -> tuple[float, Optional[int], float, float, float]:
    """Risicobedrag, evaluation_id (of None), cost_rate, en de effectieve
    (mogelijk ingeperkte) stop_loss/take_profit voor één signaal aan één
    gebruiker. Bij een actieve, niet-geblokkeerde evaluatie wordt de stop
    ingeperkt op basis van het evaluatiesaldo (Sectie 1+2); zonder actieve
    evaluatie blijven stop_loss/take_profit exact de meegegeven, gedeelde
    signaalwaarden — geen enkele wijziging voor deze gebruiker."""
    active_eval = repo.get_active_evaluation(user["id"])
    if active_eval:
        open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
        if not risk.eval_sizing_blocked(active_eval, open_risk_eur):
            max_pct = risk.eval_max_stop_pct(active_eval["tier_amount"])
            capped = risk.apply_eval_stop_cap(direction, entry_price, stop_loss, take_profit, max_pct)
            risk_eur = risk.compute_eval_risk_eur(
                active_eval, user["risk_percent"], open_risk_eur, entry_price, capped.stop_loss,
            )
            cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
            return risk_eur, active_eval["id"], cost_rate, capped.stop_loss, capped.take_profit
    return risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"]), None, 0.0, stop_loss, take_profit
```

Beide fanout-loops (dagtrading en swing) in `app/signal_processor.py` en
beide oefentrade-routes in `web/main.py` roepen deze functie aan met hun
eigen `direction`/`entry_price` en de al berekende globale
`stop_take.stop_loss`/`stop_take.take_profit`, gebruiken de teruggegeven
`effective_stop_loss` voor `compute_position_size` en `create_journal_entry`,
en zetten — alleen als de waarde daadwerkelijk afwijkt van het gedeelde
signaal — de override via `repo.update_journal_levels`.

## Sectie 4: zichtbaarheid in het Telegram-bericht

Als de stop voor deze specifieke gebruiker is ingeperkt, moet zijn/haar
Telegram-bericht de EIGEN (ingeperkte) stop_loss/take_profit tonen, niet de
gedeelde signaalwaarden — anders wijkt het bericht af van wat er
daadwerkelijk in het logboek staat. De `signal_data`-dict die aan
`telegram_notify.send_signal` wordt doorgegeven, gebruikt per gebruiker
`effective_stop_loss`/`effective_take_profit` in plaats van de gedeelde
`stop_take.stop_loss`/`stop_take.take_profit` op de plekken `"stop_loss"`
en `"take_profit"` in die dict. Bij een daadwerkelijke inperking krijgt het
bericht een extra regel, naar het patroon van de bestaande
`_eval_budget_line`: `"📏 Stop verkrapt naar {pct:.1f}% vanwege de grootte
van je evaluatie."` alleen getoond als de stop voor deze gebruiker
daadwerkelijk is aangepast.

## Sectie 5: oefentrades

`web/main.py`'s `_fetch_practice_trade_calc` blijft ongewijzigd (berekent
nog steeds de gedeelde, ongelimiteerde stop). Beide routes die 'm gebruiken
(oefen-preview en oefentrade-aanmaken) roepen na die berekening
`_resolve_signal_risk` aan (of de evaluatie-tak ervan, consistent met hoe
`_resolve_practice_risk_eur` uit het vorige deelproject al
`compute_eval_risk_eur`/`eval_sizing_blocked` hergebruikt) om ook hier de
stop in te perken vóór `compute_position_size` en het aanmaken van de
`journal_entries`-rij, en zetten de override net als bij een echt signaal.
