// Afstandsring: de ring rond een kaart loopt vol naarmate de koers het limietniveau nadert. Leest de afstand die live.js of de poll al in
// stap 1 zet, dus er is geen tweede koersbron. Volle ring = op het niveau, lege ring = ver weg (RING_SCALE_PCT of meer).
(function () {
  var RING_SCALE_PCT = 3;
  function update() {
    document.querySelectorAll(".setup-card").forEach(function (card) {
      var fill = card.querySelector(".dist-ring-fill"), span = card.querySelector('.vd-step.is-now [data-vd="distance"]');
      if (!fill || !span) return;
      var v = parseFloat(span.textContent.replace(",", "."));
      if (isNaN(v)) return;
      var share = Math.max(0, Math.min(1, 1 - Math.abs(v) / RING_SCALE_PCT));
      fill.style.strokeDashoffset = String(100 - share * 100);
      card.classList.toggle("is-ringfull", share >= 0.9);
    });
  }
  update();
  setInterval(update, 1000);
})();
