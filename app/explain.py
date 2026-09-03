"""Legt een technisch signaal in gewone taal uit via Anthropic, gebaseerd op
de al berekende factoren. Verzint zelf niets: schrijft alleen om wat het
systeem al heeft vastgesteld (indicators.confirms_direction), zodat de
uitleg nooit kan afwijken van de harde regels die de melding echt bepalen.
"""
import logging

import anthropic

from app import config

logger = logging.getLogger("explain")

SYSTEM_PROMPT = """Je legt een technisch handelssignaal uit aan iemand die \
net begint met traden. Je krijgt de coin, richting, het vertrouwen en de \
losse factoren die het systeem al heeft getoetst (elk met een vinkje of \
kruisje en een cijfermatige toelichting). Gebruik uitsluitend deze gegeven \
feiten, verzin nooit een nieuw niveau, cijfer of conclusie die er niet \
letterlijk in staat. Leg in maximaal 4 korte zinnen Nederlands uit wat de \
belangrijkste factoren betekenen en waarom ze meetellen, zodat iemand \
zonder voorkennis het leert begrijpen. Noem minstens één term kort uit \
(bijvoorbeeld wat RSI, ADX, of EMA9/21 betekent) als die in de factoren \
voorkomt. Geen jargon zonder uitleg, geen vage algemeenheden, en geen \
beleggingsadvies zoals "dit is een goed moment om te kopen": alleen \
uitleggen wat er staat en waarom, niet aanraden wat te doen."""


def explain_signal(
    coin: str, direction: str, confidence: str, reason: str,
    price: float, stop_loss: float, take_profit: float,
) -> str:
    """Geeft een lege string terug bij een API-fout: de melding zelf mag
    daar nooit op vastlopen, de rauwe factoren blijven sowieso altijd
    zichtbaar als alternatief."""
    if not reason:
        return ""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = (
        f"Coin: {coin}\nRichting: {direction}\nVertrouwen: {confidence}\n"
        f"Prijs: {price}\nStop loss: {stop_loss}\nTake profit: {take_profit}\n"
        f"Factoren: {reason}"
    )
    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text").strip()
    except Exception:
        logger.exception("Uitleg voor signaal %s %s kon niet gegenereerd worden", coin, direction)
        return ""
