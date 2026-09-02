(function () {
  const container = document.getElementById("chart");
  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#0f1115" }, textColor: "#e6e8eb" },
    grid: { vertLines: { color: "#2a2e38" }, horzLines: { color: "#2a2e38" } },
    timeScale: { timeVisible: true },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#2ecc71", downColor: "#e74c3c",
    borderVisible: false, wickUpColor: "#2ecc71", wickDownColor: "#e74c3c",
  });
  const ema9Series = chart.addLineSeries({ color: "#4d8dff", lineWidth: 1, title: "EMA9" });
  const ema21Series = chart.addLineSeries({ color: "#f5a623", lineWidth: 1, title: "EMA21" });

  fetch(`/api/candles/${SYMBOL}`)
    .then((r) => r.json())
    .then((data) => {
      candleSeries.setData(data.candles);
      ema9Series.setData(data.ema9);
      ema21Series.setData(data.ema21);

      openTrades.forEach((trade) => {
        candleSeries.createPriceLine({
          price: trade.entry_price, color: "#8a8f9a", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Solid, title: `entry ${trade.direction}`,
        });
        if (trade.stop_loss) {
          candleSeries.createPriceLine({
            price: trade.stop_loss, color: "#e74c3c", lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Solid, title: "stop loss",
          });
        }
        if (trade.take_profit) {
          candleSeries.createPriceLine({
            price: trade.take_profit, color: "#2ecc71", lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Solid, title: "take profit",
          });
        }
      });

      sourceLevels.forEach((lvl) => {
        candleSeries.createPriceLine({
          price: lvl.price_level, color: "#f5a623", lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          title: `analyse Discord${lvl.pattern_name ? ": " + lvl.pattern_name : ""}`,
        });
      });

      chart.timeScale().fitContent();
    });

  window.addEventListener("resize", () => {
    chart.applyOptions({ width: container.clientWidth });
  });
})();
