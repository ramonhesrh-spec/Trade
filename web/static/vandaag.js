/* Live verversing van Vandaag: haalt elke 15 seconden /api/vandaag op en werkt koersen en per scenario status, afstand,
   resterende tijd en ladder bij. De eerste weergave komt van de server; zonder JS blijft de pagina volledig bruikbaar.
   Stopt zolang het tabblad verborgen is. */
(function () {
  var INTERVAL_MS = 15000;
  if (!document.querySelector("[data-vd-price]")) return;

  function fmtPrice(value, coin) {
    if (value === null || value === undefined) return "";
    if (coin === "BTC") return Math.round(value).toLocaleString("nl-NL");
    return value < 100 ? value.toFixed(4) : value.toFixed(2);
  }

  function apply(payload) {
    document.querySelectorAll("[data-vd-price]").forEach(function (el) {
      var coin = el.getAttribute("data-vd-price");
      var text = fmtPrice(payload.prices[coin], coin);
      if (text) el.textContent = text;
    });
    document.querySelectorAll("[data-vd-scenario]").forEach(function (el) {
      var data = payload.scenarios[el.getAttribute("data-vd-scenario")];
      if (!data) return;
      var state = el.querySelector('[data-vd="state"]');
      if (state) state.textContent = data.label;
      el.className = el.className.replace(/vd-scenario-\w+/, "vd-scenario-" + data.state);
      var dist = el.querySelector('[data-vd="distance"]');
      if (dist) dist.textContent = data.to_trigger_pct === null ? "-" : (data.to_trigger_pct >= 0 ? "+" : "") + data.to_trigger_pct.toFixed(2) + "%";
      var left = el.querySelector('[data-vd="left"]');
      if (left) left.textContent = Math.round(data.hours_left);
      var ladder = el.querySelector('[data-vd="ladder"]');
      if (ladder && data.ladder) ladder.innerHTML = data.ladder;
    });
  }

  function refresh() {
    if (document.hidden) return;
    fetch("/api/vandaag", { cache: "no-store", credentials: "same-origin" })
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (payload) { if (payload) apply(payload); })
      .catch(function () { /* een mislukte verversing laat de laatste stand staan */ });
  }

  setInterval(refresh, INTERVAL_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
