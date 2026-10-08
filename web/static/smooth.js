// Vloeiendheid en spaarzaamheid, vier dingen die samen het verschil maken op een telefoon:
// (1) tijdens het scrollen staan de zwevende achtergrondvlakken stil, zodat de GPU alleen scrolt;
// (2) een tik op een tab kleurt hem meteen, nog voor de pagina geladen is;
// (3) trek de pagina bovenaan omlaag om te verversen, zoals in een app, en de tabtitel toont de dichtstbijzijnde kans.
(function () {
  var root = document.documentElement, ticking = false, idle = null;

  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      root.classList.add("is-scrolling");
      clearTimeout(idle);
      idle = setTimeout(function () { root.classList.remove("is-scrolling"); }, 160);
      ticking = false;
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });

  document.addEventListener("pointerdown", function (e) {
    var tab = e.target.closest && e.target.closest("a.tab");
    if (!tab) return;
    document.querySelectorAll(".tabbar .tab.is-active").forEach(function (t) { t.classList.remove("is-active"); });
    tab.classList.add("is-active");
  }, { passive: true });

  // Trek om te verversen: alleen op aanraking, alleen bovenaan de pagina, pas bij een duidelijke beweging.
  var startY = null, pulled = 0, hint = null, THRESHOLD = 80;
  function ensureHint() {
    if (hint) return hint;
    hint = document.createElement("div");
    hint.className = "pull-hint";
    hint.setAttribute("aria-hidden", "true");
    hint.textContent = "Trek om te verversen";
    document.body.appendChild(hint);
    return hint;
  }
  document.addEventListener("touchstart", function (e) { startY = window.scrollY <= 0 ? e.touches[0].clientY : null; pulled = 0; }, { passive: true });
  document.addEventListener("touchmove", function (e) {
    if (startY === null) return;
    pulled = Math.max(0, e.touches[0].clientY - startY);
    if (pulled < 12 || window.scrollY > 0) return;
    var h = ensureHint(), share = Math.min(1, pulled / THRESHOLD);
    h.style.opacity = String(share);
    h.style.transform = "translate(-50%, " + Math.round(Math.min(pulled, THRESHOLD * 1.4) * 0.6) + "px)";
    h.textContent = share >= 1 ? "Laat los om te verversen" : "Trek om te verversen";
  }, { passive: true });
  document.addEventListener("touchend", function () {
    var go = startY !== null && pulled >= THRESHOLD && window.scrollY <= 0;
    startY = null;
    if (hint) { hint.style.opacity = "0"; hint.style.transform = "translate(-50%, 0)"; }
    if (go) { if (hint) hint.textContent = "Verversen"; location.reload(); }
  }, { passive: true });

  // De tabtitel toont de dichtstbijzijnde kans binnen 1%, bijvoorbeeld "0,4% BNB short". Zo zie je het in de tabbalk of app-switcher.
  var baseTitle = document.title;
  function titleTick() {
    var best = null;
    document.querySelectorAll(".setup-card").forEach(function (card) {
      var span = card.querySelector('.vd-step.is-now [data-vd="distance"]'), coin = card.querySelector(".radar-coin"), dir = card.querySelector(".radar-dir");
      if (!span || !coin) return;
      var v = Math.abs(parseFloat(span.textContent.replace(",", ".")));
      if (!isNaN(v) && (best === null || v < best.v)) best = { v: v, text: coin.textContent.trim() + " " + (dir ? dir.textContent.trim() : "") };
    });
    document.title = best && best.v <= 1 ? best.v.toFixed(1) + "% " + best.text + " · HesPulse" : baseTitle;
  }
  if (document.querySelector(".setup-card")) setInterval(titleTick, 2000);
})();
