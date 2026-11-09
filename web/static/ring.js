// Afstandsbalk in stap 1 van een structuurkaart: loopt vol naarmate de koers het limietniveau nadert. Leest de afstand die live.js of de
// poll al in stap 1 zet, dus er is geen tweede koersbron. Vol = op het niveau, leeg = RING_SCALE_PCT of verder weg (trade_plan.approach_pct).
(function () {
  var RING_SCALE_PCT = 3;
  function update() {
    document.querySelectorAll(".vd-step.is-now .step-approach").forEach(function (track) {
      var fill = track.querySelector("i"), span = track.parentElement.querySelector('[data-vd="distance"]');
      if (!fill || !span) return;
      var v = parseFloat(span.textContent.replace(",", "."));
      if (isNaN(v)) return;
      var share = Math.max(0, Math.min(1, 1 - Math.abs(v) / RING_SCALE_PCT));
      fill.style.width = (share * 100).toFixed(0) + "%";
      track.classList.toggle("is-full", share >= 0.9);
    });
  }
  update();
  setInterval(update, 1000);
})();
