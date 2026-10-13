// Stip in de bovenbalk: groen zolang de getoonde koersen vers zijn, oranje als de nieuwste koers ouder is dan data-stale-after seconden
// (freshness.STALE_AFTER_S). Bron is de koersstroom van de beurs (live.js zet window.__liveAt) of de leeftijd die de server bij een poll
// meestuurt (X-Price-Age). Op pagina's zonder koersen blijft de stip verborgen.
(function (root) {
  function state(freshestAt, now, staleMs) {
    if (freshestAt === null || freshestAt === undefined) return "unknown";
    return now - freshestAt > staleMs ? "stale" : "fresh";
  }
  root.hesStaleState = state;
  if (typeof document === "undefined") return;
  var dot = document.getElementById("price-dot");
  if (!dot) return;
  var staleMs = (parseInt(dot.getAttribute("data-stale-after"), 10) || 120) * 1000, polledAt = null;

  function tick() {
    var freshest = polledAt;
    if (root.__liveAt && (freshest === null || root.__liveAt > freshest)) freshest = root.__liveAt;
    var s = state(freshest, Date.now(), staleMs);
    dot.hidden = s === "unknown";
    dot.classList.toggle("is-stale", s === "stale");
    var text = s === "stale" ? "Koersen zijn ouder dan " + Math.round(staleMs / 60000) + " minuten" : "Koersen zijn actueel";
    dot.setAttribute("aria-label", text);
    dot.title = text;
  }

  root.hesPriceSeen = function (ageSeconds) {
    var age = parseFloat(ageSeconds);
    if (isNaN(age)) return;
    polledAt = Date.now() - age * 1000;
    tick();
  };
  setInterval(tick, 5000);
})(typeof window !== "undefined" ? window : globalThis);
