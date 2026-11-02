"""Controle achteraf van het HesPulse-model (preregistratie, Besluiten CEO 2026-11-02 punt 1, en §10 poort 3): laat het model over de laatste
14 dagen op alle config.FIXED_COINS lopen, alleen op gesloten candles, en tekent de eerste 30 gevonden scenario's als één HTML-bestand met per
kaart een SVG (range met premium en discount, pool, sweep, shift-candle, FVG en order block, limiet, stop, doel, POC's als kandidaat) en per
stap het tijdstip waarop hij herkenbaar was.

"Zonder toekomst": per getekend scenario wordt het model opnieuw gedraaid op de candles tot elke stap, en die moet daar al precies zo staan
(model.known_until). Een afwijking staat rood op de kaart. Alleen lezen: niets gaat de database in, er gaat geen melding uit.

    python3 scripts/model_kaarten.py                       # data/model_kaarten.html
    python3 scripts/model_kaarten.py --dagen 14 --aantal 30 --uit /tmp/kaarten.html --coins BTC,ETH
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, model, model_chart  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "model_kaarten.html"
# Ruim boven 14 dagen: de 4u-bias kijkt 60 candles terug, pools 120 candles van 1u, en de 15m-ATR moet warm zijn.
LIMITS = {"1d": 400, "4h": 400, "1h": 1000, "15m": 1500}      # 1d: de richting top-down, zoals live (aanvullend besluit 2026-11-03)
logger = logging.getLogger("model_kaarten")


def fetch(coin: str, tf: str, limit: int) -> pd.DataFrame:
    from app import exchange
    return exchange.fetch_ohlcv(coin, timeframe=tf, limit=limit)


def stored_pocs(coin: str, now: pd.Timestamp):
    """De bewaarde POC-niveaus van de POC-radar (data/trading.db), of None zonder database of zonder meting voor deze coin."""
    try:
        from app import poc_radar_live, repo
        if repo.get_poc_scan(coin) is None:
            return None
        return poc_radar_live.stored_levels(coin, now)
    except Exception:
        return None


def check_prefix(sc: dict, frames: dict, pocs) -> list[str]:
    """Draait het model op de candles tot elke stap en eist dat wat dan bekend was gelijk is aan de volledige run."""
    problems = []
    for s in sc["steps"]:
        cut = s["at"]
        part = {tf: df[df["timestamp"] + model.TF[tf] <= cut] for tf, df in frames.items()}
        same = [p for p in model.scenarios(part, cut, pocs) if p["range_id"] == sc["range_id"]]
        if not same or model.known_until(same[0], cut) != model.known_until(sc, cut):
            problems.append(f"stap {s['stap']} op {cut:%d-%m %H:%M} wijkt af zonder de latere candles")
    return problems


def collect(coins: list[str], now: pd.Timestamp, days: int, limit: int, fetcher: Optional[Callable] = None, pocs_of: Callable = stored_pocs,
            check: bool = True) -> list[dict]:
    """De eerste `limit` scenario's (op het moment van ontdekken) die in de laatste `days` dagen ontdekt werden, met hun candles."""
    fetcher = fetcher or fetch
    since = now - pd.Timedelta(days=days)
    found = []
    for coin in coins:
        try:
            frames = {tf: f for tf, n in LIMITS.items() if (f := fetcher(coin, tf, n)) is not None}
        except Exception:
            logger.exception("Candles voor %s niet op te halen", coin)
            continue
        pocs = pocs_of(coin, now)
        for sc in model.scenarios(frames, now, pocs):
            if sc["discovered_at"] >= since:
                found.append({**sc, "coin": coin, "_frames": frames, "_pocs": pocs})
    found.sort(key=lambda s: (s["discovered_at"], s["coin"], s["direction"]))
    chosen = found[:limit]
    for sc in chosen:
        sc["problems"] = check_prefix(sc, sc["_frames"], sc["_pocs"]) if check else []
    return chosen


STATUS_TEXT = {"wacht_sweep": "wacht op sweep", "prik": "sweep bezig", "wacht_shift": "wacht op shift", "wacht_fvg": "wacht op gap",
               "afgerond": "entry beschikbaar", "context_weg": "context weg", "geen_pool": "geen pool meer"}


def card_html(n: int, sc: dict) -> str:
    rows = "".join(f"<tr><td>{escape(stap)}</td><td>{escape(at)}</td><td>{escape(note)}</td></tr>" for stap, at, note in model_chart.step_rows(sc))
    probs = "".join(f'<p class="bad">{escape(p)}</p>' for p in sc.get("problems") or [])
    ok = '<p class="ok">Zonder latere candles hetzelfde.</p>' if not sc.get("problems") else ""
    return (f'<section class="card" id="kaart-{n}"><h2>{n}. {escape(sc["coin"])} {sc["direction"]} · {STATUS_TEXT.get(sc["status"], sc["status"])}</h2>'
            f'<p class="meta">Range {escape(sc["range_id"])} · ontdekt {sc["discovered_at"]:%d-%m %H:%M} UTC</p>'
            f'{model_chart.full_svg(sc, sc["_frames"]["15m"])}'
            f'<table><thead><tr><th>Stap</th><th>Herkenbaar op (Amsterdam)</th><th>Wat</th></tr></thead><tbody>{rows}</tbody></table>{ok}{probs}'
            f'<p class="judge">Klopt met de definities? ☐ ja ☐ nee, want: ____________________</p></section>')


def build_html(chosen: list[dict], now: pd.Timestamp, days: int) -> str:
    cards = "".join(card_html(i, sc) for i, sc in enumerate(chosen, 1))
    legend = ("A = scenario ontdekt, S = sweep, C = shift (change of character of BOS), D = displacement met gap vastgesteld, B = entry "
              "beschikbaar; ✕ = een mislukte poging. Elke streep staat op het sluiten van de candle waarop de stap herkenbaar was.")
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HesPulse-model kaarten</title>
<style>
body {{ margin: 0; padding: 16px; background: #0b1012; color: #e8eef0; font: 14px/1.45 system-ui, sans-serif; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }} h2 {{ font-size: 16px; margin: 0 0 4px; }}
.card {{ background: #121a1d; border: 1px solid #22303a; border-radius: 12px; padding: 12px; margin: 16px 0; max-width: 1000px; }}
.meta, .legend {{ color: #9aa5b1; margin: 0 0 8px; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 13px; }} td, th {{ border-top: 1px solid #22303a; padding: 4px 6px; text-align: left; vertical-align: top; }}
.ok {{ color: #2ecc71; }} .bad {{ color: #e74c3c; font-weight: 700; }} .judge {{ color: #9aa5b1; }}
</style></head><body>
<h1>HesPulse-model: {len(chosen)} getekende scenario's</h1>
<p class="meta">Laatste {days} dagen tot {now:%d-%m-%Y %H:%M} UTC, coins {escape(", ".join(sorted({s["coin"] for s in chosen})) or "-")}. Alleen gesloten candles.
Controle achteraf (besluit CEO 2026-11-02): het model is live; fouten in de code worden hersteld, regels niet.</p>
<p class="legend">{legend}</p>
{cards or '<p>Geen scenario gevonden.</p>'}
</body></html>
"""


def _t(v) -> str:
    return "-" if v is None else pd.Timestamp(v).strftime("%d-%m %H:%M")


def _lvl(e: Optional[dict]) -> str:
    if not e:
        return "geen"
    take = e.get("take")
    return (f"limiet {e['limit']:.6g}, stop {e['stop']:.6g}, doel {take:.6g}" if take is not None else
            f"limiet {e['limit']:.6g}, stop {e['stop']:.6g}, geen doel") + (f", bekend {_t(e.get('known_at'))}" if e.get("known_at") else "")


def text_report(chosen: list[dict]) -> str:
    """Hetzelfde als de HTML, als tekst voor de terminal: elke stap met het moment waarop hij herkenbaar was (UTC), de mislukte pogingen met
    hun reden, en alle instappunten (A, B, B0, V1, P). Zo kan iemand zonder browser op de VPS het resultaat doorsturen."""
    lines = []
    for s in chosen:
        lines.append(f"== {s['coin']} {s['direction']} · ontdekt {_t(s['discovered_at'])} · stand {s['status']} · range "
                     f"{s['range_low']:.6g}-{s['range_high']:.6g} (EQ {s['eq']:.6g})")
        for st in s.get("steps") or []:
            extra = ", ".join(f"{k} {v:.6g}" for k, v in st.items() if k in ("pool", "extreme", "top") and v is not None)
            lines.append(f"   stap {st['stap']:<13} {_t(st.get('at'))}" + (f"  ({extra})" if extra else ""))
        for a in s.get("attempts") or []:
            lines.append(f"   ✕ poging {_t(a['at'])}: {a['reden']}" + (f" (pool {a['pool']:.6g})" if a.get("pool") is not None else ""))
        lines.append(f"   A  na sweep:      {_lvl(s.get('entry'))}")
        lines.append(f"   B  lagere top:    {_lvl(s.get('b'))}")
        lines.append(f"   B0 zonder premium:{_lvl(s.get('b0'))}")
        lines.append(f"   V1 vroege limiet: {_lvl(s.get('v1'))}")
        lines.append(f"   P  POC-limiet:    {_lvl(s.get('p'))}")
        for prob in s.get("problems") or []:
            lines.append(f"   !! afwijking zonder latere candles: {prob}")
    return "\n".join(lines) if lines else "Geen scenario gevonden."


def main(argv: Optional[list[str]] = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dagen", type=int, default=14)
    ap.add_argument("--aantal", type=int, default=30)
    ap.add_argument("--coins", default="", help="kommagescheiden; standaard config.FIXED_COINS")
    ap.add_argument("--uit", default=str(DEFAULT_OUT))
    ap.add_argument("--zonder-controle", action="store_true", help="sla de herberekening zonder latere candles over (sneller)")
    ap.add_argument("--tekst", action="store_true", help="druk elk scenario ook als tekst af (stappen, pogingen, alle instappunten)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    now = pd.Timestamp(datetime.now(timezone.utc))
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()] or list(config.FIXED_COINS)
    chosen = collect(coins, now, args.dagen, args.aantal, check=not args.zonder_controle)
    out = Path(args.uit)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(chosen, now, args.dagen), encoding="utf-8")
    bad = sum(1 for s in chosen if s.get("problems"))
    print(f"{len(chosen)} scenario's getekend in {out}" + (f"; {bad} met een afwijking zonder latere candles" if bad else ""))
    if args.tekst:
        print(text_report(chosen))
    return out


if __name__ == "__main__":
    main()
