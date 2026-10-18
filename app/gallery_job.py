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


PLACEHOLDER = "<p>klopt / klopt niet: ______</p>"
_BUTTONS = '<div class="oordeel"><button type="button" data-v="ja">Klopt</button><button type="button" data-v="nee">Klopt niet</button></div>'
_STYLE = ("<style>.oordeel{display:flex;gap:10px;margin:8px 0}.oordeel button{flex:1;min-height:44px;font:inherit;font-weight:600;border-radius:10px;"
          "border:1px solid var(--border,#2a3b3d);background:transparent;color:inherit}.oordeel button.is-on[data-v=ja]{background:#0abab5;color:#041a1a;border-color:#0abab5}"
          ".oordeel button.is-on[data-v=nee]{background:#e5534b;color:#fff;border-color:#e5534b}#oordeel-bar{position:sticky;bottom:0;padding:10px 0;"
          "background:var(--bg,#0b1415);border-top:1px solid var(--border,#2a3b3d);font-size:14px}#oordeel-bar button{margin-left:8px;min-height:40px;font:inherit}</style>")
_SCRIPT = r"""<div id=oordeel-bar><span id=oordeel-tel></span><button type=button id=oordeel-kopie>Kopieer uitslag</button></div><script>
(function () {
  var key = "galerij:" + KIND, saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) {}
  var cards = Array.prototype.slice.call(document.querySelectorAll("section")).filter(function (s) { return s.querySelector(".oordeel"); });
  function paint() {
    var ja = 0, nee = 0;
    cards.forEach(function (c, i) {
      var v = saved[i];
      if (v === "ja") ja++; if (v === "nee") nee++;
      c.querySelectorAll(".oordeel button").forEach(function (b) { b.classList.toggle("is-on", b.getAttribute("data-v") === v); });
    });
    document.getElementById("oordeel-tel").textContent = "Klopt " + ja + " · Klopt niet " + nee + " · Open " + (cards.length - ja - nee) + " van " + cards.length;
  }
  cards.forEach(function (c, i) {
    c.querySelectorAll(".oordeel button").forEach(function (b) {
      b.addEventListener("click", function () {
        saved[i] = b.getAttribute("data-v");
        try { localStorage.setItem(key, JSON.stringify(saved)); } catch (e) {}
        paint();
      });
    });
  });
  document.getElementById("oordeel-kopie").addEventListener("click", function () {
    var lines = cards.map(function (c, i) { return (saved[i] === "ja" ? "klopt" : saved[i] === "nee" ? "KLOPT NIET" : "open") + ": " + c.querySelector("h2").textContent; });
    var text = KIND + "\n" + lines.join("\n");
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).catch(function () { window.prompt("Kopieer", text); });
    else window.prompt("Kopieer", text);
  });
  paint();
})();
</script>"""


def decorate(html: str, kind: str) -> str:
    """Maakt van de statische kaarten een pagina waar je per kaart Klopt of Klopt niet aantikt (bewaard in de browser) met een telling."""
    html = html.replace(PLACEHOLDER, _BUTTONS)
    script = _SCRIPT.replace("KIND", repr(kind))
    return html.replace("</body>", _STYLE + script + "</body>") if "</body>" in html else html + _STYLE + script
