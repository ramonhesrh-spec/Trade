(function () {
  const container = document.getElementById("chart");
  if (!container) return;

  // iOS Safari meet de container soms verkeerd op het eerste moment (voor
  // de layout klaar is), en het "resize" event van het window gaat daar
  // niet betrouwbaar af als de adresbalk in- of uitschuift. Vandaar een
  // expliciete startbreedte/hoogte plus een ResizeObserver die de
  // container zelf in de gaten houdt, niet het window.
  const startRect = container.getBoundingClientRect();
  const chart = LightweightCharts.createChart(container, {
    width: Math.round(startRect.width) || window.innerWidth,
    height: Math.round(startRect.height) || 320,
    layout: { background: { color: "#131a1b" }, textColor: "#b7c4c2" },
    grid: { vertLines: { color: "#1c2526" }, horzLines: { color: "#1c2526" } },
    timeScale: { timeVisible: true, borderColor: "#232d2f" },
    rightPriceScale: { borderColor: "#232d2f" },
    // Standaard "magnet" snapt de crosshair (en dus ook elke klik) naar de
    // dichtstbijzijnde lijnserie, bijvoorbeeld EMA9/EMA21. Voor het zelf
    // tekenen van een lijn moet een klik precies de aangewezen prijs onder
    // de muis pakken, niet de dichtstbijzijnde EMA-waarde.
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#33d69f", downColor: "#f2685c",
    borderVisible: false, wickUpColor: "#33d69f", wickDownColor: "#f2685c",
  });

  // Alle markers die permanent op de grafiek horen te staan: narrative-
  // updates ÉN herkende candlestick-patronen samen in één array. Apart
  // bijgehouden (niet steeds opnieuw uit candleSeries gelezen) omdat
  // stopDrawing() verderop candleSeries.setMarkers([]) aanroept om zijn
  // eigen tijdelijke teken-marker weg te halen — die moet deze markers
  // herstellen, niet leegmaken. setMarkers() VERVANGT de volledige
  // markerlijst bij elke aanroep, dus narrative- en patroon-markers
  // moeten altijd samen in deze ene array staan, nooit in aparte
  // setMarkers()-aanroepen.
  let narrativeMarkers = [];

  // Zelf-gedetecteerde steun/weerstand-zones (indicators.detect_sr_zones,
  // via het sr_zones-veld van /api/candles). Anders dan de community-
  // zoneGroups hieronder (al bekend uit sourceLevels vóór de fetch) bestaan
  // deze pas ná de fetch, dus srZoneEls wordt pas in de .then()-callback
  // gevuld — maar moet hier al gedeclareerd staan zodat positionZones()
  // (aangeroepen vanaf de eerste render) hem veilig kan itereren, ook
  // vóórdat de fetch klaar is (dan gewoon een lege lijst).
  let srZoneEls = [];

  // Een uitbraak-dan-terugtest-melding ("optie C") linkt hierheen met
  // ?zone_low=...&zone_high=..., de exacte grenzen uit die ene melding.
  // Zonder dit was niet te zien welke
  // van mogelijk meerdere zelf-gedetecteerde zones op de grafiek bij de
  // melding hoorde. Tolerantie relatief (0.5%): de zone-detectie zelf kan
  // tegen de tijd dat iemand klikt een candle later opnieuw gedraaid zijn,
  // exacte float-gelijkheid zou dan al niet meer matchen.
  const urlParams = new URLSearchParams(window.location.search);
  const highlightLow = parseFloat(urlParams.get("zone_low"));
  const highlightHigh = parseFloat(urlParams.get("zone_high"));
  const hasHighlightZone = !isNaN(highlightLow) && !isNaN(highlightHigh);
  function isHighlightedZone(zone) {
    if (!hasHighlightZone) return false;
    const tolerance = Math.max(zone.price_high - zone.price_low, zone.price_high * 0.005);
    return Math.abs(zone.price_low - highlightLow) <= tolerance
      && Math.abs(zone.price_high - highlightHigh) <= tolerance;
  }

  function nearestCandleTime(candles, unixSeconds) {
    let best = candles[0].time;
    let bestDiff = Math.abs(candles[0].time - unixSeconds);
    for (const c of candles) {
      const diff = Math.abs(c.time - unixSeconds);
      if (diff < bestDiff) { best = c.time; bestDiff = diff; }
    }
    return best;
  }

  // Geen `title` hier: lightweight-charts tekent die tekst permanent naast
  // het laatste punt van de lijn, ongeacht lastValueVisible/priceLineVisible
  // (die twee onderdrukken alleen de as-badge en de horizontale lijn). EMA9
  // en EMA21 lopen per definitie vlak bij de actuele prijs, dus die twee
  // labels vielen daar altijd samen met de as-prijs en de laatste-koers-
  // lijn — precies de drukste plek van de grafiek, blijvend overlappend.
  // Kleur onderscheidt de twee lijnen al voldoende, geen tekst nodig.
  const ema9Series = chart.addLineSeries({
    color: "#17e5d6", lineWidth: 1, lastValueVisible: false, priceLineVisible: false,
  });
  const ema21Series = chart.addLineSeries({
    color: "#7d8c8a", lineWidth: 1, lastValueVisible: false, priceLineVisible: false,
  });

  // Een wig, driehoek, kanaal of trendlijn heeft schuine randen, geen platte
  // niveaus. Die twee punten als een horizontale zone tekenen (twee vlakke
  // lijnen) geeft een vorm die niets met het echte patroon te maken heeft.
  // De originele afbeelding hiernaast toont het patroon exact zoals het
  // getekend is, dus dit soort patronen wordt hier bewust niet nagebouwd,
  // alleen platte niveaus (support, retest, box, target) wel.
  const DIAGONAL_PATTERN_KEYWORDS = [
    "wig", "wedge", "driehoek", "triangle", "kanaal", "channel",
    "vlag", "flag", "trendlijn", "trendline",
  ];
  function isDiagonalPattern(name) {
    if (!name) return false;
    const lower = name.toLowerCase();
    return DIAGONAL_PATTERN_KEYWORDS.some((kw) => lower.includes(kw));
  }
  const chartableLevels = sourceLevels.filter((lvl) => !isDiagonalPattern(lvl.pattern_name));

  // Zones (bijvoorbeeld een "box" of "retest" gebied uit twee bij elkaar
  // horende niveaus) worden als vlak, doorzichtig blok over de grafiek
  // getekend, dat volgt op prijs mee als je in- of uitzoomt.
  const zoneGroups = groupLevelsByPattern(chartableLevels);
  const zoneEls = zoneGroups.map((group) => {
    const el = document.createElement("div");
    el.className = "chart-zone";
    el.innerHTML = `<span>${group.label}</span>`;
    container.appendChild(el);
    return { group, el };
  });

  // Minimale verticale ruimte tussen twee zone-labels (community of
  // zelf-gedetecteerd door elkaar) om te voorkomen dat twee zones die op
  // bijna dezelfde prijs liggen (heel gewoon: een SR-zone-rand is vaak
  // letterlijk de stop of take, dus een tweede zone vlak ernaast komt
  // regelmatig voor) hun labels over elkaar heen tekenen. Iets hoger dan
  // de labelhoogte zelf (11px tekst + 1px padding boven/onder + rand).
  const ZONE_LABEL_MIN_GAP = 20;

  // Standaard toont de grafiek alleen de zones/niveaus rond het meest
  // recente signaal (activeWindow, prijs ± 3x ATR) — de rest is oproepbaar
  // via de #toggle-all-layers-knop (showAllLayers). latestSignal en
  // activeWindow worden pas in de .then()-callback hieronder gevuld (ze
  // hebben de fetch-respons nodig), maar moeten hier al gedeclareerd staan
  // zodat positionZones()/applyLayerVisibility() ze veilig kunnen lezen,
  // ook als de knop al vóór de fetch is voltooid wordt aangeklikt.
  let showAllLayers = false;
  let latestSignal = null;
  let activeWindow = null;

  // Venster van de laatste 20 candles (prijsrange), gebruikt om een
  // zelf-gedetecteerde SR-zone die buiten activeWindow valt niet meteen
  // hard te verbergen maar te vervagen als hij tenminste nog "recent"
  // is: ergens binnen de prijsrange van wat er de laatste 20 candles is
  // gebeurd. Pas gevuld in de .then()-callback hieronder (heeft
  // data.candles nodig); tot die tijd blijft recent() false via de
  // Number.isFinite-guards, niet crashend op undefined-vergelijkingen.
  let recentLow = null;
  let recentHigh = null;

  function inActiveWindow(price) {
    if (!activeWindow) return true;
    return price >= activeWindow[0] && price <= activeWindow[1];
  }

  function positionZones() {
    const labels = [];
    zoneEls.forEach(({ group, el }) => {
      // De showAllLayers/activeWindow-check staat HIER, niet (ook) los in
      // applyLayerVisibility(): positionZones() draait ook rechtstreeks
      // vanaf pan/zoom/resize (de subscribe-aanroepen en de
      // ResizeObserver verderop), buiten applyLayerVisibility() om. Stond
      // de zichtbaarheidscheck alleen daar, dan zette elke pan of zoom een
      // verborgen zone stilzwijgend weer op "block" (priceToCoordinate
      // geeft hier bijna altijd een geldige coördinaat terug, ook voor een
      // zone ver buiten het huidige venster) en verdween het effect van de
      // knop bij de eerstvolgende interactie met de grafiek.
      if (!(showAllLayers || inActiveWindow((group.high + group.low) / 2))) {
        el.style.display = "none";
        return;
      }
      const yHigh = candleSeries.priceToCoordinate(group.high);
      const yLow = candleSeries.priceToCoordinate(group.low);
      if (yHigh === null || yLow === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${yHigh}px`;
      el.style.height = `${Math.max(yLow - yHigh, 2)}px`;
      // Label staat absoluut binnen de zone-div: zijn natuurlijke positie
      // op de pagina is de top van de zone-div (yHigh) plus zijn eigen
      // top (2px, uit de CSS-regel .chart-zone span).
      labels.push({ span: el.querySelector("span"), elTop: yHigh, naturalPageTop: yHigh + 2 });
    });
    srZoneEls.forEach(({ zone, el }) => {
      const mid = (zone.price_high + zone.price_low) / 2;
      const relevant = showAllLayers || inActiveWindow(mid);
      // recentLow/recentHigh zijn nog null vóór de fetch is opgelost; dan
      // is een zone per definitie niet "recent" (geen undefined-vergelijking).
      const recent = recentLow !== null && recentHigh !== null
        && mid >= recentLow && mid <= recentHigh;
      if (!relevant && !recent) {
        el.style.display = "none";
        return;
      }
      const yHigh = candleSeries.priceToCoordinate(zone.price_high);
      const yLow = candleSeries.priceToCoordinate(zone.price_low);
      if (yHigh === null || yLow === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${yHigh}px`;
      el.style.height = `${Math.max(yLow - yHigh, 2)}px`;
      // Niet-relevant maar wel recent: laten zien maar vervagen, in plaats
      // van hard verbergen (zie de comment bij recentLow/recentHigh
      // hierboven). toggle() zet de klasse ook weer AF zodra een zone weer
      // relevant wordt (bijv. na een nieuw signaal) — cruciaal: dit moet op
      // elke pass onvoorwaardelijk aangeroepen worden, niet alleen als
      // vervaagd, anders blijft een zone die weer relevant wordt vervaagd.
      el.classList.toggle("is-faded", !relevant && recent);
      labels.push({ span: el.querySelector("span"), elTop: yHigh, naturalPageTop: yHigh + 2 });
    });

    // Op paginahoogte sorteren en elk label dat te dicht op zijn voorganger
    // staat naar beneden duwen, zodat de labels een leesbare trap vormen
    // in plaats van op elkaar te liggen. Puur voor de labels, de zone-
    // blokken zelf (het doorzichtige vlak) blijven op hun echte prijshoogte.
    labels.sort((a, b) => a.naturalPageTop - b.naturalPageTop);
    let lastPageTop = -Infinity;
    labels.forEach(({ span, elTop, naturalPageTop }) => {
      if (!span) return;
      const pageTop = Math.max(naturalPageTop, lastPageTop + ZONE_LABEL_MIN_GAP);
      span.style.top = `${pageTop - elTop}px`;
      lastPageTop = pageTop;
    });
  }

  // showAllLayers is hierboven al gezet vóór het aanroepen; deze functie
  // is de enige plek die het toggelt en opnieuw laat renderen.
  // positionZones() past de zichtbaarheidscheck zelf al toe (zie de
  // comment daarin) zodat diezelfde regel ook bij pan/zoom/resize
  // overeind blijft, dus hier alleen doorgeven.
  function applyLayerVisibility() {
    positionZones();
  }

  // Een vaste 2-decimalen as-precisie (de standaard) is voor een coin onder
  // de €1 te grof: 0.09/0.10/0.11 verbergt dan het verschil tussen 0.087 en
  // 0.093. Precisie schalen met de prijs zelf, zoals de rest van het
  // dashboard al met %.4f/%.6f doet voor cijfers in tabellen.
  function pricePrecision(price) {
    if (price >= 100) return 2;
    if (price >= 1) return 4;
    if (price >= 0.1) return 5;
    if (price >= 0.01) return 6;
    return 8;
  }

  fetch(`/api/candles/${SYMBOL}`)
    .then((r) => r.json())
    .then((data) => {
      const lastPrice = data.candles.length ? data.candles[data.candles.length - 1].close : null;
      if (lastPrice) {
        const precision = pricePrecision(lastPrice);
        candleSeries.applyOptions({
          priceFormat: { type: "price", precision, minMove: 1 / Math.pow(10, precision) },
        });
      }
      candleSeries.setData(data.candles);
      ema9Series.setData(data.ema9);
      ema21Series.setData(data.ema21);

      // Een open trade (echt geld) krijgt altijd zijn eigen lijnen. Een
      // niet-genomen signaal alleen als er geen open trade is: met
      // meerdere signalen voor dezelfde coin stapelden de SL/TP-lijnen
      // van elk signaal boven op elkaar op, onleesbaar dicht tegen elkaar
      // aan de rechterkant. Eén set lijnen tegelijk, altijd de relevantste.
      openTrades.forEach((trade) => {
        addTradeLines(trade, `eigen trade ${trade.direction}`);
      });
      if (!openTrades.length && recentSignals.length) {
        const latest = recentSignals[0];
        addTradeLines(latest, `signaal ${latest.direction} (${latest.confidence})`);
      }

      // Venster rond het meest recente signaal (recentSignals is al
      // nieuwste-eerst gesorteerd, net als de rest van het dashboard).
      // Ontbreekt atr (oudere signalen, of nog niet berekend), dan geeft
      // de formule hieronder NaN, en elke NaN-vergelijking in
      // inActiveWindow() is altijd false — dat zou stilzwijgend ALLE
      // zones verbergen in plaats van ze allemaal te tonen. Zonder
      // bruikbare atr dus geen venster (null), zodat inActiveWindow()
      // terugvalt op "altijd zichtbaar".
      latestSignal = recentSignals[0];
      activeWindow = (latestSignal && Number.isFinite(latestSignal.atr) && latestSignal.atr)
        ? [latestSignal.price - 3 * latestSignal.atr, latestSignal.price + 3 * latestSignal.atr]
        : null;

      // Zie de comment bij de declaratie van recentLow/recentHigh
      // hierboven. "Oud" voor een zone zonder eigen tijdstip: buiten de
      // prijsrange van de laatste 20 candles.
      if (data.candles.length) {
        const recentCandles = data.candles.slice(-20);
        recentLow = Math.min(...recentCandles.map((c) => c.low));
        recentHigh = Math.max(...recentCandles.map((c) => c.high));
      }

      // Geen axis-label bij bron niveaus: bij dicht bij elkaar liggende
      // niveaus vallen die badges anders over elkaar heen en worden
      // onleesbaar. Alleen de lijn zelf blijft zichtbaar, de exacte
      // waarde staat in de lijst onder de grafiek.
      zoneGroups.forEach((group) => {
        candleSeries.createPriceLine({
          price: group.high, color: "#17e5d6", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: false,
        });
        candleSeries.createPriceLine({
          price: group.low, color: "#17e5d6", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: false,
        });
      });
      singleLevels(chartableLevels, zoneGroups).forEach((lvl) => {
        candleSeries.createPriceLine({
          price: lvl.price_level, color: "#17e5d6", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: false,
        });
      });

      if (narrativeUpdates.length && data.candles.length) {
        // LightweightCharts vereist markers oplopend gesorteerd op tijd;
        // narrativeUpdates komt binnen in narrative-volgorde (nieuwste
        // narrative eerst), niet chronologisch, dus zonder deze sort
        // vallen markers afhankelijk van zoom/scroll stilzwijgend weg.
        narrativeMarkers = narrativeUpdates
          .map((u) => ({
            time: nearestCandleTime(data.candles, Math.floor(new Date(u.received_at).getTime() / 1000)),
            position: "aboveBar",
            color: u.direction === "long" ? "#33d69f" : "#f2685c",
            shape: "circle",
            text: u.direction === "long" ? "L" : "S",
          }))
          .sort((a, b) => a.time - b.time);
      }

      // Patroon-markers uit dezelfde /api/candles respons, samengevoegd
      // met narrativeMarkers vóór de ENE setMarkers()-aanroep hieronder
      // (zie de comment bij de declaratie van narrativeMarkers hierboven).
      const patternMarkers = (data.patterns || []).map((p) => ({
        time: p.time,
        position: p.direction === "bullish" ? "belowBar" : "aboveBar",
        color: p.direction === "bullish" ? "#33d69f" : "#f2685c",
        shape: "circle",
        text: "",
      }));
      narrativeMarkers = [...narrativeMarkers, ...patternMarkers].sort((a, b) => a.time - b.time);
      if (narrativeMarkers.length) {
        candleSeries.setMarkers(narrativeMarkers);
      }

      const patternListEl = document.getElementById("pattern-list");
      if (patternListEl) {
        if (data.patterns && data.patterns.length) {
          const sorted = [...data.patterns].sort((a, b) => b.time - a.time).slice(0, 10);
          patternListEl.innerHTML = sorted.map((p) => {
            // Tijdstip inclusief uur: op een 4u-grafiek zijn er 6 candles per
            // dag, dus alleen een datum laat niet zien welke candle bedoeld
            // wordt. Richting ook als tekst (niet alleen kleur) zodat het
            // ook zonder kleuronderscheid duidelijk is.
            const date = new Date(p.time * 1000).toLocaleDateString("nl-NL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
            const cls = p.direction === "bullish" ? "pos" : "neg";
            const richting = p.direction === "bullish" ? "↑ bullish" : "↓ bearish";
            return `<p class="muted" style="margin: 4px 0; font-size: 12.5px;"><span class="${cls}">${p.pattern}</span> (${richting}) · ${date}</p>`;
          }).join("");
        } else {
          patternListEl.innerHTML = '<p class="muted">Geen patronen herkend in de laatste 100 candles.</p>';
        }
      }

      // Eén blok per zelf-gedetecteerde zone, in een eigen kleur
      // (chart-zone-sr) om ze te onderscheiden van de teal community-
      // niveau-zones hierboven. Sterkte (touches) als klein label op de
      // zone zelf, geen aparte lijst nodig zoals bij de candlestick-
      // patronen: een zone is als vlak al zichtbaar genoeg.
      srZoneEls = (data.sr_zones || []).map((zone) => {
        const el = document.createElement("div");
        const highlighted = isHighlightedZone(zone);
        el.className = highlighted ? "chart-zone-sr chart-zone-sr-highlight" : "chart-zone-sr";
        el.innerHTML = highlighted
          ? `<span>🎯 gemelde zone · ${zone.touches}x getest</span>`
          : `<span>${zone.touches}x getest</span>`;
        container.appendChild(el);
        return { zone, el, highlighted };
      });

      // Trendlijnen (indicators.detect_trendlines, via het trendlines-veld
      // van /api/candles): een diagonale lijn past niet in het
      // .chart-zone-sr-blok (vaste top/hoogte), dus een eigen
      // lightweight-charts lijnserie per lijn. Violet (#a78bfa), niet
      // amber: amber (.chart-zone-sr-highlight) betekent specifiek "dit is
      // DE zone uit de melding die je hier bekeek", maar
      // detect_trendlines kan tot twee lijnen tegelijk teruggeven zonder
      // enige aanduiding welke (als een van beide) die melding was.
      // Violet is dezelfde kleur als de zelf-gedetecteerde horizontale
      // SR-zones (.chart-zone-sr): "auto-gedetecteerd", niet "dit is HET".
      (data.trendlines || []).forEach((line) => {
        const series = chart.addLineSeries({
          color: "#a78bfa", lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
        });
        // /api/candles noemt het veld "price" (zelfde naam als overal
        // elders in deze respons, bv. sr_zones), maar lightweight-charts'
        // LineData verwacht "value" — zonder deze mapping accepteert
        // setData de punten stilzwijgend (geen foutmelding) en tekent
        // niets, want elke waarde is dan undefined.
        series.setData(line.points.map((p) => ({ time: p.time, value: p.price })));
      });

      chart.timeScale().fitContent();
      positionZones();
      applyLayerVisibility();

      const loadingEl = document.getElementById("chart-loading");
      if (loadingEl) loadingEl.remove();
    })
    .catch(() => {
      const loadingEl = document.getElementById("chart-loading");
      if (loadingEl) {
        loadingEl.classList.add("chart-error");
        loadingEl.querySelector("p").textContent = "Koersdata kon niet geladen worden. Ververs de pagina om het opnieuw te proberen.";
      }
      const patternListEl = document.getElementById("pattern-list");
      if (patternListEl) {
        patternListEl.innerHTML = '<p class="muted">Kon niet geladen worden.</p>';
      }
    });

  function addTradeLines(trade, label) {
    if (trade.entry_price) {
      candleSeries.createPriceLine({
        price: trade.entry_price, color: "#eaf1f0", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Solid, title: label,
      });
    }
    if (trade.stop_loss) {
      candleSeries.createPriceLine({
        price: trade.stop_loss, color: "#f2685c", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Solid, title: "stop loss",
      });
    }
    if (trade.take_profit) {
      candleSeries.createPriceLine({
        price: trade.take_profit, color: "#33d69f", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Solid, title: "take profit",
      });
    }
  }

  function groupLevelsByPattern(levels) {
    const byName = {};
    levels.forEach((lvl) => {
      if (!lvl.pattern_name) return;
      const key = lvl.pattern_name.toLowerCase();
      (byName[key] = byName[key] || []).push(lvl);
    });
    return Object.values(byName)
      .filter((group) => group.length >= 2)
      .map((group) => {
        const prices = group.map((g) => g.price_level);
        return { label: group[0].pattern_name, high: Math.max(...prices), low: Math.min(...prices) };
      });
  }

  function singleLevels(levels, groups) {
    const groupedNames = new Set(groups.map((g) => g.label.toLowerCase()));
    return levels.filter((lvl) => !lvl.pattern_name || !groupedNames.has(lvl.pattern_name.toLowerCase()));
  }

  chart.timeScale().subscribeVisibleTimeRangeChange(positionZones);
  chart.timeScale().subscribeVisibleLogicalRangeChange(positionZones);

  if (window.ResizeObserver) {
    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      if (width > 0 && height > 0) {
        chart.applyOptions({ width, height });
        positionZones();
      }
    });
    resizeObserver.observe(container);
  } else {
    window.addEventListener("resize", () => {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
      positionZones();
    });
  }

  // Zelf een schuine lijn tekenen (wig, driehoek, kanaal): de automatische
  // toetsing kan dat niet naberekenen, en het bronscreenshot ernaast toont
  // het patroon wel maar staat los van de live grafiek. Twee klikken op de
  // grafiek leggen de twee eindpunten vast; de lijn is daarna een gewone
  // lijnserie tussen die twee punten, en wordt gedeeld met iedereen die
  // deze coin bekijkt, net als de bron niveaus.
  (function () {
    const drawBtn = document.getElementById("draw-trendline-btn");
    const drawBtnLabel = document.getElementById("draw-trendline-label");
    const hintEl = document.getElementById("draw-trendline-hint");
    const listEl = document.getElementById("trendline-list");
    if (!drawBtn || !hintEl || !listEl) return;

    const lineSeriesById = {};
    let drawMode = false;
    let pendingPoint = null;

    function setHint(text) {
      if (text) { hintEl.textContent = text; hintEl.hidden = false; }
      else { hintEl.hidden = true; }
    }

    function stopDrawing() {
      drawMode = false;
      pendingPoint = null;
      drawBtn.classList.remove("is-active");
      if (drawBtnLabel) drawBtnLabel.textContent = "Lijn";
      container.classList.remove("is-drawing");
      setHint(null);
      candleSeries.setMarkers(narrativeMarkers);
      chart.applyOptions({
        handleScroll: true,
        handleScale: true,
      });
    }

    function drawLine(t) {
      const series = chart.addLineSeries({
        color: "#c084fc", lineWidth: 2, lastValueVisible: false,
        priceLineVisible: false, crosshairMarkerVisible: false,
      });
      series.setData([{ time: t.x1, value: t.y1 }, { time: t.x2, value: t.y2 }]);
      lineSeriesById[t.id] = series;
    }

    function removeTrendline(id) {
      fetch(`/trendlines/${id}/delete`, { method: "POST" })
        .then(() => {
          if (lineSeriesById[id]) {
            chart.removeSeries(lineSeriesById[id]);
            delete lineSeriesById[id];
          }
          const idx = trendlines.findIndex((t) => t.id === id);
          if (idx !== -1) trendlines.splice(idx, 1);
          renderList();
        })
        .catch(() => {});
    }

    function renderList() {
      listEl.innerHTML = "";
      trendlines.forEach((t) => {
        const chip = document.createElement("span");
        chip.className = "trendline-chip";
        chip.appendChild(document.createTextNode(t.label || "eigen lijn"));
        if (t.user_id === CURRENT_USER_ID) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "trendline-remove";
          btn.setAttribute("aria-label", "Lijn verwijderen");
          btn.textContent = "×";
          btn.addEventListener("click", () => removeTrendline(t.id));
          chip.appendChild(btn);
        }
        listEl.appendChild(chip);
      });
    }

    drawBtn.addEventListener("click", () => {
      if (drawMode) { stopDrawing(); return; }
      drawMode = true;
      pendingPoint = null;
      drawBtn.classList.add("is-active");
      if (drawBtnLabel) drawBtnLabel.textContent = "Annuleren";
      container.classList.add("is-drawing");
      // Zonder dit wordt een tik op mobiel (en soms ook een muisklik met een
      // paar pixels beweging) door de grafiek zelf als slepen/zoomen gezien,
      // en komt subscribeClick nooit af: de grafiek schuift dan in plaats
      // van dat er een punt gezet wordt. Pas terug aan zodra tekenen stopt.
      chart.applyOptions({
        handleScroll: false,
        handleScale: false,
      });
      setHint("Klik het eerste punt van de lijn");
    });

    chart.subscribeClick((param) => {
      if (!drawMode || !param.point || param.time === undefined) return;
      const price = candleSeries.coordinateToPrice(param.point.y);
      if (price === null) return;

      if (!pendingPoint) {
        pendingPoint = { time: param.time, value: price };
        // Direct zichtbare bevestiging op de grafiek zelf dat de eerste klik
        // geregistreerd is, niet alleen een tekstwijziging boven de grafiek
        // die makkelijk over het hoofd gezien wordt.
        candleSeries.setMarkers([{
          time: param.time, position: "inBar", color: "#c084fc", shape: "circle", text: "1",
        }]);
        setHint("Punt 1 gezet. Klik nu het tweede punt van de lijn.");
        return;
      }

      const p1 = pendingPoint;
      const p2 = { time: param.time, value: price };
      stopDrawing();
      if (p1.time === p2.time) return; // zelfde candle aangeklikt, geen lijn om te trekken

      const [a, b] = p1.time < p2.time ? [p1, p2] : [p2, p1];
      const label = `lijn ${trendlines.length + 1}`;
      fetch(`/coins/${SYMBOL}/trendlines`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ x1: a.time, y1: a.value, x2: b.time, y2: b.value, label }),
      })
        .then((r) => r.json())
        .then((res) => {
          const t = { id: res.id, x1: a.time, y1: a.value, x2: b.time, y2: b.value, label, user_id: CURRENT_USER_ID };
          trendlines.push(t);
          drawLine(t);
          renderList();
        })
        .catch(() => {});
    });

    trendlines.forEach(drawLine);
    renderList();
  })();

  const toggleBtn = document.getElementById("toggle-all-layers");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      showAllLayers = !showAllLayers;
      toggleBtn.textContent = showAllLayers ? "Alleen actueel signaal" : "Alle niveaus tonen";
      applyLayerVisibility();
    });
  }
})();

(function () {
  // Live rekenhulp op het oefentrade-formulier: laat vooraf zien welke
  // positie een risicobedrag oplevert en of die door de evaluatie-
  // hefboomlimiet wordt afgekapt, in plaats van dat pas na het aanmaken
  // op de trade-kaart te ontdekken. Zelfde berekening als de server bij
  // het echte aanmaken (_fetch_practice_trade_calc/_resolve_practice_risk_eur
  // in web/main.py), dus de preview kan nooit afwijken van het resultaat.
  const form = document.getElementById("oefen-form");
  const directionSelect = document.getElementById("oefen-direction");
  const riskInput = document.getElementById("oefen-risk-eur");
  const previewEl = document.getElementById("oefen-preview");
  if (!form || !directionSelect || !riskInput || !previewEl) return;

  let debounceTimer = null;
  let requestSeq = 0;

  function formatEur(value) {
    return "€" + Number(value).toLocaleString("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function runPreview() {
    const seq = ++requestSeq;
    previewEl.textContent = "Berekenen…";
    fetch(`/coins/${SYMBOL}/oefen-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ direction: directionSelect.value, risk_eur: riskInput.value }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (seq !== requestSeq) return; // een nieuwere aanvraag is al onderweg, deze respons is verouderd
        if (data.error) { previewEl.textContent = ""; return; }
        const notional = data.notional_eur !== null ? formatEur(data.notional_eur) : "-";
        const coinLabel = SYMBOL.replace("USDT", "");
        let text = `Positie ≈ ${data.position_size !== null ? data.position_size.toFixed(6) : "-"} ${coinLabel} (${notional} notioneel), risico ${formatEur(data.used_risk_eur)}.`;
        if (data.capped) {
          text += ` Automatisch beperkt tot de hefboomlimiet van de evaluatie (max ${formatEur(data.max_risk_eur)} risico).`;
        }
        previewEl.textContent = text;
      })
      .catch(() => { if (seq === requestSeq) previewEl.textContent = ""; });
  }

  function scheduleRunPreview() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runPreview, 500);
  }

  directionSelect.addEventListener("change", scheduleRunPreview);
  riskInput.addEventListener("input", scheduleRunPreview);
})();
