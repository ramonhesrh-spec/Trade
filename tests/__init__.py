import os

# De bestaande tests toetsen het gedrag van elke motor zelf, dus draaien ze met focus uit (ENGINE_FOCUS=false, het oude gedrag). De focus zelf
# toetsen tests/test_focus.py, test_focus_gates.py en test_web_focus.py met config.ENGINE_FOCUS expliciet aan; test_focus bewaakt ook dat de
# standaard in productie aan is. Vóór de eerste import van app.config, en setdefault zodat een expliciete omgevingswaarde wint.
os.environ.setdefault("ENGINE_FOCUS", "false")
# Zo ook het HesPulse-model (standaard aan in productie): met MODEL_ONLY_ALERTS zouden de oude motoren stil worden en hun tab verliezen. De
# modeltests (tests/hespulse_model/, test_model_*.py) zetten config.HESPULSE_MODEL_ENABLED en MODEL_ONLY_ALERTS zelf aan.
os.environ.setdefault("HESPULSE_MODEL_ENABLED", "false")
os.environ.setdefault("MODEL_ONLY_ALERTS", "false")

# De metingen bij de uitkomst (app/outcome_measure.py) halen candles en funding van de beurs. Geen test mag dat echt doen: zonder eigen nabootsing
# faalt het meteen en staat er 'onbekend'. Tests van die metingen zelf vervangen deze naden met mock.patch.object.
from app import outcome_measure as _om  # noqa: E402


def _offline(*_a, **_k):
    raise OSError("geen netwerk in tests")


_om._candles_fetch = _offline
_om._funding_get = _offline
