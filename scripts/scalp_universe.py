"""Schift een lijst coins op geschiktheid voor een BTC-voorsprong-scalp: achterstand op BTC, beta en liquiditeit. Downloadt 1m-candles
van de laatste dagen (en bewaart ze in data/candles, zodat scalp_scan ze daarna kan gebruiken). Zie app/replay/scalp_universe.py.
Draai: python3 scripts/scalp_universe.py [--coins ETH,SOL,...] [--days 120]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import exchange  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import scalp_universe as su  # noqa: E402

DEFAULT = ("ETH,SOL,XRP,DOGE,ADA,AVAX,LINK,LTC,DOT,SUI,BNB,TRX,NEAR,APT,ARB,OP,INJ,ATOM,UNI,AAVE,HBAR,WLD,ONDO,PEPE,WIF,FET,TAO,TIA,SEI,BCH")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=DEFAULT)
    p.add_argument("--days", type=int, default=120)
    a = p.parse_args()
    btc = candle_cache.load_candles("BTC", "1m")
    rows = []
    for coin in a.coins.split(","):
        try:
            if not exchange.market_exists(coin):
                print(f"{coin}: geen markt op de exchange, overgeslagen", flush=True)
                continue
            frame = candle_cache.ensure_candles(coin, a.days / 365, timeframe="1m")
        except Exception as exc:
            print(f"{coin}: ophalen mislukt ({exc})", flush=True)
            continue
        res = su.screen(btc, frame.tail(a.days * 1440))
        if res:
            rows.append((coin, res))
            print(f"{coin}: klaar", flush=True)
    print(f"\nAchterstand = wat de alt de 3 minuten na een BTC-minuut van {su.BTC_MOVE_BP:g} bp gemiddeld nog bijtrekt. Kosten {su.COST_BP:g} bp.")
    print(f"{'coin':<7}{'achterstand bp':>16}{'t':>7}{'beta':>7}{'USD/min (mediaan)':>20}{'range bp':>10}  geschikt")
    for coin, r in sorted(rows, key=lambda x: -x[1]["achterstand_bp"]):
        good = r["achterstand_bp"] > su.COST_BP and r["t_lag"] > 3 and r["quote_per_min"] > 50_000
        print(f"{coin:<7}{r['achterstand_bp']:>+16.1f}{r['t_lag']:>7.1f}{r['beta']:>7.2f}{r['quote_per_min']:>20,.0f}{r['range_bp']:>10.1f}  {'JA' if good else ''}")


if __name__ == "__main__":
    main()
