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
- direction: "long", "short", of bij category "lange_termijn" ook \
"neutraal". Gebruik "neutraal" voor een lange termijn analyse die zelf \
argumenten voor én tegen een richting geeft, zonder duidelijke conclusie \
(bijvoorbeeld "misschien de bodem, misschien niet"). Dat is een geldige, \
bruikbare conclusie, geen onduidelijk bericht: het systeem leert net zo \
goed van "de mening is verdeeld" als van een duidelijke richting, dus \
gebruik "neutraal" in plaats van leeg laten of unclear zetten zodra de \
coin wel duidelijk is. Voor category "day_trading" is direction altijd \
"long" of "short", nooit "neutraal", een concrete trade opzet kiest een \
kant. Leeg laten alleen als zelfs geen enkele richting of afweging uit \
het bericht te halen is.
- category: "day_trading" voor een concrete kortetermijn trade opzet met \
een entry op de 4 uur candle of korter. "lange_termijn" voor een analyse \
zonder korte termijn horizon: onderbouwing op de weekly of monthly candle, \
een cyclusanalyse, on-chain data, of een algemene marktvisie ("dit is de \
bodem", "dit wordt een bullrun"), ook als er een richting of percentage \
kans bij staat. "aandelen" als het bericht over aandelen gaat in plaats \
van crypto. Bij twijfel tussen day_trading en lange_termijn: kies \
lange_termijn, want zonder concrete kortetermijn entry heeft toetsen op \
de 4 uur candle geen betekenis.
- unclear: true als de coin niet met voldoende zekerheid te bepalen is, \
of als het bij day_trading gaat om een concrete trade opzet zonder \
duidelijke long/short richting. Een lange termijn analyse met een \
verdeelde conclusie (direction "neutraal") is NIET unclear, die is prima \
te bepalen, alleen niet eenduidig.
- reason: korte reden waarom het bericht onduidelijk is, alleen invullen \
als unclear true is.

Als er een afbeelding is meegestuurd: kijk alleen naar niveaus en patronen \
die de bron zelf al heeft ingetekend op de afbeelding (bijvoorbeeld \
horizontale lijnen, een driehoek, een hoofd-schouderpatroon met labels). \
Neem deze een op een over in source_levels, met de prijs van elk niveau en \
de naam van het patroon indien aangegeven. Verzin zelf geen niveaus of \
patronen die niet zichtbaar zijn ingetekend. Als er geen afbeelding is, of \
er is niets ingetekend, laat source_levels leeg.

Staat er een schuine lijn ingetekend (een trendlijn, de rand van een \
driehoek of wig, de nek van een hoofd-schouderpatroon)? Zet die dan ook in \
trendlines, met twee punten: het beginpunt en het eindpunt van die lijn, \
elk met een prijs en een schatting van hoeveel dagen geleden dat punt op \
de tijd-as van de afbeelding staat (bijvoorbeeld "point1_days_ago": 12 als \
het beginpunt 12 dagen voor het laatste zichtbare punt ligt, en \
"point2_days_ago": 0 voor het meest recente punt, nu). Kijk naar de \
datums of tijd-labels onderaan de afbeelding om deze schatting te maken, \
een ruwe schatting is beter dan niets, maar verzin geen lijn die er niet \
staat. Dit wordt gebruikt om dezelfde lijn na te tekenen op onze eigen, \
actuele koersdata, dus de prijs en de relatieve tijdsafstand tussen de \
twee punten zijn wat telt, niet de exacte pixelpositie in de afbeelding \
zelf. Laat trendlines leeg als er geen schuine lijn is ingetekend.

Lees elk cijfer zorgvuldig af, crypto grafieken hebben vaak 2 tot 4 \
decimalen, een verkeerd geplaatste komma maakt het niveau waardeloos. Kijk \
bij twijfel nog een keer goed naar de exacte positie van het label op de \
afbeelding voor je het cijfer doorgeeft.

Controleer daarna of het label van elk niveau logisch is bij de richting \
van de trade en de huidige prijs op de afbeelding: bij long hoort een \
"target" boven de huidige prijs te liggen en een support/retest niveau \
eronder, bij short precies andersom. Klopt een niveau niet met zijn eigen \
label (bijvoorbeeld een "target" die onder de prijs ligt bij een long), \
neem het label dan niet klakkeloos over: geef in pattern_name liever de \
rol die logisch bij de positie past (bijvoorbeeld "support" of "retest \
niveau" in plaats van "target"), of laat dit ene niveau weg als je niet \
zeker weet wat het voorstelt. Verzin nooit een richting om het kloppend \
te maken, de prijs die je afleest blijft altijd leidend.

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
                "enum": ["long", "short", "neutraal", ""],
                "description": "\"neutraal\" alleen bij lange_termijn met een verdeelde conclusie. Leeg laten indien onbekend.",
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
            "trendlines": {
                "type": "array",
                "description": "Schuine lijnen (trendlijn, wig, driehoekzijde) die de bron zelf heeft ingetekend, met twee punten en een geschatte tijdsafstand in dagen.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "point1_price": {"type": "number"},
                        "point1_days_ago": {"type": "number", "description": "Hoeveel dagen voor het meest recente zichtbare punt dit punt ligt."},
                        "point2_price": {"type": "number"},
                        "point2_days_ago": {"type": "number", "description": "Meestal 0 voor het meest recente punt."},
                    },
                    "required": ["point1_price", "point1_days_ago", "point2_price", "point2_days_ago"],
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
class SourceTrendline:
    point1_price: float
    point1_days_ago: float
    point2_price: float
    point2_days_ago: float
    label: Optional[str] = None


@dataclass
class Interpretation:
    coin: Optional[str]
    direction: Optional[str]
    category: str
    unclear: bool
    reason: str = ""
    source_levels: list[SourceLevel] = field(default_factory=list)
    trendlines: list[SourceTrendline] = field(default_factory=list)


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
    trendlines = [
        SourceTrendline(
            point1_price=tl["point1_price"], point1_days_ago=tl["point1_days_ago"],
            point2_price=tl["point2_price"], point2_days_ago=tl["point2_days_ago"],
            label=tl.get("label") or None,
        )
        for tl in payload.get("trendlines", [])
    ]

    if coin is None:
        unclear = True
        if not reason:
            reason = "coin niet duidelijk uit het bericht te halen"
    elif category == "day_trading" and direction is None:
        # Alleen bij een concrete day trading opzet is een echte long/short
        # richting verplicht. Een lange termijn analyse mag ook "neutraal"
        # zijn, dat is een geldige, bruikbare conclusie, geen onduidelijkheid.
        unclear = True
        if not reason:
            reason = "richting niet duidelijk uit het bericht te halen"

    return Interpretation(
        coin=coin, direction=direction, category=category,
        unclear=unclear, reason=reason, source_levels=source_levels,
        trendlines=trendlines,
    )
