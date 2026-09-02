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
        borderColor: "#17e5d6",
        backgroundColor: "rgba(23, 229, 214, 0.12)",
        fill: true,
        tension: 0.1,
      }],
    },
    options: {
      scales: {
        x: { ticks: { color: "#7d8c8a" }, grid: { color: "#1c2526" } },
        y: { ticks: { color: "#7d8c8a" }, grid: { color: "#1c2526" } },
      },
      plugins: { legend: { labels: { color: "#eaf1f0" } } },
    },
  });
})();
