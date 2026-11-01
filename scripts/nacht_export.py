"""Nachtelijke export voor de automatische verbeterlus: draait de auto-missers (scripts/auto_misser.py) en de lekken (app/leaks.py) en schrijft één
JSON en een korte Markdown-samenvatting naar data/export/ met de datum in de naam.

  .venv/bin/python3 scripts/nacht_export.py [--map data/export] [--git] [--zonder-missers]

--git kopieert alleen die twee bestanden naar een aparte kloon (data/export-git/) en pusht die naar de tak hespulse-data van HESPULSE_DATA_REMOTE,
met de deploy key HESPULSE_DATA_KEY. Een andere tak of een ander bestand weigert het script.

Wat erin staat: marktdata en geaggregeerde uitkomsten per signaal (coin, richting, niveaus, uitkomst, R, MAE/MFE), per soort de lekken, de
auto-missers en de schaduwvarianten. Wat er nooit in staat: gebruikers (namen, e-mail, chat-id's, instellingen), journaal, push-abonnementen,
meldingen per gebruiker, secrets of .env-waarden."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app import auto_misser as am, config, db, excursion, focus, leaks, repo, shadow, track_record  # noqa: E402

EXPORT_DIR = ROOT / "data" / "export"
GIT_DIR = ROOT / "data" / "export-git"
BRANCH = "hespulse-data"
DAYS = max(leaks.WINDOWS)
FILE_RE = re.compile(r"^hespulse-\d{4}-\d{2}-\d{2}\.(json|md)$")
# Alleen deze velden van een signaal gaan mee: markt, niveaus en uitkomst. Tekstvelden (reason, uitleg) blijven thuis.
SIGNAL_FIELDS = ("id", "trade_type", "coin", "direction", "created_at", "price", "stop_loss", "take_profit", "auto_outcome", "auto_outcome_at",
                 "auto_outcome_note", "pass_pct", "candle_market", "mae_r", "mfe_r", "funding_r", "funding_status")


def _stop_fetch(coin: str, since_ms: int):
    from app import exchange
    return exchange.fetch_ohlcv(coin, timeframe="5m", limit=300, since=since_ms)


def stop_then_target(signals: list[dict], now: datetime, fetch: Callable = _stop_fetch) -> dict:
    """Per stop met een doel waarvan de 24 uur voorbij zijn: haalde de koers daarna alsnog het doel (excursion.target_reached)? Een fout of geen
    candles: niet gemeten (geen sleutel), nooit 'nee'."""
    out = {}
    for s in signals:
        if s.get("auto_outcome") != "stop_loss" or s.get("take_profit") is None or s.get("r_override") is not None or not s.get("auto_outcome_at"):
            continue
        closed = excursion._ts(s["auto_outcome_at"])
        if closed + excursion.AFTER_STOP > now:
            continue
        try:
            candles = fetch(s["coin"], int(closed.timestamp() * 1000))
        except Exception:
            continue
        finally:
            if fetch is _stop_fetch:
                time.sleep(0.1)                     # zacht voor de beurs
        if candles is None or not len(candles):
            continue
        after = candles[(candles["timestamp"] > closed) & (candles["timestamp"] <= closed + excursion.AFTER_STOP)]
        if len(after):
            out[s["id"]] = excursion.target_reached(s["direction"], s["take_profit"], after)
    return out


def _signal_row(s: dict) -> dict:
    row = {k: s.get(k) for k in SIGNAL_FIELDS}
    row["r_bruto"] = track_record.signal_r(s)
    row["r_netto"] = track_record.net_signal_r(s, config.TRACK_RECORD_COST_PCT)
    return row


def build_export(now: datetime, stop_fetch: Callable = _stop_fetch) -> dict:
    since = (now - timedelta(days=DAYS)).isoformat()
    inputs = repo.leak_inputs(since)
    focus_types = set().union(*leaks.TYPES.values())
    signals = [s for s in inputs["signals"] if s["trade_type"] in focus_types]
    inputs["stop_then_target"] = stop_then_target(signals, now, stop_fetch)
    return {
        "versie": 1,
        "gemaakt": now.isoformat(),
        "instellingen": {"coins": list(config.FIXED_COINS), "kosten_pct_rondreis": config.TRACK_RECORD_COST_PCT, "focus": list(focus.FOCUS_TYPES),
                         "auto_misser": {"pivot_candles": am.PIVOT_BARS, "min_atr": am.MIN_MOVE_ATR, "max_uren": am.MAX_MOVE_HOURS,
                                         "gezien_venster_uren": am.SEEN_WINDOW.total_seconds() / 3600}},
        "lekken": leaks.report(inputs, now),
        "auto_missers": [{k: m[k] for k in ("coin", "direction", "begin_at", "end_at", "begin_price", "end_price", "size_atr", "size_pct", "seen_by",
                                             "reasons")} for m in inputs["missers"]],
        "signalen": [_signal_row(s) for s in signals],
        "schaduw": shadow.export_rows(),
    }


def _r(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:+.2f}R".replace(".", ",")


def markdown(data: dict) -> str:
    lines = [f"# HesPulse nachtelijke export {data['gemaakt'][:10]}", "",
             "Meting, geen advies. Netto na kosten; R alleen uit doel of stop. Bron: JSON met dezelfde datum.", ""]
    for window in ("7d", "30d"):
        lines.append(f"## Laatste {window[:-1]} dagen")
        for kind, k in data["lekken"][window].items():
            ended = ", ".join(f"{s} {v['n']}" for s, v in k["vervallen"].items()) or "geen"
            top = max(k["missers"]["redenen"].items(), key=lambda kv: kv[1])[0] if k["missers"]["redenen"] else "-"
            lag = f"{k['vertraging']['median_s']:.0f} s" if k["vertraging"] and k["vertraging"]["median_s"] is not None else "-"
            lines.append(f"- {shadow.label(kind)}: {k['kaarten']} kaarten, {k['gevuld']} gevuld, {k['wachtend']} wachtend, vervallen: {ended}; "
                         f"{k['afgerond']} afgerond, netto {_r(k['netto_r'])} per trade; stop daarna toch doel {k['stop_dan_doel']['toch_doel']} van "
                         f"{k['stop_dan_doel']['gecontroleerd']}; dagcap {k['dagcap']}; vertraging mediaan {lag}; missers {k['missers']['n']} "
                         f"(meest: {top})")
        lines.append("")
    unseen = [m for m in data["auto_missers"] if not m["seen_by"]]
    lines.append(f"## Auto-missers ({len(data['auto_missers'])} bewegingen in {DAYS} dagen, {len(unseen)} door geen motor gezien)")
    for m in unseen[-10:]:
        lines.append(f"- {m['coin']} {m['direction']} {m['begin_at'][:16]}: {m['size_atr']:.1f} ATR ({m['size_pct']:.1f}%)".replace(".", ","))
    lines.append("")
    lines.append("## Schaduw")
    lines += [f"- {s['trade_type']} {s['id']} ({s['status']}): {s['verdict']['tekst']}" for s in data["schaduw"]] or ["- geen"]
    return "\n".join(lines) + "\n"


def write_files(data: dict, directory: Path, now: datetime) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"hespulse-{now:%Y-%m-%d}"
    js, md = directory / f"{stem}.json", directory / f"{stem}.md"
    js.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md.write_text(markdown(data), encoding="utf-8")
    return [js, md]


def _git(args: list[str], cwd: Path, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=check, capture_output=True, text=True)


def push_to_branch(files: list[Path], work: Path, remote: str, key: Optional[str], when: datetime) -> bool:
    """Kopieert de exportbestanden naar export/ in een aparte kloon van alleen de tak hespulse-data en pusht die. Geeft False als er niets nieuws
    was. Alleen bestanden met de naam hespulse-JJJJ-MM-DD.json/.md; de tak staat vast in BRANCH."""
    for f in files:
        if not FILE_RE.match(Path(f).name):
            raise ValueError(f"{f}: alleen exportbestanden (hespulse-JJJJ-MM-DD.json/.md) gaan naar {BRANCH}")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if key:
        # known_hosts naast de sleutel: de service-gebruiker heeft mogelijk geen schrijfbare home (adduser --system).
        hosts = Path(key).parent / "known_hosts"
        env["GIT_SSH_COMMAND"] = f"ssh -i {key} -o IdentitiesOnly=yes -o UserKnownHostsFile={hosts} -o StrictHostKeyChecking=accept-new"
    work.mkdir(parents=True, exist_ok=True)
    if not (work / ".git").exists():
        _git(["init", "-q"], work, env)
        _git(["remote", "add", "origin", remote], work, env)
    else:
        _git(["remote", "set-url", "origin", remote], work, env)
    fetched = _git(["fetch", "-q", "origin", BRANCH], work, env, check=False).returncode == 0
    if fetched:
        _git(["checkout", "-q", "-B", BRANCH, "FETCH_HEAD"], work, env)
    else:
        _git(["checkout", "-q", "--orphan", BRANCH], work, env, check=False)
    target = work / "export"
    target.mkdir(exist_ok=True)
    for f in files:
        shutil.copy2(f, target / Path(f).name)
    _git(["add", "export"], work, env)
    if _git(["diff", "--cached", "--quiet"], work, env, check=False).returncode == 0:
        return False
    _git(["-c", "user.name=HesPulse nacht", "-c", "user.email=hespulse-nacht@users.noreply.github.com", "commit", "-q", "-m",
          f"Nachtelijke export {when:%Y-%m-%d}"], work, env)
    _git(["push", "-q", "origin", f"HEAD:refs/heads/{BRANCH}"], work, env)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=str(EXPORT_DIR))
    ap.add_argument("--git", action="store_true", help=f"push de bestanden naar de tak {BRANCH}")
    ap.add_argument("--zonder-missers", action="store_true", help="sla het zoeken van nieuwe auto-missers over (alleen de opgeslagen)")
    a = ap.parse_args()
    db.init_db()
    now = datetime.now(timezone.utc)
    if not a.zonder_missers:
        import auto_misser as script
        t0 = time.monotonic()
        rows = script.run(list(config.FIXED_COINS), now, am.LOOKBACK_HOURS)
        print(f"Auto-missers: {len(rows)} bewegingen, {len(am.unseen(rows))} niet gezien ({time.monotonic() - t0:.0f} s)")
    files = write_files(build_export(now), Path(a.map), now)
    print("Geschreven: " + ", ".join(str(f) for f in files))
    if a.git:
        if not config.HESPULSE_DATA_REMOTE:
            sys.exit("HESPULSE_DATA_REMOTE staat niet in .env; zie README, Automatische verbeterlus")
        pushed = push_to_branch(files, GIT_DIR, config.HESPULSE_DATA_REMOTE, config.HESPULSE_DATA_KEY or None, now)
        print(f"Gepusht naar {BRANCH}" if pushed else "Niets nieuws om te pushen")


if __name__ == "__main__":
    main()
