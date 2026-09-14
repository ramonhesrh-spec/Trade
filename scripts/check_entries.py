"""Eenmalige, interactieve check over de volledige gevolgde coinlijst: voor
elke coin de richting (trend-based, zelfde als market_scanner.py), of de
kans nu al bevestigd is, en drie entry-opties (huidige marktprijs, terugval
naar de dichtstbijzijnde zone, uitbraak-dan-terugtest). Gebruikt exact
dezelfde indicators.py/risk.py-functies als de live pipeline, geen aparte
logica. Draai dit handmatig op de VPS (waar Binance wel bereikbaar is),
niet vanuit main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import exchange, indicators, repo, risk

# Hoe ver de prijs nog voorbij de zone mag zitten om "nu aan het
# terugtesten" te tellen (in ATR): zelfde soort ATR-genormaliseerde marge
# als BTC_FLAT_EMA_GAP_ATR_MULTIPLE in indicators.py.
RETEST_TOLERANCE_ATR_MULTIPLE = 0.3


def find_breakout_retest_zones(df, zones, atr, direction):
    """Voor elke zone: is er, op closing-prijs, een duidelijke uitbraak in
    de richting van de trade geweest, staat die uitbraak nog overeind (geen
    candle sindsdien weer terug over de andere kant van de zone gesloten),
    en zit de prijs nu weer dichtbij die zone? Bij long: de zone was
    weerstand, is doorbroken naar boven, en dient nu als steun voor de
    terugval. Bij short: precies omgekeerd, de zone was steun, is naar
    beneden doorbroken en dient nu als weerstand. Alleen de meest recente
    uitbraak per zone telt."""
    closes = df["close"].reset_index(drop=True)
    current_price = closes.iloc[-1]
    hits = []
    for zone in zones:
        if direction == "long":
            broke = (closes.shift(1) <= zone.price_high) & (closes > zone.price_high)
            invalidate_level = zone.price_low
        else:
            broke = (closes.shift(1) >= zone.price_low) & (closes < zone.price_low)
            invalidate_level = zone.price_high

        breakout_indices = closes.index[broke]
        if len(breakout_indices) == 0:
            continue
        breakout_idx = breakout_indices[-1]
        since_breakout = closes.iloc[breakout_idx + 1:]
        if direction == "long":
            if (since_breakout < invalidate_level).any():
                continue
            near_zone = zone.price_low <= current_price <= zone.price_high + RETEST_TOLERANCE_ATR_MULTIPLE * atr
        else:
            if (since_breakout > invalidate_level).any():
                continue
            near_zone = zone.price_low - RETEST_TOLERANCE_ATR_MULTIPLE * atr <= current_price <= zone.price_high

        candles_since = len(closes) - 1 - breakout_idx
        if near_zone and candles_since > 0:
            hits.append((zone, candles_since))
    return hits


def check_coin(coin: str) -> None:
    df = exchange.fetch_ohlcv(coin)
    ind = indicators.compute_indicators(df)
    direction = "long" if ind.ema9 > ind.ema21 else "short"
    confirmed, detail = indicators.confirms_direction(ind, direction)
    zones = indicators.detect_sr_zones(df)

    print(f"\n{'=' * 60}")
    print(f"{coin} — richting: {direction}   prijs: {ind.price:.4f}   "
          f"bevestigd: {confirmed}")
    print(f"  {detail}")

    huidig = risk.compute_stop_take(direction, ind.price, ind.atr)
    print(f"  Optie A (nu): entry {ind.price:.4f}  stop {huidig.stop_loss:.4f}  "
          f"take {huidig.take_profit:.4f}")

    if direction == "long":
        candidates = sorted((z for z in zones if z.price_high < ind.price),
                             key=lambda z: ind.price - z.price_high)
    else:
        candidates = sorted((z for z in zones if z.price_low > ind.price),
                             key=lambda z: z.price_low - ind.price)
    if candidates:
        zone = candidates[0]
        entry = zone.price_high if direction == "long" else zone.price_low
        beter = risk.compute_stop_take(
            direction, entry, ind.atr,
            swing_low=zone.price_low if direction == "long" else None,
            swing_high=zone.price_high if direction == "short" else None,
        )
        print(f"  Optie B (terugval naar zone, {zone.touches}x geraakt): "
              f"entry {entry:.4f}  stop {beter.stop_loss:.4f}  take {beter.take_profit:.4f}")

    breakout_retests = find_breakout_retest_zones(df, zones, ind.atr, direction)
    if breakout_retests:
        zone, candles_since = max(breakout_retests, key=lambda h: h[0].touches)
        entry = ind.price
        perfect = risk.compute_stop_take(
            direction, entry, ind.atr,
            swing_low=zone.price_low if direction == "long" else None,
            swing_high=zone.price_high if direction == "short" else None,
        )
        print(f"  *** Optie C (uitbraak-dan-terugtest, de 'perfecte entry') ***")
        print(f"      Zone {zone.price_low:.4f} - {zone.price_high:.4f} "
              f"({zone.touches}x geraakt), {candles_since} candle(s) geleden doorbroken, "
              f"nu terugtest.")
        print(f"      Entry {entry:.4f}  stop {perfect.stop_loss:.4f}  take {perfect.take_profit:.4f}")


def main() -> None:
    coins = repo.list_coins()
    print(f"Check over {len(coins)} gevolgde coins...")
    perfect_entries = []
    for coin_row in coins:
        coin = coin_row["symbol"]
        try:
            check_coin(coin)
        except Exception as exc:
            print(f"\n{coin}: MISLUKT — {exc}")

    print(f"\n{'=' * 60}")
    print("Klaar. Zoek hierboven naar '*** Optie C ***' voor coins met een "
          "actieve uitbraak-dan-terugtest.")


if __name__ == "__main__":
    main()
