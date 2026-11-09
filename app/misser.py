"""Zuivere logica voor de misser-controle op een lijst handtrades: de CSV lezen en de uitkomsten samenvatten. Geen netwerk, geen drempels."""
import csv
import io
import re
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
COLUMNS = ["coin", "richting", "tijd", "instap", "stop", "doel", "uitkomst"]
OPTIONAL = ["bron", "notitie", "tf"]
TIMEFRAMES = ("", "30m", "1h", "2h", "4h")
_PRICE = re.compile(r"\d+(?:[.,]\d+)?")


def _number(raw: str) -> float:
    return float(raw.strip().replace(",", "."))


def _maybe_number(raw: str):
    """Leeg veld: None. Voorbeelden uit de community hebben vaak alleen een instap; een verzonnen stop zou de misser-controle vervuilen."""
    return None if not raw.strip() else _number(raw)


def _local_to_utc(raw: str) -> datetime:
    naive = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M")
    local = naive.replace(tzinfo=LOCAL_TZ, fold=0)             # dubbel uur bij het terugzetten van de klok: de eerste keer
    utc = local.astimezone(timezone.utc)
    if utc.astimezone(LOCAL_TZ).replace(tzinfo=None) != naive:  # uur dat bij het vooruitzetten van de klok niet bestaat
        raise ValueError(f"{raw.strip()} bestaat niet in Nederlandse tijd")
    return utc


def parse_rows(text: str) -> list[dict]:
    """CSV met de kolommen coin,richting,tijd,instap,stop,doel,uitkomst (stop en doel mogen leeg zijn) en optioneel bron,notitie,tf. Elke fout noemt het regelnummer (de kopregel is regel 1)."""
    text = text.lstrip("\ufeff")                                 # Excel zet een BOM voor de eerste kolomnaam
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delimiter = ";" if ";" in first and "," not in first else ","      # Nederlandse Excel slaat op met puntkomma
    # regelnummers tellen records, niet fysieke regels: een veld met een regeleinde in aanhalingstekens verschuift ze, dat komt in deze lijst niet voor
    lines = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    numbered = [(n, row) for n, row in enumerate(lines, start=1) if any(cell.strip() for cell in row)]
    if not numbered:
        raise ValueError("geen kopregel gevonden, verwacht: " + ",".join(COLUMNS))
    head_no, header = numbered[0]
    names = [h.strip().lower() for h in header]
    missing = [c for c in COLUMNS if c not in names]
    if missing:
        raise ValueError(f"regel {head_no}: kolom ontbreekt in de kopregel: {', '.join(missing)} (verwacht: {','.join(COLUMNS)})")
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"regel {head_no}: kolom komt dubbel voor in de kopregel: {', '.join(dupes)}")
    pos = {c: names.index(c) for c in COLUMNS}
    opt = {c: names.index(c) for c in OPTIONAL if c in names}
    rows = []
    for n, cells in numbered[1:]:
        while len(cells) > len(names) and not cells[-1].strip():       # Excel zet soms lege velden achteraan
            cells = cells[:-1]
        if len(cells) != len(names):
            hint = " (komma als decimaalteken? gebruik puntkomma als scheiding of aanhalingstekens)" if len(cells) > len(names) else ""
            raise ValueError(f"regel {n}: {len(cells)} velden, verwacht {len(names)}{hint}")
        try:
            direction = cells[pos["richting"]].strip().lower()
            if direction not in ("long", "short"):
                raise ValueError(f"richting moet long of short zijn, kreeg '{cells[pos['richting']].strip()}'")
            coin = cells[pos["coin"]].strip().upper()
            if not coin:
                raise ValueError("coin is leeg")
            tf = cells[opt["tf"]].strip().lower() if "tf" in opt else ""
            if tf not in TIMEFRAMES:
                raise ValueError(f"tf moet leeg of een van 30m, 1h, 2h, 4h zijn, kreeg '{tf}'")
            rows.append({
                "coin": coin, "direction": direction, "at": _local_to_utc(cells[pos["tijd"]]),
                "entry": _number(cells[pos["instap"]]), "stop": _maybe_number(cells[pos["stop"]]), "target": _maybe_number(cells[pos["doel"]]),
                "outcome": cells[pos["uitkomst"]].strip(),
                "source": cells[opt["bron"]].strip() if "bron" in opt else "", "note": cells[opt["notitie"]].strip() if "notitie" in opt else "", "tf": tf,
            })
        except ValueError as exc:
            raise ValueError(f"regel {n}: {exc}") from None
    return rows


def summarize(results: list[dict]) -> dict:
    """Telt per rij (met de sleutels `engines` en `blocker`) hoeveel trades een motor zag en welke regel de rest weigerde. Alleen patronen, geen drempel."""
    by_engine: Counter = Counter()
    by_blocker: Counter = Counter()
    seen = 0
    for r in results:
        engines = r.get("engines") or []
        if engines:
            seen += 1
            by_engine.update(engines)
        elif r.get("blocker"):
            by_blocker[r["blocker"]] += 1
    return {"n": len(results), "seen": seen, "by_engine": dict(by_engine), "by_blocker": dict(by_blocker)}


def draft_rows(messages: list[dict]) -> list[dict]:
    """Conceptregels voor de handtrades-CSV uit opgeslagen berichten: coin en kant zoals de pipeline ze las, tijd in Nederlandse tijd, de eerste
    prijs uit de tekst als instap. Stop, doel en uitkomst blijven leeg: die vult de gebruiker, wij raden niet."""
    out = []
    for m in messages:
        if not m.get("coin") or m.get("direction") not in ("long", "short"):
            continue
        at = datetime.fromisoformat(m["received_at"]).astimezone(LOCAL_TZ)
        price = _PRICE.search(m.get("raw_text") or "")
        out.append({"coin": m["coin"].upper(), "richting": m["direction"], "tijd": at.strftime("%Y-%m-%d %H:%M"),
                    "instap": f"{_number(price.group(0)):g}" if price else "", "bron": f"bericht {m['id']}", "notitie": (m.get("raw_text") or "")[:120]})
    return out
