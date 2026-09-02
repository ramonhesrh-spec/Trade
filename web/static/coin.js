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
})();
