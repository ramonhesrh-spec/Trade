"""Eenmalige, interactieve check: hoe staat een ETH long er nu voor, en wat
is een betere entry op basis van de zelf-gedetecteerde steun/weerstand-zones
in plaats van instappen op de huidige marktprijs? Gebruikt exact dezelfde
indicators.py/risk.py-functies als de live pipeline, geen aparte logica.
Draai dit handmatig op de VPS (waar Binance wel bereikbaar is), niet vanuit
main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import exchange, indicators, risk

COIN = "ETH"
DIRECTION = "long"

# Hoe ver de prijs nog boven de zone mag zitten om "nu aan het terugtesten"
# te tellen (in ATR): zelfde soort ATR-genormaliseerde marge als
# BTC_FLAT_EMA_GAP_ATR_MULTIPLE in indicators.py. Te klein en een terugtest
# die nog net niet helemaal terug is bij de zone wordt gemist, te groot en
# elke lichte dip na een uitbraak telt al mee.
RETEST_TOLERANCE_ATR_MULTIPLE = 0.3


def find_breakout_retest_zones(df, zones, atr):
    """Voor elke zone: is er, op closing-prijs, een duidelijke uitbraak
    erboven geweest, staat die uitbraak nog overeind (geen candle sindsdien
    weer onder de onderkant van de zone gesloten), en zit de prijs nu weer
    dichtbij die zone? Dat is de uitbraak-dan-terugtest entry: de zone was
    weerstand, is doorbroken, en dient nu als steun voor de terugval. Alleen
    de meest recente uitbraak per zone telt (de laatste candle die van onder
    de zone naar erboven sloot), niet een oudere die inmiddels weer
    overschreden is."""
    closes = df["close"].reset_index(drop=True)
    current_price = closes.iloc[-1]
    hits = []
    for zone in zones:
        broke_above = (closes.shift(1) <= zone.price_high) & (closes > zone.price_high)
        breakout_indices = closes.index[broke_above]
        if len(breakout_indices) == 0:
            continue
        breakout_idx = breakout_indices[-1]
        since_breakout = closes.iloc[breakout_idx + 1:]
        if (since_breakout < zone.price_low).any():
            continue  # uitbraak sindsdien weer volledig ongeldig gemaakt
        candles_since = len(closes) - 1 - breakout_idx
        near_zone = zone.price_low <= current_price <= zone.price_high + RETEST_TOLERANCE_ATR_MULTIPLE * atr
        if near_zone and candles_since > 0:
            hits.append((zone, candles_since))
    return hits

df = exchange.fetch_ohlcv(COIN)
ind = indicators.compute_indicators(df)
confirmed, detail = indicators.confirms_direction(ind, DIRECTION)

print(f"=== {COIN} {DIRECTION} — huidige toestand ===")
print(f"Prijs:  {ind.price:.2f}")
print(f"EMA9:   {ind.ema9:.2f}   EMA21: {ind.ema21:.2f}")
print(f"RSI:    {ind.rsi:.1f}")
print(f"ATR:    {ind.atr:.2f}")
print(f"Bevestigd: {confirmed}")
print(f"Toets: {detail}\n")

zones = indicators.detect_sr_zones(df)
print(f"=== Gedetecteerde steun/weerstand-zones (laatste {indicators.SR_ZONE_LOOKBACK} candles) ===")
for z in sorted(zones, key=lambda z: z.price_low):
    kant = "steun (onder de prijs)" if z.price_high < ind.price else (
        "weerstand (boven de prijs)" if z.price_low > ind.price else "prijs zit er middenin"
    )
    print(f"  {z.price_low:.2f} - {z.price_high:.2f}  ({z.touches}x geraakt, {kant})")

sr_label, sr_ok, sr_detail = indicators.check_sr_zone(DIRECTION, ind.price, ind.atr, zones)
print(f"\nSteun/weerstand-factor: {'OK' if sr_ok else 'geen bruikbare zone'} — {sr_detail}\n")

# Huidige-prijs-entry: exact zoals de pipeline dat nu zou doen, geen
# niveau-data, dus de vaste ATR-fallback (1.5x ATR stop, 2x risk:reward).
huidig = risk.compute_stop_take(DIRECTION, ind.price, ind.atr)
print("=== Optie A: nu instappen, tegen de huidige marktprijs ===")
print(f"Entry:      {ind.price:.2f}")
print(f"Stop loss:  {huidig.stop_loss:.2f}")
print(f"Take profit:{huidig.take_profit:.2f}")
print(f"Risico:     {ind.price - huidig.stop_loss:.2f}\n")

supports_below = sorted(
    (z for z in zones if z.price_high < ind.price),
    key=lambda z: ind.price - z.price_high,
)
if supports_below:
    zone = supports_below[0]
    # Entry op de bovenkant van de zone (waar de prijs hem het eerst raakt
    # bij een terugval), stop net onder de onderkant van diezelfde zone —
    # zelfde swing_low-mechanisme als de live pipeline bij community-
    # niveaus, hier toegepast op de zelf-gedetecteerde zone.
    entry = zone.price_high
    beter = risk.compute_stop_take(DIRECTION, entry, ind.atr, swing_low=zone.price_low)
    afstand_pct = (ind.price - entry) / ind.price * 100
    print(f"=== Optie B: wachten op terugval naar de dichtstbijzijnde steunzone ({zone.touches}x geraakt) ===")
    print(f"Entry:      {entry:.2f}  ({afstand_pct:.1f}% onder de huidige prijs)")
    print(f"Stop loss:  {beter.stop_loss:.2f}")
    print(f"Take profit:{beter.take_profit:.2f}")
    print(f"Risico:     {entry - beter.stop_loss:.2f}")
    print(f"\nVergeleken met optie A: risico per eenheid is "
          f"{(entry - beter.stop_loss) / (ind.price - huidig.stop_loss) * 100:.0f}% "
          f"van optie A, bij dezelfde risk:reward-verhouding.")
else:
    print("Geen steunzone onder de huidige prijs gevonden binnen de lookback-periode: "
          "geen duidelijk beter entry-niveau, optie A is dan het enige aanknopingspunt.")

breakout_retests = find_breakout_retest_zones(df, zones, ind.atr)
if breakout_retests:
    zone, candles_since = max(breakout_retests, key=lambda h: h[0].touches)
    entry = ind.price
    perfect = risk.compute_stop_take(DIRECTION, entry, ind.atr, swing_low=zone.price_low)
    print(f"\n=== Optie C: uitbraak-dan-terugtest (de 'perfecte entry') ===")
    print(f"Zone {zone.price_low:.2f} - {zone.price_high:.2f} was weerstand ({zone.touches}x geraakt), "
          f"is {candles_since} candle(s) geleden doorbroken en wordt nu opnieuw getest als steun.")
    print(f"Entry:      {entry:.2f}  (nu, tijdens de terugtest)")
    print(f"Stop loss:  {perfect.stop_loss:.2f}  (net onder de doorbroken zone)")
    print(f"Take profit:{perfect.take_profit:.2f}")
    print(f"Risico:     {entry - perfect.stop_loss:.2f}")
else:
    print("\n=== Optie C: uitbraak-dan-terugtest ===")
    print("Geen zone gevonden die recent doorbroken is en nu opnieuw getest wordt: "
          "deze opzet is er op dit moment niet voor ETH.")
