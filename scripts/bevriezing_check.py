"""Bewaakt de bevriezing van het HesPulse-model (taak 02, B-2026-11-03-09/-10): welke commits sinds een datum raken de instapregels?
Alleen lezen: het script draait `git log` en schrijft niets. Een commit in de lijst is een regelwijziging tijdens de bevriezing, tenzij de
CEO die vooraf besloot (zie docs/onderzoek/besluiten.md).

    python3 scripts/bevriezing_check.py                       # sinds 2026-11-03
    python3 scripts/bevriezing_check.py --sinds 2026-11-10

Afsluitcode 0: geen commits. Afsluitcode 1: minstens één commit."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SINCE = "2026-11-03"
WATCHED = ["app/model.py", "app/model_live.py", "app/structure_levels.py", "app/htf_zones.py"]
_SEP = "\x1f"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def is_shallow(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def commits_since(repo: Path, since: str, paths=WATCHED) -> list:
    """Commits na `since` (datum van de commit) die een van `paths` raken, nieuwste eerst: [{hash, date, subject, files}]."""
    # Git vult een kale datum aan met het kloktijdstip van nu; zonder dit vallen commits eerder op die dag weg.
    if len(since) == 10:
        since += "T00:00:00+00:00"
    out = _git(repo, "log", f"--since={since}", f"--format=%x1e%h{_SEP}%cI{_SEP}%s", "--name-only", "--", *paths)
    result = []
    for block in out.split("\x1e"):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        h, date, subject = lines[0].split(_SEP, 2)
        result.append({"hash": h, "date": date, "subject": subject, "files": [f for f in lines[1:] if f in paths]})
    return result


def render(commits: list, since: str, shallow: bool = False) -> str:
    lines = [f"Bevriezing: commits sinds {since} op {', '.join(WATCHED)}"]
    if shallow:
        lines.append("Let op: dit is een ondiepe kloon. De geschiedenis is onvolledig, dus een lege lijst bewijst niets.")
    if not commits:
        lines.append("Geen commits.")
    for c in commits:
        lines.append(f"{c['hash']}  {c['date']}  {c['subject']}")
        lines.append(f"    {', '.join(c['files'])}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sinds", default=DEFAULT_SINCE, help="datum, standaard 2026-11-03")
    ap.add_argument("--repo", default=str(ROOT), help="pad naar de git-repository")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    commits = commits_since(repo, args.sinds)
    print(render(commits, args.sinds, is_shallow(repo)))
    return 1 if commits else 0


if __name__ == "__main__":
    sys.exit(main())
