"""Zuivere logica voor de misser-controle op een lijst handtrades: de CSV lezen en de uitkomsten samenvatten. Geen netwerk, geen drempels."""
import csv
import io
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
COLUMNS = ["coin", "richting", "tijd", "instap", "stop", "doel", "uitkomst"]


def _number(raw: str) -> float:
    return float(raw.strip().replace(",", "."))


def _local_to_utc(raw: str) -> datetime:
    naive = datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M")
    local = naive.replace(tzinfo=LOCAL_TZ, fold=0)             # dubbel uur bij het terugzetten van de klok: de eerste keer
    utc = local.astimezone(timezone.utc)
    if utc.astimezone(LOCAL_TZ).replace(tzinfo=None) != naive:  # uur dat bij het vooruitzetten van de klok niet bestaat
        raise ValueError(f"{raw.strip()} bestaat niet in Nederlandse tijd")
    return utc


def parse_rows(text: str) -> list[dict]:
    """CSV met de kolommen coin,richting,tijd,instap,stop,doel,uitkomst. Elke fout noemt het regelnummer (de kopregel is regel 1)."""
    lines = list(csv.reader(io.StringIO(text)))
    # csv.reader geeft voor een lege regel [] terug; reader.line_num zou bij velden met regeleinden afwijken, dus tel op de lijst zelf
    numbered = [(n, row) for n, row in enumerate(lines, start=1) if any(cell.strip() for cell in row)]
    if not numbered:
        raise ValueError("geen kopregel gevonden, verwacht: " + ",".join(COLUMNS))
    head_no, header = numbered[0]
    names = [h.strip().lower() for h in header]
    missing = [c for c in COLUMNS if c not in names]
    if missing:
        raise ValueError(f"regel {head_no}: kolom ontbreekt in de kopregel: {', '.join(missing)} (verwacht: {','.join(COLUMNS)})")
    pos = {c: names.index(c) for c in COLUMNS}
    rows = []
    for n, cells in numbered[1:]:
        if len(cells) < len(names):
            raise ValueError(f"regel {n}: {len(cells)} velden, verwacht {len(names)}")
        try:
            direction = cells[pos["richting"]].strip().lower()
            if direction not in ("long", "short"):
                raise ValueError(f"richting moet long of short zijn, kreeg '{cells[pos['richting']].strip()}'")
            coin = cells[pos["coin"]].strip().upper()
            if not coin:
                raise ValueError("coin is leeg")
            rows.append({
                "coin": coin, "direction": direction, "at": _local_to_utc(cells[pos["tijd"]]),
                "entry": _number(cells[pos["instap"]]), "stop": _number(cells[pos["stop"]]), "target": _number(cells[pos["doel"]]),
                "outcome": cells[pos["uitkomst"]].strip(),
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
