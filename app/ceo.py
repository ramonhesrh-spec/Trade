"""Gewone teksten voor de begroeting en de week. Tot 2026-11-03 stond hier de CEO-grap (pagina /ceo, geldregen, quotes, CEO-taal in de
tijdlijn); op verzoek van de CEO weg: "het grappen is nu over, we gaan nu echt werken". De modulenaam bleef om de imports niet te
verschuiven."""


def greeting(hour: int, is_ceo: bool = True, name: str = "") -> str:
    """Dezelfde begroeting voor iedereen, met de naam."""
    part = "Goedenacht" if hour < 6 else "Goedemorgen" if hour < 12 else "Goedemiddag" if hour < 18 else "Goedenavond"
    return f"{part} {name}".strip()


def week_headline(net_r: float, resolved: int) -> str:
    if not resolved:
        return "Nog geen afgeronde trades deze week"
    return "Week positief" if net_r > 0 else "Week negatief" if net_r < 0 else "Week vlak"
