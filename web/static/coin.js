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

  fetch(`/api/candles/${SYMBOL}`)
    .then((r) => r.json())
    .then((data) => {
      candleSeries.setData(data.candles);
      ema9Series.setData(data.ema9);
      ema21Series.setData(data.ema21);

      openTrades.forEach((trade) => {
        candleSeries.createPriceLine({
          price: trade.entry_price, color: "#1a1a1a", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Solid, title: `entry ${trade.direction}`,
        });
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
      });

      sourceLevels.forEach((lvl) => {
        candleSeries.createPriceLine({
          price: lvl.price_level, color: "#0ABAB5", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: lvl.pattern_name || "",
        });
      });

      chart.timeScale().fitContent();
    });

  window.addEventListener("resize", () => {
    chart.applyOptions({ width: container.clientWidth });
  });
})();
