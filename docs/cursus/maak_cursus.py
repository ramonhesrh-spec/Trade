"""Maakt docs/cursus/hespulse-cursus.html en .pdf: de HesPulse-cursus voor beginners. Draaien: python3 docs/cursus/maak_cursus.py
De getallen in de tekst komen uit de code en de preregistratie van 3 november 2026; bij een regelwijziging moet deze tekst mee."""
import html
import pathlib

OUT = pathlib.Path(__file__).parent
INK, GREY, RED, GREEN, ZONE = "#1b2324", "#8a9698", "#c0392b", "#1e8449", "#e4e8e8"
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 520, 250, 14, 150, 14, 22


def svg(path, lines=(), boxes=(), marks=(), caption="", n=100):
    """path: [(x, y)] met x 0..n en y 0..100 (hoger = hogere koers). lines: (y, label, kleur, gestippeld). boxes: (x0, x1, y0, y1, label).
    marks: (x, y, label)."""
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    X = lambda x: PAD_L + x / n * pw
    Y = lambda y: PAD_T + (100 - y) / 100 * ph
    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="dia">']
    for box in boxes:
        x0, x1, y0, y1, label = box[:5]
        pos = box[5] if len(box) > 5 else "tl"
        out.append(f'<rect x="{X(x0):.1f}" y="{Y(y1):.1f}" width="{X(x1) - X(x0):.1f}" height="{Y(y0) - Y(y1):.1f}" fill="{ZONE}" stroke="{GREY}" stroke-width="0.8"/>')
        if label:
            # tl: binnen linksboven, tr: binnen rechtsboven, under: onder het vlak (waar de koerslijn er niet doorheen loopt)
            tx, ty, anchor = {"tl": (X(x0) + 4, Y(y1) + 12, "start"), "tr": (X(x1) - 4, Y(y1) + 12, "end"),
                              "under": (X(x0), Y(y0) + 12, "start"), "above": (X(x0), Y(y1) - 5, "start")}[pos]
            out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" class="t s">{html.escape(label)}</text>')
    for y, label, color, dashed in lines:
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R + 6}" y1="{Y(y):.1f}" y2="{Y(y):.1f}" stroke="{color}" stroke-width="1.2"{dash}/>')
        out.append(f'<text x="{W - PAD_R + 10}" y="{Y(y) + 4:.1f}" class="t" fill="{color}">{html.escape(label)}</text>')
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in path)
    out.append(f'<polyline points="{pts}" fill="none" stroke="{INK}" stroke-width="2" stroke-linejoin="round"/>')
    for x, y, label in marks:
        out.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3.5" fill="{INK}"/>')
        out.append(f'<text x="{X(x) + 6:.1f}" y="{Y(y) - 6:.1f}" class="t s">{html.escape(label)}</text>')
    out.append("</svg>")
    cap = f'<figcaption>{caption}</figcaption>' if caption else ""
    return f'<figure>{"".join(out)}{cap}</figure>'


def flow(steps):
    """Een rij vakjes met pijlen: de top-down-volgorde."""
    w, h, gap = 118, 64, 16
    out = [f'<svg viewBox="0 0 {len(steps) * (w + gap) - gap} {h + 4}" xmlns="http://www.w3.org/2000/svg" class="dia">']
    for i, (title, sub) in enumerate(steps):
        x = i * (w + gap)
        out.append(f'<rect x="{x}" y="2" width="{w}" height="{h}" rx="8" fill="#fff" stroke="{INK}" stroke-width="1.2"/>')
        out.append(f'<text x="{x + w / 2}" y="26" text-anchor="middle" class="t b">{html.escape(title)}</text>')
        out.append(f'<text x="{x + w / 2}" y="46" text-anchor="middle" class="t s">{html.escape(sub)}</text>')
        if i < len(steps) - 1:
            out.append(f'<path d="M{x + w + 2} {h / 2 + 2} l{gap - 6} 0 m-5 -4 l5 4 l-5 4" stroke="{INK}" fill="none" stroke-width="1.4"/>')
    out.append("</svg>")
    return f'<figure>{"".join(out)}</figure>'


# ---- de schema's (allemaal een short; een long is hetzelfde in spiegelbeeld) ----
D_RANGE = svg([(0, 92), (14, 96), (32, 20), (46, 8), (62, 40), (74, 33), (88, 66), (100, 58)],
              lines=[(96, "4u range high", INK, False), (52, "evenwicht (0,5)", GREY, True), (8, "4u range low", INK, False)],
              boxes=[(0, 100, 52, 96, "premium: hier zoeken we shorts", "tr")],
              caption="De 4u-range na een breuk omlaag. Boven het evenwicht is het duur (premium), eronder goedkoop (discount). Shorts zoek je in premium.")

D_SWEEP = svg([(0, 30), (12, 55), (20, 48), (30, 62), (40, 50), (52, 58), (58, 74), (62, 60), (72, 52), (84, 40), (100, 30)],
              lines=[(68, "pool: oude 1u-top", INK, True)],
              marks=[(58, 74, "prik erboven"), (62, 60, "slot terug eronder")],
              caption="Een sweep: de koers prikt net boven een oude top (daar liggen stops van anderen) en sluit binnen 6 candles van 15m weer eronder.")

D_RUN = svg([(0, 30), (15, 55), (25, 48), (40, 64), (50, 74), (62, 80), (75, 86), (100, 92)],
            lines=[(68, "pool: oude 1u-top", INK, True)],
            caption="Geen sweep maar een run: de koers sluit boven de pool en blijft erboven. Dan geeft A niets.")

D_A = svg([(0, 40), (14, 60), (24, 52), (34, 70), (40, 80), (44, 66), (52, 72), (60, 48), (66, 46), (74, 56), (80, 50), (100, 18)],
          lines=[(84, "stop: boven de sweep", RED, False), (70, "pool", GREY, True), (60, "limiet A: in de gap", INK, False),
                 (12, "doel: range low of POC", GREEN, False)],
          boxes=[(66, 100, 56, 64, "gap (FVG)", "tr")],
          marks=[(40, 80, "sweep"), (60, 48, "breuk")],
          caption="A: sweep van de pool, dan een harde breuk omlaag op 15m die een gap achterlaat. De limiet ligt in die gap.")

D_B = svg([(0, 30), (14, 86), (26, 56), (40, 76), (48, 62), (54, 66), (62, 44), (70, 50), (78, 46), (100, 14)],
          lines=[(86, "eerdere top", GREY, True), (80, "stop", RED, False), (66, "B: limiet in de gap", INK, False),
                 (56, "R: limiet op het dal", INK, True), (10, "doel", GREEN, False)],
          marks=[(40, 76, "lagere top"), (48, 62, "laatste dal"), (62, 44, "breuk")],
          caption="B en R: een lagere top in premium, dan een slot onder het laatste 15m-dal vóór die top. B wil een gap, R zet de limiet op het gebroken dal. De stop staat boven de lagere top.")

D_K = svg([(0, 10), (10, 22), (20, 40), (30, 62), (38, 82), (42, 76), (48, 80), (54, 74), (60, 79), (66, 75), (70, 60), (78, 66),
           (86, 52), (100, 20)],
          lines=[(86, "stop: boven de top", RED, False), (73, "K: limiet op de onderkant", INK, False), (14, "doel", GREEN, False)],
          boxes=[(38, 66, 73, 83, "consolidatie: 8 candles van 15m", "above")],
          marks=[(70, 60, "breuk")],
          caption="K: na een rechte stijging ligt het laatste dal ver weg. K neemt de 2 uur na de top als consolidatie en breekt de onderkant daarvan.")

SECTIONS = []


def sec(title, body):
    SECTIONS.append((title, body))


sec("Voor je begint", f"""
<p class="lead">Deze cursus legt uit wat HesPulse doet, hoe de instappunten werken en wat er wel en niet bewezen is. Je hebt geen
voorkennis nodig. Elk vakwoord staat in de woordenlijst achterin.</p>
<div class="box warn"><b>Drie dingen vooraf</b>
<ol><li>HesPulse plaatst nooit zelf een order. Jij beslist of je een trade neemt.</li>
<li>HesPulse zegt niets over hoe groot je positie moet zijn. Dat bepaal je zelf, op basis van wat je per trade wilt riskeren.</li>
<li>Alle instappunten zijn <b>ongetest</b>. Er is nog geen bewijs dat ze winst opleveren. Les 6 legt uit hoe we dat meten.</li></ol></div>
<h3>Wat je leert</h3>
<ol><li>Hoe HesPulse de richting kiest (top-down).</li><li>Wat een range, premium en discount zijn.</li>
<li>Wat liquiditeit en een sweep zijn.</li><li>De instappunten A, B, B0, R en K.</li><li>Van melding tot order.</li>
<li>Wat bewezen is en wat niet.</li><li>Goede gewoontes.</li></ol>
""")

sec("Les 1. De richting: van groot naar klein", f"""
<p>HesPulse kijkt eerst naar het grootste tijdframe en werkt dan naar beneden. Dat heet top-down.</p>
{flow([("Dag", "kiest long of short"), ("4 uur", "geeft de range"), ("1 uur", "zoekt de top"), ("15 minuten", "geeft de instap")])}
<ol><li><b>Dag.</b> De laatste breuk op de daggrafiek bepaalt de richting. Brak de koers onder een vorige bodem, dan zoekt HesPulse
alleen shorts. Brak hij boven een vorige top, alleen longs.</li>
<li><b>4 uur.</b> De laatste 4u-breuk in die richting geeft de range waarin we werken (les 2).</li>
<li><b>1 uur.</b> Hier zoekt HesPulse de toppen en bodems waar liquiditeit ligt (les 3) en de lagere toppen (les 4).</li>
<li><b>15 minuten.</b> Hier gebeurt de breuk die het plan klaarzet.</li></ol>
<div class="box"><b>Herstel tegen de dag in.</b> Gaat de 4u-grafiek even omhoog terwijl de dag omlaag wijst, dan is dat een herstel. HesPulse
blijft dan shorts zoeken. In de grafiek "Groot" staat dan bijvoorbeeld "4u ↑ herstel".</div>
<div class="box"><b>Breekt de koers door de rand?</b> Sluit een 4u-candle boven de range high terwijl de dag omlaag blijft wijzen, dan schuift
de range high mee naar de nieuwe top. Er kan dan een nieuw scenario beginnen.</div>
<p class="note">Alles werkt hetzelfde voor longs, alleen in spiegelbeeld. In deze cursus gebruiken we steeds een short als voorbeeld.</p>
""")

sec("Les 2. De range: premium en discount", f"""
<p>Na een breuk omlaag op 4 uur tekent HesPulse een range: van de top van de beweging (range high) tot de bodem (range low). Het
midden heet het <b>evenwicht</b>.</p>
{D_RANGE}
<ul><li><b>Premium</b> is de bovenste helft. Daar is de prijs relatief duur. Shorts zoeken we hier.</li>
<li><b>Discount</b> is de onderste helft. Longs zoeken we daar.</li></ul>
<p>Waarom? Wie short in discount, verkoopt goedkoop en heeft weinig ruimte naar beneden. Wie short in premium, heeft een stop vlak
boven en veel ruimte naar het doel.</p>
""")

sec("Les 3. Liquiditeit en de sweep", f"""
<p>Boven een oude top liggen veel stops van traders die short zitten, en kooporders van uitbraakkopers. Samen heet dat
<b>liquiditeit</b>. HesPulse noemt zo'n plek een <b>pool</b>: een 1u-top die nog niet geraakt is. Twee toppen op bijna dezelfde hoogte
(EQH) tellen als één pool.</p>
{D_SWEEP}
{D_RUN}
<p>Een <b>sweep</b> is een korte prik door de pool, met een slot weer terug. Het idee: grote partijen halen eerst die orders op en
draaien dan. Een <b>run</b> is geen sweep: de koers breekt echt uit.</p>
""")

sec("Les 4. De instappunten", f"""
<p>Een scenario begint als de range klaar staat en er een pool binnen 6% van de koers ligt. Daarna wacht HesPulse op een van de
instappunten hieronder. Elk instappunt heeft een vaste regel. Niemand past die achteraf aan.</p>
<table><tr><th>Letter</th><th>Naam</th><th>Kort</th><th>Melding</th></tr>
<tr><td>A</td><td>Na sweep</td><td>Sweep van de pool, harde breuk, limiet in de gap</td><td>ja</td></tr>
<tr><td>B</td><td>Lagere top</td><td>Lagere top in premium, breuk, limiet in de gap</td><td>ja</td></tr>
<tr><td>B0</td><td>Lagere top, ook buiten premium</td><td>Als B, zonder premium-eis</td><td>ja</td></tr>
<tr><td>R</td><td>Breuk en terugtest</td><td>Als B, maar limiet op het gebroken dal, zonder gap</td><td>ja</td></tr>
<tr><td>K</td><td>Consolidatiebreuk</td><td>Lagere top, breuk van de consolidatie van 2 uur erna</td><td>ja</td></tr>
<tr><td>V1, P</td><td>Vroege limiet, POC-limiet</td><td>Alleen stil gemeten, niet op de kaart</td><td>nee</td></tr></table>
<h3>A: na een sweep</h3>
{D_A}
<ol><li>De koers prikt door de pool en sluit binnen 6 candles van 15m weer terug.</li>
<li>Binnen 24 candles van 15m sluit een candle onder het laatste dal vóór de sweep. Dat is de breuk (shift).</li>
<li>Die breuk gaat met kracht (displacement) en laat een gat in de prijs achter: een fair value gap (FVG).</li>
<li><b>Limiet</b> in de gap. <b>Stop</b> een kwart ATR boven de top van de sweep, minstens 0,4% van de limiet. <b>Doel</b> de dichtstbijzijnde
van de range low en een naakte POC.</li></ol>
<h3>B, B0 en R: de lagere top</h3>
{D_B}
<ol><li>De koers maakt op 1 uur een top die lager is dan de vorige. Bij B en R ligt die top in premium.</li>
<li>Binnen 24 candles van 15m sluit een candle onder het laatste 15m-dal vóór die top.</li>
<li><b>B</b>: daarna een harde breuk met een gap; limiet in de gap, en die limiet moet ook in premium liggen.</li>
<li><b>B0</b>: hetzelfde als B, maar zonder premium-eis.</li>
<li><b>R</b>: geen gap nodig; de limiet ligt op het gebroken dal zelf (de terugtest).</li>
<li>Stop boven de lagere top (een kwart ATR erboven, minstens 0,4%), doel zoals bij A.</li></ol>
<h3>K: de consolidatiebreuk</h3>
{D_K}
<p>Na een rechte stijging ligt het laatste dal vóór de top ver weg, en dan breken B en R vaak niet op tijd. K kijkt daarom naar de 2 uur
(8 candles van 15m) direct na de top. Breekt de koers onder de onderkant daarvan, binnen 6 uur na de top, dan staat K klaar. Limiet op
die onderkant, stop boven de top, doel zoals bij A.</p>
<div class="box"><b>Voorrang.</b> Liggen er meer plannen tegelijk klaar, dan toont de kaart er één: eerst B, dan R, dan K, dan B0. De andere
staan in het detailblad.</div>
""")

sec("Les 5. Van melding tot order", f"""
<h3>1. Je krijgt een korte melding</h3>
<div class="push"><b>▼ SOL short · HesPulse K</b><br>Limiet 96.93 · Stop 98.68 · Doel 92.25</div>
<p>Meer staat er niet in. De uitleg vind je op de kaart.</p>
<h3>2. Je opent de kaart op Kansen</h3>
<ul><li>"Plan K klaar" met limiet, stop, doel en tot hoe laat het plan geldt.</li>
<li>Een plan geldt <b>6 uur</b> na de breuk. Daarna vervalt het. Een vervallen plan verdwijnt van de kaart.</li>
<li>"Groot" opent de grafiek met de range, het evenwicht en de trend per tijdframe.</li></ul>
<h3>3. Je zet de order, stap voor stap</h3>
<ol><li>Open de coin bij je beurs. Kies short (of long) en Limit.</li><li>Plak de limietprijs.</li>
<li>Zet de stop er meteen bij, niet later.</li><li>Zet het doel.</li></ol>
<h3>4. Daarna</h3>
<ul><li>Vult de limiet, dan krijg je een stille melding "gevuld".</li>
<li>Raakt de koers stop of doel, dan krijg je daar een melding van.</li>
<li>Vult de limiet niet binnen 6 uur, of loopt de koers eerst naar het doel, dan is er geen trade.</li></ul>
<h3>Wanneer je geen melding krijgt</h3>
<ul><li>De koers stond al voorbij de limiet: een marktorder doet HesPulse nooit.</li>
<li>De trade gaat tegen BTC op 4 uur in (de BTC-poort). Die trade wordt wel stil gevolgd.</li>
<li>Je dagbudget van 8 luide meldingen is op: je krijgt dan een stille melding, en de kans staat op de pagina Meldingen.</li></ul>
""")

sec("Les 6. Wat is bewezen?", f"""
<div class="box warn"><b>Kort antwoord: nog niets.</b> Geen enkel instappunt heeft genoeg afgeronde trades om iets te bewijzen.</div>
<h3>Wat we wel weten (stand 3 november 2026)</h3>
<ul><li>A gaf in de eerste 54 scenario's nog geen enkele entry. De volledige keten (sweep, breuk, gap) is streng.</li>
<li>V1 verloor 6 van de 6 trades, maar dat waren twee bewegingen van BTC. Daarom staat V1 niet meer op de kaart en wordt hij alleen
stil gemeten.</li>
<li>K is gebouwd op één voorbeeld (SOL, 30 oktober). Dat K dat voorbeeld goed voorspelt, telt niet: een regel scoort altijd goed op zijn
eigen aanleiding.</li></ul>
<h3>Hoe we het eerlijk meten</h3>
<ol><li><b>Regels liggen vooraf vast.</b> Elk getal staat in de preregistratie voordat er gemeten wordt, en wordt achteraf niet aangepast.</li>
<li><b>Bevriezing.</b> Drie weken verandert er niets aan de instapregels. Alleen trades van na het bevriezingsmoment tellen.</li>
<li><b>Netto na kosten.</b> Elke trade telt na 0,06% kosten per rondreis, en na funding als die gemeten is.</li>
<li><b>In R.</b> 1R is wat je verliest als de stop geraakt wordt. +2R betekent twee keer je risico gewonnen.</li>
<li><b>Per week.</b> Trades in dezelfde week en richting hangen samen. Daarom rekent HesPulse het onzekerheidsinterval per week.</li>
<li><b>Stopregel per instappunt.</b> Na 30 afgeronde trades een eerste blik. Na 50 stopt de melding van een punt als de netto R per
week duidelijk onder nul ligt. Meten gaat altijd door.</li>
<li><b>Een besluit over het model</b> komt pas bij 150 afgeronde trades, verspreid over 12 weken.</li></ol>
<h3>Waar je het ziet</h3>
<p>Op de pagina <b>Bewijs</b>: per instappunt het aantal afgeronde trades, de netto R en de stand van de stopregel. En per kenmerk van een
hoger tijdframe (12u- of dagzone, dagpremium, dag- of weekopen) hoe plannen met en zonder dat kenmerk scoren. Dat beschrijft; het
voorspelt nog niets.</p>
<div class="box"><b>Waarom één mooi voorbeeld niets zegt.</b> Op een grafiek achteraf zie je de winnaars. De trades die op dezelfde
manier verloren, zie je niet. Alleen alle trades samen, vooraf vastgelegd, zeggen of een regel werkt.</div>
""")

sec("Les 7. Goede gewoontes", f"""
<ol><li><b>Bepaal je risico vóór de trade.</b> Bijvoorbeeld 0,5% tot 1% van je rekening per trade. Je positiegrootte volgt uit de afstand
tot de stop.</li>
<li><b>Verplaats je stop niet verder weg.</b> De meting gaat uit van de stop op de kaart.</li>
<li><b>Jaag de koers niet na.</b> Staat de koers al voorbij de limiet, dan is er geen trade. Wacht op de volgende.</li>
<li><b>Let op samenhang.</b> Staan er tien shorts open die allemaal van BTC afhangen, dan is dat eigenlijk één grote trade. Draait BTC, dan
gaan ze samen onderuit.</li>
<li><b>Houd een logboek.</b> Het Logboek in de app laat zien wat je deed en wat de uitkomst was.</li>
<li><b>Ongetest betekent ongetest.</b> Behandel elk plan als een experiment met klein risico, tot Bewijs iets anders laat zien.</li></ol>
""")

sec("Woordenlijst", f"""
<dl>
<dt>ATR</dt><dd>De gemiddelde beweging per candle. HesPulse gebruikt hem voor de afstand van de stop.</dd>
<dt>BOS, CHoCH, breuk</dt><dd>Een slot voorbij de vorige top of bodem. BOS gaat mee met de trend, CHoCH draait de trend.</dd>
<dt>Candle</dt><dd>Eén staafje in de grafiek: open, hoog, laag en slot over een vaste tijd (15m, 1u, 4u, dag).</dd>
<dt>Consolidatie</dt><dd>Een periode waarin de koers zijwaarts beweegt in een smalle band.</dd>
<dt>Displacement</dt><dd>Een harde, snelle beweging over meerdere candles.</dd>
<dt>Doel</dt><dd>De prijs waar je winst neemt.</dd>
<dt>EQH, EQL</dt><dd>Twee toppen of bodems op bijna gelijke hoogte. Daar ligt vaak extra liquiditeit.</dd>
<dt>Evenwicht</dt><dd>Het midden van de range (0,5).</dd>
<dt>FVG (fair value gap)</dt><dd>Een gat tussen drie candles waar de prijs niet verhandeld is. Vaak komt de koers erin terug.</dd>
<dt>Limietorder</dt><dd>Een order die pas vult als de koers jouw prijs raakt.</dd>
<dt>Liquiditeit, pool</dt><dd>Een plek met veel stops en orders, meestal boven een top of onder een bodem.</dd>
<dt>Order block (OB)</dt><dd>De laatste candle tegen de richting in, vlak voor een harde beweging.</dd>
<dt>POC</dt><dd>Point of control: de prijs met het meeste volume in een dag of week. "Naakt" als de koers er sindsdien niet meer kwam.</dd>
<dt>Premium, discount</dt><dd>De bovenste en onderste helft van de range.</dd>
<dt>R, R:R</dt><dd>R is je risico per trade. R:R is de verhouding tussen mogelijke winst en risico.</dd>
<dt>Range</dt><dd>De beweging tussen een top en een bodem waarbinnen HesPulse werkt.</dd>
<dt>Stop</dt><dd>De prijs waarop je verlies neemt als het plan niet klopt.</dd>
<dt>Sweep</dt><dd>Een korte prik door een pool met een slot weer terug.</dd>
<dt>Top-down</dt><dd>Van het grote tijdframe naar het kleine werken.</dd></dl>
""")

CSS = f"""
@page {{ size: A4; margin: 18mm 16mm 18mm 16mm; }}
body {{ font-family: 'Helvetica Neue', Arial, sans-serif; color: {INK}; font-size: 10.5pt; line-height: 1.5; }}
.cover {{ height: 245mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }}
.cover h1 {{ font-size: 34pt; margin: 0 0 6mm; letter-spacing: -0.5px; }}
.cover p {{ font-size: 13pt; color: #4a5658; margin: 0 0 3mm; }}
.cover .meta {{ margin-top: 20mm; font-size: 10pt; color: #6b7678; }}
section {{ page-break-before: always; }}
h2 {{ font-size: 18pt; margin: 0 0 4mm; border-bottom: 2px solid {INK}; padding-bottom: 2mm; }}
h3 {{ font-size: 12pt; margin: 6mm 0 2mm; break-after: avoid; }}
.lead {{ font-size: 12pt; }}
.box {{ border: 1px solid #c9d0d1; background: #f4f6f6; border-radius: 6px; padding: 3mm 4mm; margin: 4mm 0; break-inside: avoid; }}
.box.warn {{ border-left: 4px solid {RED}; }}
.box ol, .box ul {{ margin: 2mm 0 0; }}
.note {{ color: #5a6668; font-size: 9.5pt; }}
figure {{ margin: 4mm 0; break-inside: avoid; }}
figcaption {{ font-size: 9pt; color: #5a6668; margin-top: 1mm; }}
.dia {{ width: 100%; height: auto; }}
.dia .t {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11px; fill: {INK}; }}
.dia .s {{ font-size: 10px; }}
.dia .b {{ font-weight: 700; font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9.5pt; break-inside: avoid; }}
th, td {{ border-bottom: 1px solid #d5dbdc; text-align: left; padding: 1.5mm 2mm; vertical-align: top; }}
th {{ background: #eef1f1; }}
.push {{ border: 1px solid #c9d0d1; border-radius: 10px; padding: 3mm 4mm; width: 70%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
dl dt {{ font-weight: 700; margin-top: 1.2mm; }} dl dd {{ margin: 0; }} dl {{ font-size: 9.8pt; line-height: 1.4; }}
.toc li {{ margin: 1mm 0; }}
"""


def build():
    toc = "".join(f"<li>{html.escape(t)}</li>" for t, _ in SECTIONS)
    body = "".join(f"<section><h2>{html.escape(t)}</h2>{b}</section>" for t, b in SECTIONS)
    page = f"""<!doctype html><html lang="nl"><head><meta charset="utf-8"><title>HesPulse cursus</title><style>{CSS}</style></head><body>
<div class="cover"><h1>HesPulse<br>voor beginners</h1><p>Hoe het model kansen vindt, hoe de instappunten werken en wat er wel en niet bewezen is.</p>
<ol class="toc">{toc}</ol><p class="meta">Stand 3 november 2026. Alle instappunten zijn ongetest. HesPulse plaatst nooit zelf een order.</p></div>
{body}</body></html>"""
    (OUT / "hespulse-cursus.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    # De PDF maakt docs/cursus/naar_pdf.js met de Chromium van Playwright (Node): node docs/cursus/naar_pdf.js
    build()
    print("html klaar")
