// Kansen (ontwerp V4): een tik op de kop van een kaart, of op de kaart naast de grafiek, opent het detailblad van die kans. Het blad volgt de
// vinger 1:1 als je het aan de greep omlaag trekt en sluit bij loslaten; Escape en de knop sluiten ook. De ladders in het blad schuiven live mee:
// de koers komt van /api/radar (radar.js haalt die al op, hier alleen de prijs) en tussendoor van de koersstroom van live.js als die vers is.
(function () {
  window.hesKansenSummary = summary;
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
    // Een levelchart-grafiek is van levelchart.js (tik = groot), links en knoppen doen hun eigen werk; een getekende kaart (svg) opent het blad.
    if (card && !e.target.closest(".lc .level-chart, a, button")) openSheet(card.getAttribute("data-kc"), card.querySelector("[data-kc-open]"));
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

  // ===== De eigen kaartgrafiek van Zone-radar en Zone-sweep (/api/kaart_svg, app/card_chart.py) =====
  // Pas als de kaart bijna in beeld is, en hoogstens MAX_SVG tegelijk onderweg: een lange tab op een telefoon haalt niet alles in één keer op.
  var MAX_SVG = 4, busy = 0, queue = [];
  function pump() {
    while (busy < MAX_SVG && queue.length) {
      var fig = queue.shift(), box = fig.querySelector(".kc-svg-box");
      if (!box || fig._svgDone) continue;
      fig._svgDone = true;
      busy++;
      fetch(fig.getAttribute("data-kc-svg"), { cache: "no-store", credentials: "same-origin" })
        .then((function (b, f) { return function (r) {
          // Geen eigen tekening (een signaal zonder setup-rij): dan de gewone kaartgrafiek, die levelchart.js tekent zodra hij zichtbaar is.
          var lc = f.querySelector("[data-levelchart]");
          if (r.status === 404 && lc) {
            b.hidden = true; lc.hidden = false; f.classList.add("is-fallback");
            var cap = f.querySelector(".lc-cap");
            if (cap) cap.textContent = "15 min per candle \u00b7 jouw tijd";
            return "fallback";
          }
          return r.ok ? r.text() : "";
        }; })(box, fig))
        .then((function (b, f) { return function (svg) {
          if (svg === "fallback") return;
          if (svg && svg.indexOf("<svg") === 0) { b.innerHTML = svg; f.classList.add("is-drawn"); }
          else { b.querySelector(".kc-svg-wait").textContent = "Grafiek nu niet beschikbaar"; f._svgDone = false; }
        }; })(box, fig))
        .catch((function (b, f) { return function () { b.querySelector(".kc-svg-wait").textContent = "Grafiek nu niet beschikbaar"; f._svgDone = false; }; })(box, fig))
        .then(function () { busy--; pump(); });
    }
  }
  var figs = document.querySelectorAll("[data-kc-svg]");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { io.unobserve(en.target); queue.push(en.target); } });
      pump();
    }, { rootMargin: "300px 0px" });
    figs.forEach(function (f) { io.observe(f); });
  } else {
    figs.forEach(function (f) { queue.push(f); });
    pump();
  }

  // ===== Tellers boven de kansen =====
  // De server zet de getallen (app/kansen.py, tabs[].n en in_zone); hier alleen opnieuw tellen wat er op de pagina staat zodra radar.js een
  // kaart van stand laat wisselen. Dezelfde woorden als kansen.summary (tests/test_static_js.py).
  function summary(n, zone, open) {
    if (!n && !open) return "Geen kansen";
    var parts = n ? [n + (n === 1 ? " kans klaar" : " kansen klaar")] : [];
    if (zone) parts.push(zone + " in de zone");
    if (open) parts.push(open + " open");
    return parts.join(" \u00b7 ");
  }
  function recount() {
    var tn = 0, tz = 0, to = 0;
    document.querySelectorAll('[data-utabs-panels="kansen"] > [data-utab-panel]').forEach(function (panel) {
      var plans = panel.querySelectorAll("[data-kt-plans] > .kc:not(.is-moot)"), zone = 0;
      plans.forEach(function (c) { if (c.querySelector(".kc-head .state-pill.is-in_zone")) zone++; });
      var open = panel.querySelectorAll("[data-kt-trades] > .kc").length, n = plans.length;
      tn += n; tz += zone; to += open;
      var sum = panel.querySelector(".kt-sum");
      if (sum) sum.textContent = summary(n, zone, open);
      var tab = document.getElementById(panel.id + "-tab");
      if (!tab) return;
      var num = tab.querySelector("[data-ut-num]");
      if (num) num.textContent = n;
      var badge = tab.querySelector("[data-ut-badge]");
      if (zone && !badge) {
        badge = document.createElement("i");
        badge.className = "ut-badge";
        badge.setAttribute("data-ut-badge", "");
        tab.appendChild(badge);
      }
      if (badge && !zone) badge.remove();
      else if (badge) badge.innerHTML = zone + '<span class="sr-only"> in de zone</span>';
    });
    var total = document.querySelector("[data-kansen-total]");
    if (total) {
      var next = summary(tn, tz, to);
      if (total.textContent !== next) total.textContent = next;
    }
  }
  document.addEventListener("hp:radar", recount);
})();
