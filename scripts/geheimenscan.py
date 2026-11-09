"""Pre-commit controle op geheimen. `python3 scripts/geheimenscan.py` leest de gestagede wijzigingen (alleen toegevoegde regels);
`--alles` leest elk gevolgd bestand. Afsluitcode 1 bij een vondst. Toont nooit de waarde zelf."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import secret_scan  # noqa: E402


# Hulpscripts van skills (derde partij) bevatten woorden als 'token' zonder een geheim; de bestandsnaamcontrole blijft wel gelden.
SKIP_CONTENT = (".claude/skills/",)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def staged_findings() -> list[str]:
    found = []
    for path in _git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines():
        if secret_scan.forbidden_file(path):
            found.append(f"{path}: dit bestand hoort niet in git")
    diff = _git("diff", "--cached", "--unified=0", "--no-color")
    path = None
    line_no = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
        elif raw.startswith("@@"):
            line_no = int(raw.split("+")[1].split(",")[0].split(" ")[0]) - 1
        elif raw.startswith("+") and not raw.startswith("+++"):
            line_no += 1
            if path and path.startswith(SKIP_CONTENT):
                continue
            for _, name in secret_scan.scan_text(raw[1:]):
                found.append(f"{path}:{line_no}: {name}")
    return found


def all_findings() -> list[str]:
    found = []
    for path in _git("ls-files").splitlines():
        if secret_scan.forbidden_file(path):
            found.append(f"{path}: dit bestand hoort niet in git")
            continue
        if path.startswith(SKIP_CONTENT):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        found += [f"{path}:{n}: {name}" for n, name in secret_scan.scan_text(text)]
    return found


def main() -> int:
    found = all_findings() if "--alles" in sys.argv else staged_findings()
    if not found:
        return 0
    print("Geheimenscan: commit gestopt. Mogelijk geheim op:", file=sys.stderr)
    for f in found:
        print("  " + f, file=sys.stderr)
    print("Is het geen geheim? Zet '# geheimscan:ok' op die regel. Is het wel een geheim? Haal het uit git en draai de sleutel rond.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
