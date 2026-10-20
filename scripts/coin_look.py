"""Wat ziet de motor op één coin? Alleen-lezen: haalt candles op, toont koers en beweging, de range per timeframe (of waarom er geen is), de actieve
zones en de setups van de laatste 48 uur. Draai op de VPS: .venv/bin/python3 scripts/coin_look.py NEAR"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.replay import rangesweep as rs, trendlab as tl  # noqa: E402
from app.replay.lab import add_indicators  # noqa: E402

COMBOS = (("zone", "zone", "slot"), ("sweep", "ob", "slot"))


def _fmt(v: float) -> str:
    return f"{v:.4f}" if abs(v) < 10 else f"{v:,.2f}"


def look(coin: str, frames: dict, price: float, now: pd.Timestamp) -> list[str]:
    out = [f"{coin} nu {_fmt(price)}"]
    h1 = rs.closed_only(frames["1h"], now, "1h")
    last24, last7 = h1.tail(24), h1.tail(24 * 7)
    if len(last24) >= 24:
        out.append(f"24 uur: laag {_fmt(last24['low'].min())}, hoog {_fmt(last24['high'].max())}, bandbreedte {100 * (last24['high'].max() / last24['low'].min() - 1):.1f}%")
    if len(last7) >= 24 * 7:
        out.append(f"7 dagen: laag {_fmt(last7['low'].min())}, hoog {_fmt(last7['high'].max())}, bandbreedte {100 * (last7['high'].max() / last7['low'].min() - 1):.1f}%, "
                   f"verandering {100 * (price / last7['close'].iloc[0] - 1):+.1f}%")
    a = add_indicators(h1)["atr"].iloc[-1]
    out.append(f"ATR 1u: {_fmt(a)} ({100 * a / price:.2f}% van de koers)")
    out.append("")
    out.append("Ranges, per timeframe")
    for tf in rs.TFS:
        closed = rs.closed_only(frames[tf], now, tf)
        if len(closed) < 40:
            out.append(f"  {tf}: te weinig candles"); continue
        b = add_indicators(closed).reset_index(drop=True)
        hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
        rng, why = rs.range_at(b, len(b) - 1, tf, tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N))
        if rng is None:
            out.append(f"  {tf}: geen range ({why})"); continue
        pos = 100 * (price - rng.low) / (rng.high - rng.low)
        side = "boven de range" if pos > 100 else "onder de range" if pos < 0 else f"{pos:.0f}% omhoog in de range"
        out.append(f"  {tf}: {_fmt(rng.low)} tot {_fmt(rng.high)}, {rng.high_touches} keer boven en {rng.low_touches} keer onder aangeraakt, "
                   f"{(rng.high - rng.low) / rng.atr:.1f} ATR breed. De koers staat {side}.")
        idx = len(b) - 1
        zones = [z for z in rs.find_zones(b) if rs.zone_active(z, idx)]
        for z in zones[-3:]:
            out.append(f"      {'aanbodzone' if z.kind == 'bear' else 'vraagzone'} {_fmt(z.low)} tot {_fmt(z.high)}")
    out.append("")
    out.append("Setups van de laatste 48 uur")
    found = 0
    for tf in ("1h", "2h", "4h"):
        closed = {k: rs.closed_only(v, now, k) for k, v in frames.items()}
        for family, entry, confirm in COMBOS:
            setups, _ = rs.find_setups(closed, tf, family, entry, confirm, True)
            for s in setups:
                if now - s["placed_at"] > pd.Timedelta(hours=48):
                    continue
                found += 1
                legs = ", ".join(_fmt(p) for _, p in s["legs"])
                out.append(f"  {tf} {family} {s['direction']} geplaatst {s['placed_at']:%d-%m %H:%M} UTC: limiet {legs}, stop {_fmt(rs.final_stop(s, 'zone_025'))}, "
                           f"zone {_fmt(s['zone_low'])} tot {_fmt(s['zone_high'])}")
    if not found:
        out.append("  geen")
    return out


def main() -> None:
    coin = (sys.argv[1] if len(sys.argv) > 1 else "NEAR").upper()
    import misser_check
    from app import exchange
    now = pd.Timestamp.now(tz="UTC")
    frames = misser_check.fetch_rangesweep(coin, now)
    print("\n".join(look(coin, frames, exchange.fetch_last_price(coin), now)))


if __name__ == "__main__":
    main()
