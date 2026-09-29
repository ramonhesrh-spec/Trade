"""Eenmalige diagnose: heeft de prijs sinds het aanmaken van een signaal
ooit de stop loss of take profit geraakt, gebaseerd op candle-hoog/laag in
plaats van op de losse live-prijs-polls die check_open_trades/
check_signal_outcomes gebruiken? Toont elke candle waarvan de wick het
niveau raakte. Puur diagnostisch, geen wijziging aan het systeem.
Draai met: python3 scripts/check_stop_hit_since.py <signal_id> [timeframe]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, exchange

if len(sys.argv) < 2:
    print("Gebruik: python3 scripts/check_stop_hit_since.py <signal_id> [timeframe]")
    sys.exit(1)

signal_id = int(sys.argv[1])
timeframe = sys.argv[2] if len(sys.argv) > 2 else "5m"

with db.session() as conn:
    signal = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()

if signal is None:
    print(f"Geen signaal met id {signal_id} gevonden.")
    sys.exit(1)

print(f"Signaal {signal_id}: {signal['coin']} {signal['direction']} sinds {signal['created_at']}")
print(f"  entry {signal['price']}  stop {signal['stop_loss']}  take {signal['take_profit']}")
print(f"  auto_outcome in db: {signal['auto_outcome']}\n")

from datetime import datetime  # noqa: E402
since_ms = int(datetime.fromisoformat(signal["created_at"]).timestamp() * 1000)

df = exchange.fetch_ohlcv(signal["coin"], timeframe=timeframe, since=since_ms, limit=1000)
print(f"{len(df)} {timeframe}-candles opgehaald sinds het signaal, van {df['timestamp'].iloc[0]} tot {df['timestamp'].iloc[-1]}\n")

direction = signal["direction"]
stop_loss = signal["stop_loss"]
take_profit = signal["take_profit"]

hits = []
for _, c in df.iterrows():
    if direction == "long":
        if stop_loss is not None and c["low"] <= stop_loss:
            hits.append((c["timestamp"], "stop loss", c["low"]))
        if take_profit is not None and c["high"] >= take_profit:
            hits.append((c["timestamp"], "take profit", c["high"]))
    else:
        if stop_loss is not None and c["high"] >= stop_loss:
            hits.append((c["timestamp"], "stop loss", c["high"]))
        if take_profit is not None and c["low"] <= take_profit:
            hits.append((c["timestamp"], "take profit", c["low"]))

if not hits:
    print("Geen enkele candle-wick raakte stop of take sinds het signaal.")
else:
    print(f"{len(hits)} candle(s) waarvan de wick een niveau raakte (eerste hieronder is de vroegste):")
    for ts, kind, price in hits[:10]:
        print(f"  {ts}  {kind} geraakt op {price}")

print(f"\nHoogste high sinds signaal: {df['high'].max()}")
print(f"Laagste low sinds signaal: {df['low'].min()}")
print(f"Laatste close: {df['close'].iloc[-1]}")
