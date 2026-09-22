"""Eenmalige, interactieve check over de volledige gevolgde coinlijst: voor
elke coin de richting (trend-based, zelfde als market_scanner.py), of de
kans nu al bevestigd is, en drie entry-opties (huidige marktprijs, terugval
naar de dichtstbijzijnde zone, uitbraak-dan-terugtest). Gebruikt exact
dezelfde indicators.py/risk.py-functies als de live pipeline, geen aparte
logica. Print een volledig overzicht in de terminal en stuurt daarnaast een
compacte samenvatting naar Telegram (naar de eerste gebruiker met een
gekoppelde chat_id). Draai dit handmatig op de VPS (waar Binance wel
bereikbaar is), niet vanuit main.py."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot

from app import config, exchange, indicators, repo, risk

DIVIDER = "━" * 14


def check_coin(coin: str) -> dict:
    """Print het volledige overzicht voor deze coin en geeft een compact
    resultaat terug voor de Telegram-samenvatting in main()."""
    df = exchange.fetch_ohlcv(coin)
    ind = indicators.compute_indicators(df)
    direction = "long" if ind.ema9 > ind.ema21 else "short"
    # daily_trend_factor=None: net als market_scanner.py's cheap precheck,
    # bewust geen dagtrend-hard-gate hier — een 1d-candle per coin ophalen
    # zou dit al trage, interactieve overzicht (alle gevolgde coins in één
    # run) nog verder vertragen, dus dit blijft een vereenvoudigd
    # (geen-dagtrend) scenario, niet representatief voor de volledige
    # productietoetsing in process_day_trading_signal.
    confirmed, detail, _, _ = indicators.confirms_direction(ind, direction, daily_trend_factor=None)
    zones = indicators.detect_sr_zones(df)
    factors = indicators.basic_factors(direction, ind)

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

    perfect_entry = None
    breakout_retests = indicators.find_breakout_retest(df, zones, ind.atr, direction)
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
        perfect_entry = {
            "coin": coin, "direction": direction, "confirmed": confirmed,
            "entry": entry, "stop_loss": perfect.stop_loss, "take_profit": perfect.take_profit,
        }

    return {
        "coin": coin, "direction": direction, "confirmed": confirmed,
        "factors": factors, "perfect_entry": perfect_entry,
    }


def build_telegram_summary(results: list[dict]) -> str:
    perfect_entries = [r["perfect_entry"] for r in results if r["perfect_entry"]]
    confirmed_long = [r["coin"] for r in results if r["confirmed"] and r["direction"] == "long"]
    confirmed_short = [r["coin"] for r in results if r["confirmed"] and r["direction"] == "short"]
    not_confirmed = [r["coin"] for r in results if not r["confirmed"]]

    lines = ["🔍 Coin-check — alle gevolgde coins", DIVIDER]

    if perfect_entries:
        lines.append("")
        lines.append("🎯 Perfecte entry (uitbraak + terugtest):")
        for pe in perfect_entries:
            note = "" if pe["confirmed"] else " (niet bevestigd)"
            lines.append(
                f"• {pe['coin']} {pe['direction']} — entry {pe['entry']:.4f}, "
                f"stop {pe['stop_loss']:.4f}, take {pe['take_profit']:.4f}{note}"
            )
    else:
        lines.append("")
        lines.append("🎯 Geen enkele coin heeft nu een actieve uitbraak-dan-terugtest.")

    lines.append("")
    lines.append(DIVIDER)
    lines.append(f"✅ Bevestigd long: {', '.join(confirmed_long) if confirmed_long else '—'}")
    lines.append(f"✅ Bevestigd short: {', '.join(confirmed_short) if confirmed_short else '—'}")
    lines.append(f"⚠️ Niet bevestigd: {', '.join(not_confirmed) if not_confirmed else '—'}")

    # Meest voorkomende falende factor bij de short-richting: vaak dezelfde
    # oorzaak (bijvoorbeeld trend net gedraaid, momentum nog niet mee) voor
    # meerdere coins tegelijk, dat is dan in één oogopslag te zien.
    shorts = [r for r in results if r["direction"] == "short"]
    if shorts:
        fail_counts: dict[str, int] = {}
        for r in shorts:
            for name, ok, _ in r["factors"]:
                if not ok:
                    fail_counts[name] = fail_counts.get(name, 0) + 1
        if fail_counts:
            top_factor, count = max(fail_counts.items(), key=lambda kv: kv[1])
            if count >= max(2, len(shorts) // 2):
                lines.append("")
                lines.append(DIVIDER)
                lines.append(f"📌 Bij {count} van de {len(shorts)} shorts faalt steeds dezelfde factor: {top_factor}.")

    return "\n".join(lines)


async def send_summary(text: str) -> None:
    users = repo.list_users()
    target = next((u for u in users if u.get("telegram_chat_id")), None)
    if not target:
        print("\nGeen gebruiker met een gekoppelde Telegram gevonden, samenvatting niet verstuurd.")
        return
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    await bot.send_message(chat_id=target["telegram_chat_id"], text=text)
    print(f"\nSamenvatting verstuurd naar {target['username']} op Telegram.")


def main() -> None:
    coins = repo.list_coins()
    print(f"Check over {len(coins)} gevolgde coins...")
    results = []
    for coin_row in coins:
        coin = coin_row["symbol"]
        try:
            results.append(check_coin(coin))
        except Exception as exc:
            print(f"\n{coin}: MISLUKT — {exc}")

    print(f"\n{'=' * 60}")
    print("Klaar. Zoek hierboven naar '*** Optie C ***' voor coins met een "
          "actieve uitbraak-dan-terugtest.")

    summary = build_telegram_summary(results)
    asyncio.run(send_summary(summary))


if __name__ == "__main__":
    main()
