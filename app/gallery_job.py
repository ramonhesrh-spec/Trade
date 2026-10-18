"""De keuring van de range sweep met het oog, vanuit de app (CEO). Genereert dezelfde kaarten als scripts/range_sweep_gallery.py in een
achtergronddraad, want het ophalen van candles duurt minuten, en bewaart de pagina's als bestand zodat een herstart ze niet kwijtraakt."""
import logging
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(config.DATABASE_PATH).parent / "galerij"
CSV = ROOT / "docs" / "onderzoek" / "range-sweep" / "handtrades.csv"
KINDS = {"voorbeelden": "Jouw voorbeelden", "willekeurig": "30 willekeurige setups"}
_state: dict = {k: {"busy": False, "error": None} for k in KINDS}
_lock = threading.Lock()


def path_of(kind: str) -> Path:
    return OUT_DIR / f"{kind}.html"


def status(kind: str) -> dict:
    p = path_of(kind)
    made = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) if p.exists() else None
    return {**_state[kind], "ready": p.exists(), "made_at": made}


def _build(kind: str) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    import misser_check
    import range_sweep_gallery as gal
    if kind == "voorbeelden":
        cards = gal.from_csv(str(CSV), lambda coin, at: misser_check.fetch_rangesweep(coin, at))
    else:
        cards = gal.random_cards(["BTC", "ETH", "SOL", "ARB", "APT", "AAVE"], 30, 3.0)
    return gal.page(cards)


def _run(kind: str) -> None:
    try:
        html = _build(kind)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path_of(kind).write_text(html, encoding="utf-8")
        _state[kind]["error"] = None
    except Exception as exc:
        logger.exception("Galerij %s is mislukt", kind)
        _state[kind]["error"] = str(exc)[:300]
    finally:
        _state[kind]["busy"] = False


def start(kind: str) -> bool:
    """Start het maken in een draad. False als hij al bezig is of de soort onbekend is."""
    if kind not in KINDS:
        return False
    with _lock:
        if _state[kind]["busy"]:
            return False
        _state[kind]["busy"] = True
    threading.Thread(target=_run, args=(kind,), daemon=True).start()
    return True
