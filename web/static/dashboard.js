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
        borderColor: "#0ABAB5",
        backgroundColor: "rgba(10, 186, 181, 0.12)",
        fill: true,
        tension: 0.1,
      }],
    },
    options: {
      scales: {
        x: { ticks: { color: "#6b7280" }, grid: { color: "#e1e8e7" } },
        y: { ticks: { color: "#6b7280" }, grid: { color: "#e1e8e7" } },
      },
      plugins: { legend: { labels: { color: "#1a1a1a" } } },
    },
  });
})();
