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
  const ema9Series = chart.addLineSeries({
    color: "#17e5d6", lineWidth: 1, title: "EMA9", lastValueVisible: false, priceLineVisible: false,
  });
  const ema21Series = chart.addLineSeries({
    color: "#7d8c8a", lineWidth: 1, title: "EMA21", lastValueVisible: false, priceLineVisible: false,
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
  // Een niveau dat als "klopt niet" is aangevinkt (zie de lijst onder de
  // grafiek) staat er soms gewoon naast en hoort niet meer in de grafiek
  // te staan, ook al blijft het in de lijst zelf zichtbaar als geschiedenis.
  const chartableLevels = sourceLevels.filter((lvl) => !isDiagonalPattern(lvl.pattern_name) && !lvl.dismissed);

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

  function positionZones() {
    zoneEls.forEach(({ group, el }) => {
      const yHigh = candleSeries.priceToCoordinate(group.high);
      const yLow = candleSeries.priceToCoordinate(group.low);
      if (yHigh === null || yLow === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${yHigh}px`;
      el.style.height = `${Math.max(yLow - yHigh, 2)}px`;
    });
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

      openTrades.forEach((trade) => {
        addTradeLines(trade, `eigen trade ${trade.direction}`);
      });
      recentSignals.forEach((signal) => {
        addTradeLines(signal, `signaal ${signal.direction} (${signal.confidence})`);
      });

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

      chart.timeScale().fitContent();
      positionZones();

      const loadingEl = document.getElementById("chart-loading");
      if (loadingEl) loadingEl.remove();
    })
    .catch(() => {
      const loadingEl = document.getElementById("chart-loading");
      if (!loadingEl) return;
      loadingEl.classList.add("chart-error");
      loadingEl.querySelector("p").textContent = "Koersdata kon niet geladen worden. Ververs de pagina om het opnieuw te proberen.";
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
      drawBtn.textContent = "+ Lijn tekenen";
      container.classList.remove("is-drawing");
      setHint(null);
      candleSeries.setMarkers([]);
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
      drawBtn.textContent = "Annuleren";
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

  // Bron niveaus aanvinken als "klopt niet": verbergt het niveau meteen uit
  // de grafiek (voor iedereen, het is één gedeeld oordeel) en toont de rij
  // in de lijst hieronder doorgestreept, zonder paginaherlaad.
  (function () {
    const table = document.getElementById("source-levels-table");
    if (!table) return;

    table.addEventListener("click", (event) => {
      const btn = event.target.closest(".level-dismiss-btn, .level-restore-btn");
      if (!btn) return;
      const dismiss = btn.classList.contains("level-dismiss-btn");
      const levelId = btn.dataset.levelId;
      btn.disabled = true;

      // Een niveau kan onderdeel zijn van een gegroepeerde zone (box,
      // meerdere punten samen), dus de grafiek boven de lijst opnieuw laten
      // opbouwen na een wijziging is simpeler en betrouwbaarder dan zelf
      // precies bijhouden welke lijn(en)/zone bij welk niveau hoorden.
      fetch(`/source-levels/${levelId}/${dismiss ? "dismiss" : "restore"}`, { method: "POST" })
        .then((r) => {
          if (r.ok) { location.reload(); return; }
          btn.disabled = false;
          if (window.HP) window.HP.progressDone();
        })
        .catch(() => {
          btn.disabled = false;
          if (window.HP) window.HP.progressDone();
        });
    });
  })();
})();
