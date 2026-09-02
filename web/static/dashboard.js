(function () {
  const ctx = document.getElementById("cumulative-chart");
  if (!ctx) return;

  new Chart(ctx, {
    type: "line",
    data: {
      labels: cumulativeData.map((p) => p.time.slice(0, 10)),
      datasets: [{
        label: "Cumulatief resultaat (euro)",
        data: cumulativeData.map((p) => p.cumulative_eur),
        borderColor: "#4d8dff",
        backgroundColor: "rgba(77, 141, 255, 0.15)",
        fill: true,
        tension: 0.1,
      }],
    },
    options: {
      scales: {
        x: { ticks: { color: "#8a8f9a" }, grid: { color: "#2a2e38" } },
        y: { ticks: { color: "#8a8f9a" }, grid: { color: "#2a2e38" } },
      },
      plugins: { legend: { labels: { color: "#e6e8eb" } } },
    },
  });
})();
