"""Zoekt geheimen in tekst (sleutels, tokens, wallet-geheimen) voor ze in git komen. Zuiver: geen bestandstoegang, geen netwerk.
Bewust grof: een valse melding kost een regel '# geheimscan:ok' op de plek, een gemist geheim kost een wallet of een account."""
import re

MARKER = "geheimscan:ok"
PLACEHOLDER = re.compile(r"(?i)change|test|fake|verify|example|dummy|placeholder|your|xxx|secret_?value|<")

# (naam, patroon). Elk patroon zoekt één regel; de waarde wordt nooit teruggegeven, alleen de naam en het regelnummer.
PATTERNS = [
    ("privésleutel (PEM)", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Anthropic-sleutel", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI-sleutel", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("Telegram-bottoken", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("Discord-token", re.compile(r"\b[MNO][A-Za-z0-9_\-]{23,25}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}\b")),
    ("GitHub-token", re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{30,}")),
    # Een Solana-geheim is 64 bytes: 86 tot 88 tekens base58, of een JSON-lijst van 64 getallen. Een adres (32 tot 44 tekens) is openbaar.
    ("Solana-geheim (base58)", re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{86,88}(?![1-9A-HJ-NP-Za-km-z])")),
    ("Solana-geheim (lijst van 64 bytes)", re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]")),
    # Naam met SECRET, TOKEN, PASSWORD of KEY die een lange letterlijke waarde krijgt (geen verwijzing naar een omgevingsvariabele).
    ("toegewezen geheim", re.compile(r"""(?i)\b[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY)[A-Z0-9_]*\s*[=:]\s*["']?(?![\w+/\-]*\()(?P<v>[A-Za-z0-9+/_\-]{12,})""")),
]

# Bestanden die nooit in git horen.
FORBIDDEN_FILES = re.compile(r"(^|/)(\.env(\.[^/]*)?|id_[a-z0-9]+|[^/]*\.pem|[^/]*\.key|[^/]*keypair[^/]*\.json)$")
ALLOWED_FILES = re.compile(r"(^|/)\.env\.example$")


def scan_text(text: str) -> list[tuple[int, str]]:
    """[(regelnummer, naam van het patroon)] voor elke regel met een vermoedelijk geheim. Een regel met MARKER telt niet."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if MARKER in line:
            continue
        for name, rx in PATTERNS:
            m = rx.search(line)
            if m and not (m.groupdict().get("v") and PLACEHOLDER.search(m.group("v"))):
                out.append((n, name))
                break
    return out


def forbidden_file(path: str) -> bool:
    return bool(FORBIDDEN_FILES.search(path)) and not ALLOWED_FILES.search(path)
