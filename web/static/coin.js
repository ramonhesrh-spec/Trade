(function () {
  const container = document.getElementById("chart");
  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#131a1b" }, textColor: "#b7c4c2" },
    grid: { vertLines: { color: "#1c2526" }, horzLines: { color: "#1c2526" } },
    timeScale: { timeVisible: true, borderColor: "#232d2f" },
    rightPriceScale: { borderColor: "#232d2f" },
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

  // Zones (bijvoorbeeld een "box" of "retest" gebied uit twee bij elkaar
  // horende niveaus) worden als vlak, doorzichtig blok over de grafiek
  // getekend, dat volgt op prijs mee als je in- of uitzoomt.
  const zoneGroups = groupLevelsByPattern(sourceLevels);
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

  // Schuine patroonlijnen (trendlijn, wig, driehoekzijde): de bron geeft
  // twee punten met een geschatte "dagen geleden", die tekenen we tegen
  // onze eigen echte tijdas, geankerd op de meest recente candle.
  const trendlineEls = [];

  function renderTrendlines(latestTime) {
    trendlines.forEach((tl) => {
      const d1 = Math.max(0, tl.point1_days_ago || 0);
      const d2 = Math.max(0, tl.point2_days_ago || 0);
      if (d1 === d2) return; // twee punten op dezelfde tijd is geen lijn

      const points = [
        { time: latestTime - d1 * 86400, value: tl.point1_price },
        { time: latestTime - d2 * 86400, value: tl.point2_price },
      ].sort((a, b) => a.time - b.time);

      const series = chart.addLineSeries({
        color: "#f2b03e", lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dashed,
        lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
      });
      series.setData(points);

      const el = document.createElement("div");
      el.className = "chart-zone";
      el.style.background = "none";
      el.style.borderTop = "none";
      el.style.borderBottom = "none";
      el.innerHTML = `<span style="color:#f2b03e;">${tl.label || "trendlijn"}</span>`;
      container.appendChild(el);
      trendlineEls.push({ series, point: points[points.length - 1], el });
    });
  }

  function positionTrendlineLabels() {
    trendlineEls.forEach(({ series, point, el }) => {
      const y = series.priceToCoordinate(point.value);
      const x = chart.timeScale().timeToCoordinate(point.time);
      if (y === null || x === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${y - 18}px`;
      el.style.left = `${x + 6}px`;
      el.style.right = "auto";
    });
  }

  // Genoeg historie opvragen om de oudste trendlijn ook echt in beeld te
  // krijgen, anders valt het beginpunt buiten de geladen candles en trekt
  // de lijn krom.
  const maxDaysAgo = trendlines.reduce(
    (max, tl) => Math.max(max, tl.point1_days_ago || 0, tl.point2_days_ago || 0), 0,
  );

  fetch(`/api/candles/${SYMBOL}?days=${Math.ceil(maxDaysAgo) + 3}`)
    .then((r) => r.json())
    .then((data) => {
      candleSeries.setData(data.candles);
      ema9Series.setData(data.ema9);
      ema21Series.setData(data.ema21);

      if (data.candles.length) {
        renderTrendlines(data.candles[data.candles.length - 1].time);
      }

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
      singleLevels(sourceLevels, zoneGroups).forEach((lvl) => {
        candleSeries.createPriceLine({
          price: lvl.price_level, color: "#17e5d6", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: false,
        });
      });

      chart.timeScale().fitContent();
      positionZones();
      positionTrendlineLabels();
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
  chart.timeScale().subscribeVisibleTimeRangeChange(positionTrendlineLabels);
  chart.timeScale().subscribeVisibleLogicalRangeChange(positionTrendlineLabels);

  window.addEventListener("resize", () => {
    chart.applyOptions({ width: container.clientWidth });
    positionZones();
    positionTrendlineLabels();
  });
})();
