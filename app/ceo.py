"""De CEO-grap: kleine teksten voor jou en je vrienden, op één plek. Pure functies zonder database. De cijfers op de CEO-pagina zijn echt,
alleen de titels en de zinnen eromheen zijn de grap."""
import math
from datetime import date

GRADE_VERDICT = {"A": "De CEO keurt goed.", "B": "De CEO knikt.", "C": "De CEO twijfelt."}

STATUS_QUOTE = {
    "te_weinig": "De aandeelhouders wachten nog op cijfers.",
    "positief": "Aandeelhouders afwachtend.",
    "voordeel": "Aandeelhouders tevreden.",
    "verlies": "Aandeelhouders ongerust.",
}

QUOTES = (
    "Een stop is geen verlies, het is een strategische bijsturing.",
    "Winst is een stop die nog niet geraakt is.",
    "Een vergadering is een kans die nog niet gevuld heeft.",
    "Wie niet handelt kan ook niet verliezen. Wie niet verliest, is geen CEO.",
    "Een goede CEO delegeert. Een geweldige CEO delegeert zijn stop naar de beurs.",
    "Risico is wat overblijft als je niet in de grafiek kijkt.",
    "Elke R is een bonus, elke min R een leermoment.",
    "De markt sluit nooit, een CEO ook niet.",
)

TESTIMONIALS = (
    "Dankzij de CEO weet ik nu wat een stop is.",
    "Ik heb mijn baan opgezegd. Daarna ook mijn saldo.",
    "De CEO deelt geen trades, hij deelt een gevoel.",
    "Sinds ik meekijk slaap ik beter. De CEO niet, die handelt.",
    "Eerst was ik arm in euro's, nu ben ik arm in R. Vooruitgang.",
    "De masterclass was gratis. De les kostte een stop.",
)

STUDENT_TITLES = ("Stagiair Chief Fomo Officer", "Trainee Overtrading", "Junior analist van de CEO", "Hoofd Koffiezetten", "Leerling-handelaar eerste klas",
                  "Meeloper van de Raad", "Assistent Revenge-trades")


def greeting(hour: int, is_ceo: bool = True, name: str = "") -> str:
    """De CEO krijgt de begroeting van een CEO, iedereen anders die van een leerling."""
    part = "Goedemorgen" if 6 <= hour < 12 else "Goedemiddag" if 12 <= hour < 18 else "Goedenavond"
    if not is_ceo:
        return f"{part} leerling {name}".strip() if hour >= 6 else f"Nog wakker, leerling {name}?".strip()
    return f"{part} CEO" if hour >= 6 else "De CEO werkt over"


def week_headline(net_r: float, resolved: int) -> str:
    if not resolved:
        return "Geen nieuws is goed nieuws"
    return "Bonus uitgekeerd" if net_r > 0 else "Herstructurering aangekondigd" if net_r < 0 else "Resultaten in lijn met verwachting"


def timeline_text(text: str) -> str:
    """Tijdlijnregels in CEO-taal. De betekenis blijft er in staan: wie niet weet wat een persbericht is, leest tussen haakjes wat er gebeurde."""
    if text == "Gemeld":
        return "Persbericht uitgegeven (gemeld)"
    if text.startswith("Plan gemeld"):
        return "Persbericht: plan aangekondigd, limietorder klaarzetten"
    if text.startswith("Limiet geraakt"):
        return "Overname afgerond (limiet geraakt, de trade loopt)"
    if text.startswith("Stop op de instap"):
        return "Strategische bijsturing (stop op de instap geraakt, break-even)"
    if text == "Stop geraakt":
        return "Strategische bijsturing (stop geraakt)"
    if text.startswith("T") and text[1:2].isdigit():
        return f"Winstwaarschuwing, de goede kant ({text})"
    return {"Doel geraakt": "Doel gehaald, bonus", "Vervallen zonder uitkomst": "Vervallen, de CEO ging lunchen"}.get(text, text)


RAIN_BASE = 16


def rain_count(net_r: float) -> int:
    """Hoeveel geldbiljetten er regenen als je de CEO-pagina opent: altijd een bui (de CEO regent altijd), en meer naarmate het weekresultaat
    positief is. Het regent één keer per bezoek, niet doorlopend."""
    return RAIN_BASE if net_r <= 0 else min(56, RAIN_BASE + math.ceil(net_r * 8))


def quote_of_the_day(today: date) -> str:
    return QUOTES[today.toordinal() % len(QUOTES)]


def students(usernames: list[str], today: date) -> list[dict]:
    """De leerlingen met een functietitel. Eén van hen is leerling van de maand, wisselend per kalendermaand."""
    star = (today.year * 12 + today.month) % len(usernames) if usernames else -1
    return [{"name": n, "title": STUDENT_TITLES[i % len(STUDENT_TITLES)], "star": i == star,
             "quote": TESTIMONIALS[(i + today.month) % len(TESTIMONIALS)]} for i, n in enumerate(usernames)]
