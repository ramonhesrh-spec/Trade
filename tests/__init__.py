import os

# De bestaande tests toetsen het gedrag van elke motor zelf, dus draaien ze met focus uit (ENGINE_FOCUS=false, het oude gedrag). De focus zelf
# toetsen tests/test_focus.py, test_focus_gates.py en test_web_focus.py met config.ENGINE_FOCUS expliciet aan; test_focus bewaakt ook dat de
# standaard in productie aan is. Vóór de eerste import van app.config, en setdefault zodat een expliciete omgevingswaarde wint.
os.environ.setdefault("ENGINE_FOCUS", "false")
