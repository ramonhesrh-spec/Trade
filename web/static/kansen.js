// Een kans in beweging: ververst de afstand op Setups en Vandaag en laat stap 1 pulseren zodra de koers dichtbij is.
// Zonder JS blijft de pagina een gewone, server-gerenderde pagina. Stopt zolang het tabblad verborgen is.
(function () {
  var NEAR_PCT = 0.5, POLL_MS = 15000;

  function markNear() {
    document.querySelectorAll(".vd-step.is-now").forEach(function (li) {
      var span = li.querySelector('[data-vd="distance"], [data-radar="distance"]');
      if (!span) return;
      var v = parseFloat(span.textContent.replace(",", "."));
      li.classList.toggle("is-near", !isNaN(v) && Math.abs(v) <= NEAR_PCT);
    });
  }

  function apply(payload) {
    Object.keys(payload.structuur || {}).forEach(function (id) {
      var card = document.getElementById("structuur-" + id);
      if (!card) return;
      var span = card.querySelector('[data-vd="distance"]');
      if (!span) return;
      span.textContent = payload.structuur[id].dist;
      if (span.parentElement && span.parentElement.hasAttribute("hidden")) span.parentElement.removeAttribute("hidden");
    });
    markNear();
  }

  function refresh() {
    if (document.hidden || !document.querySelector(".setup-card")) return;
    fetch("/api/kansen", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) { if (p) apply(p); })
      .catch(function () {});
  }

  markNear();
  setInterval(markNear, 3000);
  setInterval(refresh, POLL_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
