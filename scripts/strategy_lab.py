"""Strategie-lab: toetst kosten-robuuste regels op 1u en 4u (zie app/replay/trendlab.py). Draai op de VPS, de candles zijn klein en snel op te halen:

  .venv/bin/python3 scripts/strategy_lab.py [--jaren 3] [--coins BTC,ETH,...] [--kosten 0.06] [--familie alle|kanteling|standaard|rangesweep] [--alleen-volledig] [--opslaan]

Een variant slaagt alleen als beide helften positief zijn, de marge boven 0 ligt en hij beter is dan willekeurige instappen met dezelfde uitgang.
Het aantal getoetste varianten staat in de uitvoer: hoe meer, hoe minder bijzonder een treffer is. Met --alleen-volledig tellen alleen coins mee die de hele periode bestaan (overlevingscontrole). Vertrouw alleen wat ook in de tweede helft overeind blijft.

`alle` is alleen de trendlab-families; `--familie rangesweep` heeft een eigen register (app/replay/rangesweep_lab.py, pre-registratie in docs/onderzoek/range-sweep/)
en eigen opties: --hervat MAP (tussenresultaat per coin, een onderbroken run gaat verder) en --rapport PAD (vult de tekst tussen de markers van het resultatenbestand)."""
import argparse
import json
import os
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db, repo  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import positioning, rangesweep as rs, rangesweep_lab as rl  # noqa: E402
from app.replay import trendlab as tl  # noqa: E402

SUMMARY_KEYS = ("n", "avg", "ci", "week_ci", "train", "test", "placebo", "winrate", "gross", "median_risk_pct")
LAB_COINS = ",".join(tl.LAB_COINS)


def save_results(results, now_iso: str) -> int:
    """Slaat de uitkomst per variant met trades op; varianten zonder trades blijven ongemoeid."""
    db.init_db()
    saved = 0
    for v, r in results:
        if not r.get("n"):
            continue
        # tuples worden JSON-lijsten; numpy-getallen gaan via default=float in repo.set_rule_lab
        repo.set_rule_lab(v.name.lower(), bool(r["passes"]), {k: r.get(k) for k in SUMMARY_KEYS}, now_iso)
        saved += 1
    return saved


def coverage_warning(tf: str, first: pd.Timestamp, last: pd.Timestamp, jaren: float):
    """Waarschuwing als de candles die er echt zijn meer dan 14 dagen korter dekken dan gevraagd. ensure_candles geeft een bestaande cache terug zonder
    naar het aantal jaren te kijken (de 15m-cache wordt door andere scripts gedeeld), dus --jaren kan stil genegeerd worden."""
    days, asked = (last - first).days, round(jaren * 365)
    if asked - (last - first) / pd.Timedelta(days=1) > 14:
        return f"let op: {tf} dekt maar {days} dagen, gevraagd {asked}"
    return None


def check_coverage(coin: str, frames: dict, jaren: float) -> None:
    """Stopt als een van de timeframes meer dan 14 dagen korter dekt dan --jaren. ensure_candles geeft een bestaande cache terug zonder naar de jaren te
    kijken (de galerij vult hem met 1 jaar), dus zonder deze controle rekent een lab-run met 3 jaar stil op 1 jaar, en --alleen-volledig laat dan
    precies de coins vallen met de kortste cache."""
    short = [w for tf in ("15m", "1h", "4h") if len(frames[tf]) and (w := coverage_warning(tf, frames[tf]["timestamp"].iloc[0], frames[tf]["timestamp"].iloc[-1], jaren))]
    if short:
        sys.exit(f"{coin}: {'; '.join(short)}. De cache in data/candles/ is korter dan --jaren {jaren:g}: haal hem opnieuw op met refresh "
                 f"(docs/onderzoek/range-sweep/vps-protocol.md, stap 4) of kies minder --jaren.")


def select_variants(familie: str):
    if familie == "kanteling":
        return tuple(v for v in tl.VARIANTS if v.family == "kanteling")
    if familie == "standaard":
        return tuple(v for v in tl.VARIANTS if v.family != "kanteling")
    return tl.VARIANTS


def needed_timeframes(variants) -> list[str]:
    """Alleen de timeframes die de gekozen varianten gebruiken (plus 4u voor het trendfilter), zodat een kanteling-run geen 4u of 5m onnodig ophaalt."""
    need = {v.timeframe for v in variants} | {"4h" for v in variants if v.htf}
    return [tf for tf in ("5m", "15m", "1h", "4h") if tf in need]


def load_coin(coin: str, timeframes, jaren: float) -> dict[str, pd.DataFrame]:
    tfs = {}
    for tf in timeframes:
        try:
            tfs[tf] = candle_cache.ensure_candles(coin, jaren, timeframe=tf)
        except Exception as exc:
            print(f"{coin} {tf}: geen candles ({exc})", flush=True)
    print(f"{coin}: " + ", ".join(f"{len(tfs[tf])} candles van {tf}" for tf in tfs), flush=True)
    return tfs


BEGIN, END = "<!-- resultaten:begin -->", "<!-- resultaten:end -->"
PART_VERSION = 1


def write_between_markers(text: str, block: str) -> str:
    if BEGIN not in text or END not in text:
        raise ValueError(f"markers {BEGIN} en {END} ontbreken")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{block}\n{END}{tail}"


def check_rangesweep_costs(kosten: float, opslaan: bool) -> None:
    if opslaan and kosten < rl.LAB_COST_PCT:
        sys.exit(f"--opslaan voor rangesweep vraagt --kosten {rl.LAB_COST_PCT} of hoger (gekozen {kosten})")


def check_rangesweep_verdict(choice, opslaan: bool) -> None:
    """Opslaan mag alleen bij een geslaagde toets op stopkwaliteit (poort 3, S2): bij geen keuze blijft de database zoals hij was."""
    if opslaan and choice is None:
        sys.exit("--opslaan geweigerd: geen enkele toets slaagde op stopkwaliteit (S2), er is niets opgeslagen")


def coin_part_paths(outdir: Path, coin: str) -> tuple[Path, Path]:
    """Tussenresultaat per coin: een onderbroken run op de VPS gaat verder bij de volgende coin in plaats van opnieuw te beginnen."""
    return outdir / f"{coin}_rows.pkl", outdir / f"{coin}_placebo.pkl"


def _atomic_write(path: Path, data: bytes) -> None:
    """Via een tijdelijk bestand en os.replace: een run die midden in een schrijfactie stopt laat nooit een half bestand als tussenresultaat achter."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _check_part_settings(outdir: Path, a) -> None:
    """Tussenresultaten gelden alleen voor dezelfde kosten, jaren en varianten; anders zou een hervatte run oude en nieuwe coins stil mengen."""
    want = {"versie": PART_VERSION, "kosten": a.kosten, "jaren": a.jaren, "varianten": [v.name for v in rl.VARIANTS]}
    meta = outdir / "instellingen.json"
    if meta.exists():
        if json.loads(meta.read_text(encoding="utf-8")) != want:
            sys.exit(f"{outdir} bevat tussenresultaten van andere instellingen (kosten, jaren of varianten); kies een andere map of verwijder deze")
    else:
        _atomic_write(meta, json.dumps(want).encode("utf-8"))


def _load_part(paths: tuple[Path, Path]):
    """None als een van de twee bestanden ontbreekt of niet te lezen is: die coin wordt dan opnieuw gerekend."""
    try:
        if paths[0].exists() and paths[1].exists():
            rows = pickle.loads(paths[0].read_bytes())
            plac, cspan = pickle.loads(paths[1].read_bytes())
            return rows, plac, cspan
    except Exception as exc:
        print(f"tussenresultaat {paths[0].name} onleesbaar ({exc}), opnieuw gerekend", flush=True)
    return None


def _save_part(paths: tuple[Path, Path], rows, plac, cspan) -> None:
    # Eerst de placebo, dan de rijen: alleen als allebei er zijn geldt de coin als klaar, ook als de run tussen de twee schrijfacties stopt.
    _atomic_write(paths[1], pickle.dumps((plac, cspan)))
    _atomic_write(paths[0], pickle.dumps(rows))


def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def render_rangesweep(results, meta: dict) -> str:
    n_tests = sum(len(v.stops) for v, _ in results)
    lines = [f"Run: {meta['first']} tot {meta['last']}, {meta['coins']} coins, kosten {meta['kosten']}% per rondreis, {meta['jaren']} jaar.",
             f"{n_tests} toetsen in deze familie, {rl.TESTED_TOTAL} in het register sinds het begin; horde voor een voordeel t \u2265 {rl.EDGE_T_MIN}.", "",
             "### Stopkwaliteit (de kop)", "",
             "| Variant | Stop | Setups | Gevuld | Stop % | Kosten R | Stop geraakt | +1R vóór de stop | +2R | +3R | +6R | Te krap | Tegen willekeurig | Oordeel |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    passed = 0
    for v, r in results:
        for name in v.stops:
            s, q = r[name]["summary"], r[name]["quality"]
            if not s.get("n"):
                lines.append(f"| {v.name} | {name} | {s.get('setups', 0)} | 0 | - | - | - | - | - | - | - | - | - | geen vullingen |")
                continue
            passed += bool(q["passes"])
            ci = s["reach"][1]["ci"]
            lines.append(f"| {v.name} | {name} | {s['setups']} | {s['n']} | {s['median_stop_pct']:.2f}% | {s['median_cost_r']:.3f} | {_pct(s['stop_hit']['p'])} | "
                         f"{_pct(s['reach'][1]['p'])} ({ci[0] * 100:.0f} tot {ci[1] * 100:.0f}%) | {_pct(s['reach'][2]['p'])} | {_pct(s['reach'][3]['p'])} | "
                         f"{_pct(s['reach'][6]['p'])} | {_pct(s['tight_rate'])} | {q['placebo_diff'] * 100:+.1f} pp | {'SLAAGT' if q['passes'] else q['reason']} |")
    lines += ["", f"{passed} van {n_tests} toetsen slagen op stopkwaliteit." + (" Stopcriterium S2: geen enkele toets slaagt." if not passed else ""), "",
              "### Netto R bij de referentie-uitgangen (ernaast, nooit de kop)", "",
              "| Variant | Stop | Midden | Overkant | Meelopend (3 ATR 1u) | t per week | Strenge toets |", "|---|---|---|---|---|---|---|"]
    for v, r in results:
        for name in v.stops:
            s, e = r[name]["summary"], r[name]["edge"]
            if not s.get("n"):
                continue
            ref = lambda k: "-" if s["ref"][k]["avg_net"] is None else f"{s['ref'][k]['avg_net']:+.3f}"
            lines.append(f"| {v.name} | {name} | {ref('mid')} | {ref('opp')} | {ref('trail')} | {e.get('t_week', 0):.2f} | {'SLAAGT' if e.get('passes') else e.get('reason', '')} |")
    lines += ["", "### Score per graad (beschrijvend, geen poort)", "", "| Variant | Stop | Graad | n | +1R vóór de stop | Stop geraakt |", "|---|---|---|---|---|---|"]
    for v, r in results:
        for name in v.stops:
            for g, x in sorted(r[name]["summary"].get("by_grade", {}).items()):
                lines.append(f"| {v.name} | {name} | {g} | {x['n']} | {_pct(x['reach1'])} | {_pct(x['stop_hit'])} |")
    lines += ["", "Ter vergelijking, stop op de buitenkant van de zone zonder buffer (geen toets):", ""]
    for v, r in results:
        w = r[rs.DESCRIPTIVE_STOP]["summary"]
        if w.get("n"):
            lines.append(f"- {v.name}: {w['n']} gevuld, stop geraakt {_pct(w['stop_hit']['p'])}, te krap {_pct(w['tight_rate'])}, kosten {w['median_cost_r']:.3f}R")
    return "\n".join(lines)


def save_rangesweep(results, live_choice, now_iso: str) -> int:
    db.init_db()
    saved = 0
    for v, r in results:
        best = max(v.stops, key=lambda n: r[n]["summary"].get("n", 0))
        e = r[best]["edge"]
        repo.set_rule_lab(v.name.lower(), bool(e.get("passes")), {"stop_name": best, "n": e.get("n"), "avg": e.get("avg"), "t_week": e.get("t_week"),
                                                                  "quality_passes": bool(r[best]["quality"]["passes"])}, now_iso)
        saved += 1
    if live_choice is None:
        repo.set_rule_lab("range_sweep_stop", False, {"variant": None, "reason": "geen toets slaagde op stopkwaliteit"}, now_iso)
        repo.set_rule_lab("range_sweep", False, {"variant": None}, now_iso)
        return saved + 2
    v, name = live_choice
    cell = next(r for vv, r in results if vv == v)[name]
    repo.set_rule_lab("range_sweep_stop", True, {"variant": v.name, "stop_name": name, "quality": cell["quality"], "summary": cell["summary"],
                                                 "doelkans": cell["doelkans"]}, now_iso)
    repo.set_rule_lab("range_sweep", bool(cell["edge"].get("passes")), {"variant": v.name, "stop_name": name, **{k: cell["edge"].get(k) for k in ("n", "avg", "t_week", "reason")}}, now_iso)
    return saved + 2


def _run_one_coin(coin: str, a, ensure, positioning_fn) -> tuple[dict, dict, list]:
    try:
        frames = rl.load_frames(coin, a.jaren, ensure)
    except Exception as exc:
        print(f"{coin}: geen candles ({exc})", flush=True)
        return {}, {}, []
    if any(frames[tf].empty for tf in ("15m", "1h", "4h")):
        print(f"{coin}: te weinig candles", flush=True)
        return {}, {}, []
    check_coverage(coin, frames, a.jaren)
    span = [frames["15m"]["timestamp"].iloc[0], frames["15m"]["timestamp"].iloc[-1]]
    metrics = None
    try:
        metrics, _ = positioning_fn(coin, span[0], span[1])
        print(f"{coin}: OI vanaf {metrics['timestamp'].iloc[0]:%Y-%m-%d}" if len(metrics) else f"{coin}: geen OI", flush=True)
    except Exception as exc:
        print(f"{coin}: geen OI ({exc})", flush=True)
    cache, rows, plac = {}, {}, {}
    for v in rl.VARIANTS:
        r = rl.run_coin(v, coin, frames, a.kosten, cache, metrics if v.oi_flush else None)
        rows[v.name] = r
        filled = r[r["filled"].astype(bool)] if len(r) else r
        plac[v.name] = rl.placebo_by_stop(v, frames, cache, filled, a.kosten)
        print(f"{coin} {v.name}: {len(r)} rijen", flush=True)
    return rows, plac, span


def run_rangesweep(a, ensure=candle_cache.ensure_candles, positioning_fn=positioning.ensure_positioning) -> None:
    """`ensure` en `positioning_fn` zijn de naad voor de tests: kunstmatige candles zonder beurs."""
    check_rangesweep_costs(a.kosten, a.opslaan)
    report = Path(a.rapport) if a.rapport else None
    if report:
        try:  # faalt nu, niet pas na 40 minuten rekenen
            write_between_markers(report.read_text(encoding="utf-8"), "")
        except (ValueError, OSError) as exc:
            sys.exit(f"--rapport {report}: {exc}")
    coins = a.coins.split(",")
    if a.alleen_volledig:
        full = {c: ensure(c, a.jaren, timeframe="15m") for c in coins}
        for c, df in full.items():
            if len(df):
                check_coverage(c, {"15m": df, "1h": df, "4h": df}, a.jaren)
        firsts = {c: df.head(1) for c, df in full.items()}
        coins = [c for c in coins if c in set(tl.full_history(firsts))]
        print(f"{len(coins)} coins met volle historie", flush=True)
    outdir = Path(a.hervat) if a.hervat else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
        _check_part_settings(outdir, a)
    all_rows = {v.name: [] for v in rl.VARIANTS}
    all_plac = {v.name: {n: [] for n in v.stops} for v in rl.VARIANTS}
    span = []
    for coin in coins:
        paths = coin_part_paths(outdir, coin) if outdir else None
        part = _load_part(paths) if paths else None
        if part:
            rows, plac, cspan = part
            print(f"{coin}: uit {paths[0]}", flush=True)
        else:
            rows, plac, cspan = _run_one_coin(coin, a, ensure, positioning_fn)
            if paths and cspan:
                _save_part(paths, rows, plac, cspan)
        span += cspan
        for v in rl.VARIANTS:
            if len(rows.get(v.name, [])):
                all_rows[v.name].append(rows[v.name])
            for n in v.stops:
                p = plac.get(v.name, {}).get(n)
                if p is not None and len(p):
                    all_plac[v.name][n].append(p)
    results = []
    for v in rl.VARIANTS:
        r = pd.concat(all_rows[v.name], ignore_index=True) if all_rows[v.name] else pd.DataFrame(columns=["stop_name", "filled", "at", "cancel"])
        results.append((v, rl.judge(r, {n: pd.concat(p, ignore_index=True) if p else pd.DataFrame() for n, p in all_plac[v.name].items()}, v)))
    meta = {"kosten": a.kosten, "jaren": a.jaren, "coins": len(span) // 2, "first": f"{min(span):%Y-%m-%d}" if span else "-",
            "last": f"{max(span):%Y-%m-%d}" if span else "-"}
    print(f"\n{len(rl.VARIANTS)} varianten, {sum(len(v.stops) for v in rl.VARIANTS)} toetsen; samen met eerder bekeken varianten {rl.TESTED_TOTAL} in het register: een toevallige treffer is dan normaal.")
    md = render_rangesweep(results, meta)
    print(md)
    choice = rl.select_live(results)
    print(f"\nGekozen voor de proef: {choice[0].name} met stop {choice[1]}" if choice else "\nGeen variant gekozen voor de proef (S2).")
    if report:
        report.write_text(write_between_markers(report.read_text(encoding="utf-8"), md), encoding="utf-8")
        print(f"Rapport geschreven naar {report}")
    check_rangesweep_verdict(choice, a.opslaan)
    if a.opslaan:
        print(f"{save_rangesweep(results, choice, datetime.now(timezone.utc).isoformat())} regels opgeslagen.")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=LAB_COINS)
    ap.add_argument("--jaren", type=float, default=3.0)
    ap.add_argument("--kosten", type=float, default=config.TRACK_RECORD_COST_PCT)
    ap.add_argument("--familie", choices=("alle", "kanteling", "standaard", "rangesweep"), default="alle",
                    help="welke varianten: alle (trendlab), alleen de kanteling, alleen de oudere, of de range sweep-familie")
    ap.add_argument("--alleen-volledig", action="store_true", help="alleen coins met candles over de volle periode (overlevingscontrole)")
    ap.add_argument("--opslaan", action="store_true", help="bewaar de uitkomst per regel in de database; zonder deze vlag schrijft het script niets")
    ap.add_argument("--rapport", help="rangesweep: schrijf de uitkomst tussen de markers van dit markdownbestand")
    ap.add_argument("--hervat", help="rangesweep: map voor tussenresultaten per coin; een tweede run slaat klare coins over")
    return ap


def main() -> None:
    a = build_parser().parse_args()
    if a.familie == "rangesweep":
        return run_rangesweep(a)
    variants = select_variants(a.familie)
    timeframes = needed_timeframes(variants)
    coins = a.coins.split(",")

    # Coin voor coin: 5m over drie jaar is ~315k candles per coin, alle coins tegelijk in het geheugen past niet op de 4 GB van de VPS.
    keep: dict[str, list[str]] = {}
    if a.alleen_volledig:
        firsts: dict[str, dict[str, pd.DataFrame]] = {tf: {} for tf in timeframes}
        for coin in coins:
            for tf, df in load_coin(coin, timeframes, a.jaren).items():
                firsts[tf][coin] = df.head(1)
        for tf in timeframes:
            keep[tf] = tl.full_history(firsts[tf])
            print(f"{tf}: {len(keep[tf])} coins met volle historie", flush=True)

    span: dict[str, list] = {}
    parts: dict[str, list] = {v.name: [] for v in variants}
    plac: dict[str, list] = {v.name: [] for v in variants}
    for coin in coins:
        tfs = load_coin(coin, timeframes, a.jaren)
        for tf, df in tfs.items():
            if len(df):
                lo_hi = span.setdefault(tf, [df["timestamp"].iloc[0], df["timestamp"].iloc[-1]])
                lo_hi[0], lo_hi[1] = min(lo_hi[0], df["timestamp"].iloc[0]), max(lo_hi[1], df["timestamp"].iloc[-1])
        for v in variants:
            if a.alleen_volledig and coin not in keep[v.timeframe]:
                continue
            bars = tfs.get(v.timeframe)
            if bars is None or len(bars) < tl.WARMUP + 50:
                continue
            htf_bars = tfs.get("4h") if v.htf else None
            if v.htf and (htf_bars is None or len(htf_bars) == 0):
                continue
            real = tl.run_variant(v, bars, a.kosten, htf_bars=htf_bars)
            if real.empty:
                continue
            real["coin"] = coin
            parts[v.name].append(real)
            plac[v.name].append(tl.placebo_variant(v, bars, real, a.kosten, htf_bars=htf_bars))
        del tfs

    for tf, (first, last) in span.items():
        print(f"{tf}: candles van {first:%Y-%m-%d} tot {last:%Y-%m-%d}", flush=True)
        warn = coverage_warning(tf, first, last, a.jaren)
        if warn:
            print(warn, flush=True)

    results = []
    for v in variants:
        trades = pd.concat(parts[v.name], ignore_index=True) if parts[v.name] else pd.DataFrame()
        placebo = pd.concat(plac[v.name], ignore_index=True) if plac[v.name] else pd.DataFrame()
        results.append((v, tl.evaluate(trades, placebo)))

    print(f"\n{len(results)} varianten getoetst; bij zoveel toetsen is een toevallige treffer normaal.")
    print(f"Kosten {a.kosten}% per rondreis, {a.jaren} jaar, {len(coins)} coins\n")
    print(f"{'variant':<15}{'n':>6}{'win':>5}{'stop%':>7}{'bruto':>8}{'netto':>8}  {'95%-marge':<17}{'eerste':>8}{'tweede':>8}{'willek.':>9}  oordeel")
    for v, r in results:
        if not r.get("n"):
            print(f"{v.name:<15}  geen trades")
            continue
        ci = f"{r['ci'][0]:+.2f} tot {r['ci'][1]:+.2f}"
        tr, te = r["train"][1], r["test"][1]
        pl = r["placebo"]
        print(f"{v.name:<15}{r['n']:>6}{r['winrate'] * 100:>4.0f}%{r['median_risk_pct']:>7.1f}{r['gross']:>+8.2f}{r['avg']:>+8.2f}  {ci:<17}"
              f"{(f'{tr:+.2f}' if tr is not None else '-'):>8}{(f'{te:+.2f}' if te is not None else '-'):>8}{(f'{pl:+.2f}' if pl is not None else '-'):>9}  "
              f"{'SLAAGT' if r['passes'] else r['reason']}")
    best = [(v, r) for v, r in results if r.get("n") and r["passes"]]
    print(f"\n{len(best)} van {len(results)} varianten slagen. Bij {len(results)} toetsen is een toevallige treffer normaal: één geslaagde variant is nog geen bewijs.")
    for v, r in best:
        print(f"  {v.name}: gemiddelde winnaar {r['avg_win']:+.1f}R, beste trade {r['best']:+.1f}R. Controleer of dit niet aan één coin of één maand hangt.")

    if a.opslaan:
        print(f"\n{save_results(results, datetime.now(timezone.utc).isoformat())} regels opgeslagen in de database.")


if __name__ == "__main__":
    main()
