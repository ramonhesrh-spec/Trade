// Vloeiendheid op een telefoon, drie dingen:
// (1) een tik op een tab kleurt hem meteen, nog voor de pagina geladen is;
// (2) trek de pagina bovenaan omlaag om te verversen, zoals in een app (Radar en Vandaag zonder herlaadslag), en de tabtitel toont de dichtstbijzijnde kans.
(function () {
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
  // Geen trek-om-te-verversen in de grafiek (die pant zelf), in een invoerveld of bij een open blad of venster.
  function pullBlocked(target) {
    if (!target || !target.closest) return false;
    return !!target.closest("[data-levelchart], .chart, input, textarea, select, dialog[open], #more-sheet.is-open, .cmdk-overlay:not([hidden]), .fsearch");
  }
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  var startX = 0, busy = false;
  function hideHint() {
    if (!hint) return;
    hint.style.opacity = "0";
    hint.style.transform = "translate(-50%, 0)";
  }
  document.addEventListener("touchstart", function (e) {
    startY = window.scrollY <= 0 && !busy && e.touches.length === 1 && !pullBlocked(e.target) ? e.touches[0].clientY : null;
    startX = e.touches[0].clientX;
    pulled = 0;
  }, { passive: true });
  document.addEventListener("touchmove", function (e) {
    if (startY === null) return;
    // Een scheve of opwaartse beweging is scrollen of vegen, geen trek; dan laten we iOS-rubberband met rust.
    var dy = e.touches[0].clientY - startY, dx = Math.abs(e.touches[0].clientX - startX);
    if (e.touches.length > 1 || window.scrollY > 0 || dx > dy) { startY = null; pulled = 0; hideHint(); return; }
    pulled = Math.max(0, dy);
    if (pulled < 12) return;
    var h = ensureHint(), share = Math.min(1, pulled / THRESHOLD);
    h.style.opacity = String(share);
    h.style.transform = "translate(-50%, " + (reduceMotion && reduceMotion.matches ? 0 : Math.round(Math.min(pulled, THRESHOLD * 1.4) * 0.6)) + "px)";
    h.textContent = share >= 1 ? "Laat los om te verversen" : "Trek om te verversen";
  }, { passive: true });
  document.addEventListener("touchend", function () {
    var go = startY !== null && pulled >= THRESHOLD && window.scrollY <= 0;
    startY = null;
    if (!go) { hideHint(); return; }
    var h = ensureHint();
    h.textContent = "Verversen";
    // Radar en Vandaag halen alleen hun gegevens opnieuw op (window.hesRefresh): scrollpositie en open grafieken blijven staan.
    if (typeof window.hesRefresh !== "function") { location.reload(); return; }
    busy = true;
    Promise.resolve(window.hesRefresh()).then(function (ok) {
      h.textContent = ok ? "Bijgewerkt" : "Verversen lukte niet";
      setTimeout(function () { busy = false; hideHint(); }, 900);
    });
  }, { passive: true });
  document.addEventListener("touchcancel", function () { startY = null; hideHint(); }, { passive: true });

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

  // Een tik op een melding: de service worker stuurt de bestemming als bericht naar de open app, of zet haar kort in een cache voor een koude start.
  // iOS negeert in een geïnstalleerde app vaak de link van de melding zelf, dus de pagina navigeert hier zelf naartoe.
  function goTo(url) {
    try {
      var u = new URL(url, location.origin);
      if (u.origin === location.origin && u.href !== location.href) location.href = u.href;
    } catch (e) { /* ongeldige bestemming: blijf waar je bent */ }
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", function (e) {
      if (e.data && e.data.hespulseNavigate) goTo(e.data.hespulseNavigate);
    });
    if (navigator.serviceWorker.startMessages) navigator.serviceWorker.startMessages();
  }
  // De cache wordt niet alleen bij het laden gelezen: een app die op de achtergrond stond, laadt niet opnieuw als je op de melding tikt, en het bericht
  // van de service worker gaat verloren als iOS de pagina bevroren had. Daarom ook bij terugkeer naar de app.
  function checkPending() {
    if (!("caches" in window)) return;
    caches.open("hespulse-nav").then(function (c) {
      return c.match("/__pending-nav").then(function (r) {
        if (!r) return;
        c.delete("/__pending-nav");
        return r.json().then(function (d) { if (d && Date.now() - d.at < 120000) goTo(d.url); });
      });
    }).catch(function () {});
  }
  checkPending();
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") checkPending(); });
  window.addEventListener("pageshow", checkPending);
  window.addEventListener("focus", checkPending);
})();
