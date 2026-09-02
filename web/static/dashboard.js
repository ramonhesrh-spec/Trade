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

// Live prijs en PnL van open posities, elke 20 seconden bijgewerkt zonder
// de pagina opnieuw te laden.
(function () {
  const priceEls = document.querySelectorAll("[data-price]");
  if (!priceEls.length) return;

  function refresh() {
    fetch("/api/open_positions")
      .then((r) => r.json())
      .then((positions) => {
        positions.forEach((p) => {
          const priceEl = document.querySelector(`[data-price="${p.id}"]`);
          const pnlEl = document.querySelector(`[data-pnl="${p.id}"]`);
          const pnlPctEl = document.querySelector(`[data-pnl-pct="${p.id}"]`);
          if (priceEl && p.current_price !== null) {
            priceEl.textContent = p.current_price.toFixed(4);
          }
          if (pnlEl && p.pnl_eur !== null) {
            pnlEl.firstChild.textContent = `€${p.pnl_eur.toFixed(2)} `;
            pnlEl.classList.toggle("pos", p.pnl_eur >= 0);
            pnlEl.classList.toggle("neg", p.pnl_eur < 0);
          }
          if (pnlPctEl) {
            pnlPctEl.textContent = `(${p.pnl_pct.toFixed(1)}%)`;
          }
        });
      })
      .catch(() => {});
  }

  refresh();
  setInterval(refresh, 20000);
})();
