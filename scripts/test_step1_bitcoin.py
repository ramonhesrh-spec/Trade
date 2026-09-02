"""Stap 1: technische data en indicatoren voor bitcoin, los van Discord.
Draai met: python3 scripts/test_step1_bitcoin.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import exchange, indicators, risk


def main() -> None:
    coin = "BTC"
    print(f"Bestaat {exchange.to_symbol(coin)} op {exchange.get_exchange().id}? "
          f"{exchange.market_exists(coin)}")

    df = exchange.fetch_ohlcv(coin)
    print(f"Aantal candles opgehaald: {len(df)}")
    print(df.tail(3))

    ind = indicators.compute_indicators(df)
    print("\nIndicatoren (4h):")
    print(f"  prijs:         {ind.price}")
    print(f"  RSI(14):       {ind.rsi:.2f}")
    print(f"  MACD:          {ind.macd:.2f}")
    print(f"  MACD signaal:  {ind.macd_signal:.2f}")
    print(f"  volume ratio:  {ind.volume_ratio:.2f}x gemiddelde 20 candles")
    print(f"  EMA9:          {ind.ema9:.2f}")
    print(f"  EMA21:         {ind.ema21:.2f}")
    print(f"  ATR:           {ind.atr:.2f}")

    for direction in ("long", "short"):
        confirmed, reason = indicators.confirms_direction(ind, direction)
        levels = risk.compute_levels(
            direction=direction,
            entry_price=ind.price,
            atr=ind.atr,
            portfolio_eur=10000,
            risk_percent=1.0,
        )
        print(f"\nRichting {direction}: bevestigd = {confirmed} ({reason})")
        print(f"  stop loss:    {levels.stop_loss:.2f}")
        print(f"  take profit:  {levels.take_profit:.2f}")
        print(f"  risicobedrag: {levels.risk_eur:.2f} euro (bij 10.000 euro portfolio, 1%)")


if __name__ == "__main__":
    main()
