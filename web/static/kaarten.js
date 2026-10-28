// Kansen (ontwerp V4): een tik op de kop van een kaart, of op de kaart naast de grafiek, opent het detailblad van die kans. Het blad volgt de
// vinger 1:1 als je het aan de greep omlaag trekt en sluit bij loslaten; Escape en de knop sluiten ook. De ladders in het blad schuiven live mee:
// de koers komt van /api/radar (radar.js haalt die al op, hier alleen de prijs) en tussendoor van de koersstroom van live.js als die vers is.
(function () {
  var sheet = document.querySelector("[data-kd]");
  if (!sheet) return;
  var panel = sheet.querySelector("[data-kd-panel]");
  var rm = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var lastFocus = null;
  // In <main> zou het blad onder het dok vallen (main heeft een eigen stapel); aan body ligt het erboven.
  document.body.appendChild(sheet);

  function openSheet(key, opener) {
    var item = null;
    sheet.querySelectorAll("[data-kd-item]").forEach(function (s) {
      var on = s.getAttribute("data-kd-item") === key;
      s.hidden = !on;
      if (on) item = s;
    });
    if (!item) return;
    lastFocus = opener || document.activeElement;
    sheet.hidden = false;
    void sheet.offsetWidth;
    panel.scrollTop = 0;
    panel.style.transform = "";
    sheet.classList.add("is-open");
    document.documentElement.classList.add("kd-lock");
    var title = item.querySelector(".kd-title");
    if (title) title.focus({ preventScroll: true });
    live();
  }
  function closeSheet() {
    if (!sheet.classList.contains("is-open")) return;
    sheet.classList.remove("is-open");
    panel.style.transform = "";
    document.documentElement.classList.remove("kd-lock");
    setTimeout(function () { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, rm ? 0 : 260);
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }

  document.addEventListener("click", function (e) {
    var head = e.target.closest && e.target.closest("[data-kc-open]");
    if (head) { openSheet(head.getAttribute("data-kc-open"), head); return; }
    var card = e.target.closest && e.target.closest("[data-kc]");
    // De grafiek is van levelchart.js (tik = groot), links en knoppen doen hun eigen werk.
    if (card && !e.target.closest(".lc, a, button")) openSheet(card.getAttribute("data-kc"), card.querySelector("[data-kc-open]"));
  });
  sheet.querySelectorAll("[data-kd-close]").forEach(function (b) {
    b.addEventListener("click", function () { if (b._dragged) { b._dragged = false; return; } closeSheet(); });
  });
  sheet.addEventListener("click", function (e) { if (e.target === sheet) closeSheet(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeSheet(); });

  // Omlaag trekken aan de greep: 1:1 met de vinger, bij loslaten dicht of terug.
  var grab = sheet.querySelector(".kd-grab");
  if (grab) {
    var startY = 0, dy = 0, active = false, moved = false;
    grab.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      active = true; moved = false; startY = e.clientY; dy = 0;
      try { grab.setPointerCapture(e.pointerId); } catch (err) { /* zonder capture werkt de tik nog */ }
    });
    grab.addEventListener("pointermove", function (e) {
      if (!active) return;
      dy = Math.max(0, e.clientY - startY);
      if (!moved && dy < 6) return;
      moved = true;
      sheet.classList.add("is-dragging");
      panel.style.transform = "translateY(" + dy + "px)";
    });
    function end() {
      if (!active) return;
      active = false;
      sheet.classList.remove("is-dragging");
      if (!moved) return;
      grab._dragged = true;
      if (dy > Math.min(120, (panel.offsetHeight || innerHeight) * 0.2)) closeSheet();
      else panel.style.transform = "";
    }
    grab.addEventListener("pointerup", end);
    grab.addEventListener("pointercancel", end);
  }

  // ===== Live koers op de ladders =====
  function live() {
    if (!window.hesLadder || !window.__livePrices) return;
    Object.keys(window.__livePrices).forEach(function (coin) { window.hesLadder.updateCoin(coin, window.__livePrices[coin]); });
  }
  setInterval(function () {
    if (document.hidden || sheet.hidden || !(window.hesLiveFresh && window.hesLiveFresh())) return;
    live();
  }, 1000);
  function poll() {
    if (document.hidden || sheet.hidden) return;
    fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        if (!payload || !window.hesLadder || (window.hesLiveFresh && window.hesLiveFresh())) return;
        Object.keys(payload).forEach(function (k) {
          var d = payload[k], card = document.querySelector('[data-kc="' + k + '"] [data-live-coin]');
          if (d && d.price && card) window.hesLadder.updateCoin(card.getAttribute("data-live-coin"), d.price);
        });
      })
      .catch(function () { /* de laatste stand blijft staan */ });
  }
  setInterval(poll, 15000);
})();
