"""Nieuws en events: RSS-koppen van crypto-nieuws en de aankondigingen van Binance. Een goedkoop Claude-model (Haiku)
sorteert elke nieuwe kop: welke coins raakt het, welke kant op, hoe groot is de kans op beweging. Het resultaat staat in
`market_events`, het markt-script en de Radar lezen het van daar. Een bron die niet antwoordt wordt overgeslagen, de rest
gaat door. Elke kop wordt maar één keer beoordeeld (url is uniek)."""
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

from app import config, repo

logger = logging.getLogger("news")

RSS_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "The Block": "https://www.theblock.co/rss.xml",
}
BINANCE_URL = ("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
               "?type=1&catalogId=48&pageNo=1&pageSize=10")
MAX_PER_RUN = 20
KEEP_IMPACT = ("middel", "hoog")


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 HesPulse"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def parse_rss(xml_bytes: bytes) -> list[dict]:
    items = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title, link, pub = (item.findtext(k) for k in ("title", "link", "pubDate"))
        if not title or not link:
            continue
        try:
            at = parsedate_to_datetime(pub).astimezone(timezone.utc) if pub else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            at = datetime.now(timezone.utc)
        items.append({"title": title.strip(), "url": link.strip(), "at": at.isoformat()})
    return items


def parse_binance(payload: dict) -> list[dict]:
    items = []
    for a in (payload.get("data") or {}).get("catalogs", [{}])[0].get("articles", []) or []:
        code, title, ms = a.get("code"), a.get("title"), a.get("releaseDate")
        if code and title:
            at = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else datetime.now(timezone.utc)
            items.append({"title": title.strip(), "url": f"https://www.binance.com/en/support/announcement/{code}", "at": at.isoformat()})
    return items


def fetch_all(http: Callable[[str], bytes] = _http) -> list[dict]:
    out = []
    for source, url in RSS_FEEDS.items():
        try:
            out += [{**i, "source": source} for i in parse_rss(http(url))]
        except Exception:
            logger.warning("Bron %s niet bereikbaar, overgeslagen", source)
    try:
        out += [{**i, "source": "Binance"} for i in parse_binance(json.loads(http(BINANCE_URL)))]
    except Exception:
        logger.warning("Binance-aankondigingen niet bereikbaar, overgeslagen")
    return out


SYSTEM_PROMPT = """Je sorteert nieuwskoppen voor een crypto day-trader. Je krijgt een lijst met genummerde koppen. Geef per kop:
- coins: de tickers uit de lijst met gevolgde coins die direct geraakt worden, kommagescheiden. 'ALLES' als het de hele cryptomarkt of een macro-uitslag betreft (rente, inflatie, wet, beurs). Leeg als het geen gevolgde coin raakt.
- direction: long, short of neutraal. De kant waarop de koers volgens het bericht waarschijnlijk beweegt, kort na het bericht.
- impact: laag, middel of hoog. Hoog is een bericht dat binnen uren een merkbare beweging geeft (listing op Binance, hack, uitslag die afwijkt van de verwachting). Meningen, analyses en herhalingen zijn laag.
- summary: één korte zin Nederlands, alleen met feiten uit de kop.
Verzin niets. Twijfel je, kies laag of neutraal. Roep altijd de tool record_events aan."""

TOOL = {
    "name": "record_events",
    "description": "Legt de beoordeling per kop vast.",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "coins": {"type": "string"},
                           "direction": {"type": "string", "enum": ["long", "short", "neutraal"]},
                           "impact": {"type": "string", "enum": ["laag", "middel", "hoog"]}, "summary": {"type": "string"}},
            "required": ["n", "coins", "direction", "impact", "summary"]}}},
        "required": ["items"],
    },
}


def classify_with_claude(items: list[dict]) -> list[dict]:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    listing = "\n".join(f"{i}. [{x['source']}] {x['title']}" for i, x in enumerate(items))
    response = client.messages.create(
        model=config.ANTHROPIC_EXPLAIN_MODEL, max_tokens=2000, system=SYSTEM_PROMPT, tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_events"},
        messages=[{"role": "user", "content": f"Gevolgde coins: {', '.join(config.FIXED_COINS)}\n\n{listing}"}],
    )
    return next(b for b in response.content if b.type == "tool_use").input.get("items", [])


def clean_coins(value: str) -> str:
    parts = [p.strip().upper() for p in (value or "").split(",") if p.strip()]
    if "ALLES" in parts:
        return "ALLES"
    return ",".join(p for p in parts if p in config.FIXED_COINS)


def run(http: Callable[[str], bytes] = _http, classify: Optional[Callable[[list[dict]], list[dict]]] = None) -> int:
    """Geeft het aantal nieuwe, relevante events dat is bewaard."""
    classify = classify or classify_with_claude
    items = fetch_all(http)
    known = repo.known_event_urls([i["url"] for i in items])
    new = sorted((i for i in items if i["url"] not in known), key=lambda i: i["at"], reverse=True)[:MAX_PER_RUN]
    if not new:
        return 0
    try:
        verdicts = {int(v["n"]): v for v in classify(new)}
    except Exception:
        logger.exception("Koppen sorteren is mislukt, volgende keer opnieuw")
        return 0
    kept = 0
    for i, item in enumerate(new):
        v = verdicts.get(i)
        if v is None:
            continue    # niet beoordeeld: niet bewaren, dan komt de kop de volgende keer opnieuw langs
        coins, impact = clean_coins(v.get("coins", "")), v.get("impact", "laag")
        # Alles wordt vastgelegd zodat een kop niet opnieuw beoordeeld wordt, maar alleen relevante koppen tellen mee.
        relevant = bool(coins) and impact in KEEP_IMPACT
        if repo.insert_market_event(item["at"], item["source"], item["title"], item["url"], coins if relevant else "",
                                    v.get("direction", "neutraal"), impact, str(v.get("summary", ""))[:200]) and relevant:
            kept += 1
    return kept


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    logger.info("%s nieuwe events bewaard", run())
