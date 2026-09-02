"""Interpretatie van Discord berichten via de Anthropic API.

Haalt eruit: coin, richting (long/short), categorie (day trading, lange
termijn, aandelen). Bij een bijgevoegde afbeelding wordt gevraagd welke
niveaus en welk patroon de bron zelf al heeft ingetekend, dit is overname
van bestaande analyse, geen eigen patroonherkenning.
"""
import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import anthropic

from app import config

SYSTEM_PROMPT = """Je analyseert een doorgestuurd bericht uit een betaalde \
crypto trading Discord community. Het bericht is doorgestuurd naar een eigen \
bot account.

Haal op:
- coin: het ticker symbool van de coin waar het bericht over gaat, \
bijvoorbeeld BTC, ETH, SOL. Leeg laten als dit niet met voldoende zekerheid \
te bepalen is.
- direction: "long" of "short". Leeg laten als dit niet met voldoende \
zekerheid te bepalen is.
- category: "day_trading" voor een concrete kortetermijn trade opzet met \
een entry op de 4 uur candle of korter. "lange_termijn" voor een analyse \
zonder korte termijn horizon: onderbouwing op de weekly of monthly candle, \
een cyclusanalyse, on-chain data, of een algemene marktvisie ("dit is de \
bodem", "dit wordt een bullrun"), ook als er een richting of percentage \
kans bij staat. "aandelen" als het bericht over aandelen gaat in plaats \
van crypto. Bij twijfel tussen day_trading en lange_termijn: kies \
lange_termijn, want zonder concrete kortetermijn entry heeft toetsen op \
de 4 uur candle geen betekenis.
- unclear: true als coin of direction niet met voldoende zekerheid te \
bepalen zijn. Bij twijfel altijd unclear op true zetten.
- reason: korte reden waarom het bericht onduidelijk is, alleen invullen \
als unclear true is.

Als er een afbeelding is meegestuurd: kijk alleen naar niveaus en patronen \
die de bron zelf al heeft ingetekend op de afbeelding (bijvoorbeeld \
horizontale lijnen, een driehoek, een hoofd-schouderpatroon met labels). \
Neem deze een op een over in source_levels, met de prijs van elk niveau en \
de naam van het patroon indien aangegeven. Verzin zelf geen niveaus of \
patronen die niet zichtbaar zijn ingetekend. Als er geen afbeelding is, of \
er is niets ingetekend, laat source_levels leeg.

Roep altijd de tool record_interpretation aan met je bevindingen."""

TOOL = {
    "name": "record_interpretation",
    "description": "Registreer de interpretatie van een Discord trading bericht.",
    "input_schema": {
        "type": "object",
        "properties": {
            "coin": {
                "type": "string",
                "description": "Ticker symbool, bijvoorbeeld BTC. Leeg laten indien onbekend.",
            },
            "direction": {
                "type": "string",
                "enum": ["long", "short", ""],
                "description": "Leeg laten indien onbekend.",
            },
            "category": {
                "type": "string",
                "enum": ["day_trading", "lange_termijn", "aandelen"],
            },
            "unclear": {
                "type": "boolean",
                "description": "True als coin of direction niet zeker zijn.",
            },
            "reason": {
                "type": "string",
                "description": "Reden waarom het bericht onduidelijk is, indien van toepassing.",
            },
            "source_levels": {
                "type": "array",
                "description": "Niveaus/patroon die de bron al zelf heeft ingetekend op een bijgevoegde afbeelding.",
                "items": {
                    "type": "object",
                    "properties": {
                        "price_level": {"type": "number"},
                        "pattern_name": {"type": "string"},
                    },
                    "required": ["price_level"],
                },
            },
        },
        "required": ["category", "unclear"],
    },
}


@dataclass
class SourceLevel:
    price_level: float
    pattern_name: Optional[str] = None


@dataclass
class Interpretation:
    coin: Optional[str]
    direction: Optional[str]
    category: str
    unclear: bool
    reason: str = ""
    source_levels: list[SourceLevel] = field(default_factory=list)


def _image_block(path: str) -> dict:
    media_type = mimetypes.guess_type(path)[0] or "image/png"
    data = base64.standard_b64encode(Path(path).read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


def interpret_message(raw_text: str, image_paths: Optional[list[str]] = None) -> Interpretation:
    image_paths = image_paths or []
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    content: list[dict] = [{"type": "text", "text": raw_text or "(leeg bericht, alleen afbeelding)"}]
    for path in image_paths:
        content.append(_image_block(path))

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_interpretation"},
        messages=[{"role": "user", "content": content}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    payload = tool_use.input

    coin = (payload.get("coin") or "").strip().upper() or None
    direction = (payload.get("direction") or "").strip().lower() or None
    category = payload.get("category", "day_trading")
    unclear = bool(payload.get("unclear", False))
    reason = payload.get("reason", "")

    source_levels = [
        SourceLevel(price_level=lvl["price_level"], pattern_name=lvl.get("pattern_name") or None)
        for lvl in payload.get("source_levels", [])
    ]

    if coin is None or direction is None:
        unclear = True
        if not reason:
            reason = "coin of richting niet duidelijk uit het bericht te halen"

    return Interpretation(
        coin=coin, direction=direction, category=category,
        unclear=unclear, reason=reason, source_levels=source_levels,
    )
