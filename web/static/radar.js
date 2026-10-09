/* Live verversing van de Trade Radar: haalt elke 15 seconden /api/radar op en werkt per kaart de status, afstand,
   live R en de strook met R:R bij. De eerste weergave komt gewoon van de server; zonder JS blijft de pagina volledig bruikbaar.
   Stopt zolang het tabblad verborgen is, zodat een vergeten tabblad geen koersen blijft ophalen. */
(function () {
  var INTERVAL_MS = 15000;
  var cards = document.querySelectorAll("[data-radar-key]");
  if (!cards.length) return;

  function setText(card, name, text) {
    var el = card.querySelector('[data-radar="' + name + '"]');
    if (el) el.textContent = text;
  }

  function apply(payload) {
    cards.forEach(function (card) {
      var data = payload[card.getAttribute("data-radar-key")];
      if (!data) return;
      var state = card.querySelector('[data-radar="state"]');
      if (state) {
        state.textContent = data.label;
        state.className = "radar-state radar-state-" + (data.state || "laden");
      }
      // Doel gehaald terwijl de pagina openstaat: strook en stappen verdwijnen, de rest van de kaart komt bij de volgende paginaweergave.
      card.classList.toggle("is-moot", data.state === "doel_geraakt");
      if (!(window.hesLiveFresh && window.hesLiveFresh()) && data.distance_pct !== null && data.distance_pct !== undefined) {
        setText(card, "distance", (data.distance_pct >= 0 ? "+" : "") + data.distance_pct.toFixed(2) + "%");
      }
      var r = card.querySelector('[data-radar="live_r"]');
      if (r && data.live_r !== null && data.live_r !== undefined) {
        r.textContent = (data.live_r >= 0 ? "+" : "") + data.live_r.toFixed(2) + "R";
        r.className = "radar-r " + (data.live_r > 0 ? "pos" : data.live_r < 0 ? "neg" : "");
      }
      var bar = card.querySelector(".r-progress");
      var mark = card.querySelector('[data-radar="progress"]');
      if (bar && mark && data.live_r !== null && data.live_r !== undefined) {
        var rr = parseFloat(bar.getAttribute("data-rr"));
        mark.style.left = Math.max(0, Math.min(100, (data.live_r + 1) / (rr + 1) * 100)).toFixed(1) + "%";
        mark.className = "r-progress-mark" + (data.live_r > 0 ? " pos" : data.live_r < 0 ? " neg" : "");
      }
      var ladder = card.querySelector('[data-radar="ladder"]');
      if (ladder && data.ladder) window.hesStripSwap(ladder, data.ladder);
    });
  }

  function refresh() {
    if (document.hidden) return;
    fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (payload) { if (payload) apply(payload); })
      .catch(function () { /* een mislukte verversing laat de laatste stand staan */ });
  }

  setInterval(refresh, INTERVAL_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
