"""Welke coins kunnen erbij? Alleen-lezen. Draai op de VPS: .venv/bin/python3 scripts/coin_kandidaten.py [--aantal 15]
Toont de coins die HesPulse nu volgt en de meest verhandelde USDT-paren die er nog niet bij staan (24-uurs volume), zonder stablecoins en
hefboomtokens, met koers en de verandering over 24 uur. Dit is een lijst om uit te kiezen: of je platform de coin als perp heeft, controleer je zelf."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, exchange, repo  # noqa: E402

STABLES = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USDP", "USDE", "BUSD", "EUR", "EURI", "AEUR", "XUSD", "USD1", "PAXG", "WBTC", "WBETH", "BFUSD"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aantal", type=int, default=15)
    a = ap.parse_args()
    current = sorted(c["symbol"] for c in repo.list_coins())
    print(f"Nu gevolgd ({len(current)}): {', '.join(current)}\n")
    ex = exchange.get_exchange()
    rows = []
    for symbol, t in ex.fetch_tickers().items():
        base, _, quote = symbol.partition("/")
        if quote != config.QUOTE_CURRENCY or ":" in symbol or base in STABLES or base in current:
            continue
        if base.endswith(("UP", "DOWN", "BULL", "BEAR")) or not t.get("quoteVolume") or not t.get("last"):
            continue
        rows.append((t["quoteVolume"], base, t["last"], t.get("percentage") or 0.0))
    rows.sort(reverse=True)
    print(f"Kandidaten, meest verhandeld eerst (volume in miljoen {config.QUOTE_CURRENCY} per 24 uur):")
    for i, (vol, base, last, pct) in enumerate(rows[:a + 10], 1):
        print(f"{i:>2}. {base:<8} {vol / 1e6:>8.1f} M   koers {last:<12g} {pct:+.1f}% 24u")
    print(f"\nZet je keuze in .env: EXTRA_COINS={','.join(current_extra(current))}{',' if current_extra(current) else ''}NIEUW1,NIEUW2,... en herstart crypto-bot.")


def current_extra(current: list[str]) -> list[str]:
    return [c for c in current if c not in config.BASE_COINS]


if __name__ == "__main__":
    main()
