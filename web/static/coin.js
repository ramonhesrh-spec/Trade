(function () {
  const container = document.getElementById("chart");
  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#ffffff" }, textColor: "#1a1a1a" },
    grid: { vertLines: { color: "#e1e8e7" }, horzLines: { color: "#e1e8e7" } },
    timeScale: { timeVisible: true },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#2f855a", downColor: "#c53030",
    borderVisible: false, wickUpColor: "#2f855a", wickDownColor: "#c53030",
  });
  const ema9Series = chart.addLineSeries({ color: "#0ABAB5", lineWidth: 1, title: "EMA9" });
  const ema21Series = chart.addLineSeries({ color: "#6b7280", lineWidth: 1, title: "EMA21" });

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

  fetch(`/api/candles/${SYMBOL}`)
    .then((r) => r.json())
    .then((data) => {
      candleSeries.setData(data.candles);
      ema9Series.setData(data.ema9);
      ema21Series.setData(data.ema21);

      openTrades.forEach((trade) => {
        addTradeLines(trade, `eigen trade ${trade.direction}`);
      });
      recentSignals.forEach((signal) => {
        addTradeLines(signal, `signaal ${signal.direction} (${signal.confidence})`);
      });

      zoneGroups.forEach((group) => {
        candleSeries.createPriceLine({
          price: group.high, color: "#0ABAB5", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed, title: group.label,
        });
        candleSeries.createPriceLine({
          price: group.low, color: "#0ABAB5", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed, title: "",
        });
      });
      singleLevels(sourceLevels, zoneGroups).forEach((lvl) => {
        candleSeries.createPriceLine({
          price: lvl.price_level, color: "#0ABAB5", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: lvl.pattern_name || "",
        });
      });

      chart.timeScale().fitContent();
      positionZones();
    });

  function addTradeLines(trade, label) {
    if (trade.entry_price) {
      candleSeries.createPriceLine({
        price: trade.entry_price, color: "#1a1a1a", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Solid, title: label,
      });
    }
    if (trade.stop_loss) {
      candleSeries.createPriceLine({
        price: trade.stop_loss, color: "#c53030", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Solid, title: "stop loss",
      });
    }
    if (trade.take_profit) {
      candleSeries.createPriceLine({
        price: trade.take_profit, color: "#2f855a", lineWidth: 1,
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

  window.addEventListener("resize", () => {
    chart.applyOptions({ width: container.clientWidth });
    positionZones();
  });
})();
