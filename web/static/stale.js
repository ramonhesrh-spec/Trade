// Stip in de bovenbalk: groen zolang de getoonde koersen vers zijn, oranje als de nieuwste koers ouder is dan data-stale-after seconden
// (freshness.STALE_AFTER_S). Bron is per coin de koersstroom van de beurs (live.js zet window.__liveAtByCoin) of de leeftijd die de server bij
// een poll meestuurt (X-Price-Age); de stip volgt de oudste getoonde koers, niet de nieuwste. Op pagina's zonder koersen blijft hij verborgen.
(function (root) {
  function state(freshestAt, now, staleMs) {
    if (freshestAt === null || freshestAt === undefined) return "unknown";
    return now - freshestAt > staleMs ? "stale" : "fresh";
  }
  root.hesStaleState = state;
  // Per coin de nieuwste van stroom en poll, daarna de oudste over de coins: één verse coin mag een stille coin niet groen laten ogen.
  function shownAt(polledAt, byCoin, coins) {
    var oldest = null;
    (coins || []).forEach(function (c) {
      var t = byCoin && byCoin[c] !== undefined ? byCoin[c] : null;
      if (polledAt !== null && polledAt !== undefined && (t === null || polledAt > t)) t = polledAt;
      if (t !== null && (oldest === null || t < oldest)) oldest = t;
    });
    return oldest !== null ? oldest : (polledAt === undefined ? null : polledAt);
  }
  root.hesShownAt = shownAt;
  if (typeof document === "undefined") return;
  var dot = document.getElementById("price-dot");
  if (!dot) return;
  var staleMs = (parseInt(dot.getAttribute("data-stale-after"), 10) || 120) * 1000, polledAt = null;

  function tick() {
    var s = state(shownAt(polledAt, root.__liveAtByCoin, root.__liveCoins), Date.now(), staleMs);
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
  document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });   // timers staan stil op een verborgen tab
})(typeof window !== "undefined" ? window : globalThis);
