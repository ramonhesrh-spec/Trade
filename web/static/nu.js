// Nu op de prijsladder (ontwerp V3). De keuze tussen rust, een plan in de zone of een open trade maakt de server (app/nu.py); verandert wat
// er in de zone staat of welke trades open zijn, dan laadt de pagina opnieuw (met het skelet van de ladder in plaats van een spinner).
// Verder schuift alleen de koers (ladder.js). Bron: /api/radar elke 15 seconden, tussendoor de koersstroom van live.js als die vers is.
// Gebaren volgen de vinger 1:1; alleen bij loslaten loopt de curve (CSS --t-blad). Elk gebaar heeft een knop ernaast.
(function () {
  var root = document.querySelector("[data-nu-mode]");
  if (!root) return;
  var sig = root.getAttribute("data-nu-sig") || "|";
  var skip = (root.getAttribute("data-nu-skip") || "").split(",").filter(Boolean);
  var cards = [].slice.call(root.querySelectorAll("[data-nu-key]"));
  var math = window.hesLadderMath;
  var reloading = false;
  var rm = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);

  function ladders(card) { return [].slice.call(document.querySelectorAll('[data-ladder][data-lad-coin="' + card.getAttribute("data-nu-coin") + '"]')); }
  function show(card, price) {
    if (!price || !window.hesLadder) return;
    ladders(card).forEach(function (el) { window.hesLadder.update(el, price); });
  }

  // Herladen: het skelet neemt de plek van de ladder in, zodat de nieuwe inhoud op dezelfde plek verschijnt.
  function reload() {
    if (reloading) return;
    reloading = true;
    root.querySelectorAll("[data-ladder-skeleton]").forEach(function (sk) {
      var real = sk.previousElementSibling;
      if (real) real.hidden = true;
      sk.hidden = false;
    });
    location.reload();
  }

  function signature(payload) {
    var zone = [], trades = [];
    Object.keys(payload).forEach(function (k) {
      if (k.indexOf("signal:") === 0) trades.push(k);
      else if (payload[k].state === "in_zone" && skip.indexOf(k) === -1) zone.push(k);
    });
    return zone.sort().join(",") + "|" + trades.sort().join(",");
  }

  function apply(payload) {
    if (signature(payload) !== sig) { if (!pendingSkip) reload(); return; }
    cards.forEach(function (card) {
      var d = payload[card.getAttribute("data-nu-key")];
      if (d) show(card, d.price);
    });
  }

  function staleLine(age) {
    var text = math ? math.stale(age) : "";
    root.querySelectorAll("[data-nu-stale]").forEach(function (el) { el.textContent = text; el.hidden = !text; });
  }

  function refresh() {
    if (document.hidden || reloading) return;
    fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return null;
        var age = r.headers.get("X-Price-Age");
        if (age !== null && window.hesPriceSeen) window.hesPriceSeen(age);
        if (age !== null && !isNaN(parseInt(age, 10))) staleLine(parseInt(age, 10));
        return r.json();
      })
      .then(function (payload) { if (payload) apply(payload); })
      .catch(function () { /* een mislukte verversing laat de laatste stand staan */ });
  }

  setInterval(function () {
    if (document.hidden || !(window.hesLiveFresh && window.hesLiveFresh()) || !window.__livePrices) return;
    cards.forEach(function (card) { show(card, window.__livePrices[card.getAttribute("data-nu-coin")]); });
  }, 1000);
  setInterval(refresh, 15000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });

  // Het blad en de ongedaan-balk staan in <main>, dat een eigen stapel heeft (z-index 1): onder het dok. Naar body, dan liggen ze erboven.
  var sheet = root.querySelector("[data-nu-sheet]");
  var undo = root.querySelector("[data-nu-undo]");
  if (sheet) document.body.appendChild(sheet);
  if (undo) document.body.appendChild(undo);

  // ===== Overslaan: veeg de ladder opzij, of de knop "Sla over". Geen vraag, wel 4 s om het ongedaan te maken. =====
  var form = root.querySelector("[data-nu-skip-form]");
  var swipe = root.querySelector("[data-nu-skippable]");
  var pendingSkip = null;
  var SWIPE_OUT = 110, UNDO_MS = 4000;

  function commitSkip() {
    if (!pendingSkip || !form) return;
    pendingSkip = null;
    // keepalive: ook als de pagina net sluit komt het overslaan aan (de server bewaart het in plan_skips).
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", keepalive: true, redirect: "manual" })
      .catch(function () {})
      .then(function () { reload(); });
  }
  function startSkip() {
    if (pendingSkip || !undo) return;
    undo.hidden = false;
    undo.classList.remove("is-running");
    void undo.offsetWidth;
    undo.classList.add("is-running");
    pendingSkip = setTimeout(commitSkip, UNDO_MS);
    var btn = undo.querySelector("[data-nu-undo-btn]");
    if (btn) btn.focus({ preventScroll: true });
  }
  function settle(dx) {
    if (!swipe) return;
    swipe.style.transition = rm ? "opacity 120ms linear" : "transform var(--t-blad) var(--e-blad), opacity var(--t-blad) var(--e-blad)";
    swipe.style.transform = rm ? "" : "translateX(" + dx + "px)";
    swipe.style.opacity = dx ? "0" : "";
  }
  function undoSkip() {
    clearTimeout(pendingSkip);
    pendingSkip = null;
    if (undo) { undo.hidden = true; undo.classList.remove("is-running"); }
    settle(0);
  }
  if (undo) undo.querySelector("[data-nu-undo-btn]").addEventListener("click", undoSkip);
  window.addEventListener("pagehide", function () { if (pendingSkip) { clearTimeout(pendingSkip); commitSkip(); } });
  if (form) form.addEventListener("submit", function (e) {
    if (!undo) return;
    e.preventDefault();
    settle(-window.innerWidth);
    startSkip();
  });

  if (swipe) {
    var sx = 0, sy = 0, dx = 0, mode = null, pid = null;
    swipe.addEventListener("pointerdown", function (e) {
      if (pendingSkip || (e.pointerType === "mouse" && e.button !== 0)) return;
      sx = e.clientX; sy = e.clientY; dx = 0; mode = null; pid = e.pointerId;
    });
    swipe.addEventListener("pointermove", function (e) {
      if (pid !== e.pointerId) return;
      var mx = e.clientX - sx, my = e.clientY - sy;
      if (!mode) {
        if (Math.abs(mx) < 8 && Math.abs(my) < 8) return;
        mode = Math.abs(mx) > Math.abs(my) ? "x" : "y";          // verticaal is scrollen: dat laten we aan de browser
        if (mode === "x") { try { swipe.setPointerCapture(pid); } catch (err) { /* geen capture, dan volgt hij zolang de vinger erop blijft */ } swipe.classList.add("is-dragging"); }
      }
      if (mode !== "x") return;
      dx = mx;
      swipe.style.transition = "none";
      if (!rm) swipe.style.transform = "translateX(" + dx + "px)";
      swipe.style.opacity = String(Math.max(0.15, 1 - Math.abs(dx) / 420));
    });
    function end(e) {
      if (pid !== e.pointerId) return;
      pid = null;
      swipe.classList.remove("is-dragging");
      if (mode !== "x") return;
      if (Math.abs(dx) > SWIPE_OUT) { settle((dx > 0 ? 1 : -1) * window.innerWidth); startSkip(); }
      else settle(0);
    }
    swipe.addEventListener("pointerup", end);
    swipe.addEventListener("pointercancel", end);
  }

  // ===== Detailblad: trek de greep omhoog, of tik erop. Het blad volgt de vinger 1:1 en klikt bij loslaten open of dicht. =====
  if (!sheet) return;
  var panel = sheet.querySelector("[data-nu-sheet-panel]");
  var opener = root.querySelector("[data-nu-sheet-open]");
  var lastFocus = null;

  function openSheet() {
    lastFocus = document.activeElement;
    sheet.hidden = false;
    void sheet.offsetWidth;
    panel.style.transform = "";
    sheet.classList.add("is-open");
    if (opener) opener.setAttribute("aria-expanded", "true");
    document.documentElement.classList.add("nu-lock");
    var title = sheet.querySelector("#nu-sheet-title");
    if (title) title.focus({ preventScroll: true });
  }
  function closeSheet() {
    sheet.classList.remove("is-open");
    panel.style.transform = "";
    if (opener) opener.setAttribute("aria-expanded", "false");
    document.documentElement.classList.remove("nu-lock");
    setTimeout(function () { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, rm ? 0 : 260);
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }
  sheet.querySelectorAll("[data-nu-sheet-close]").forEach(function (b) { b.addEventListener("click", function () { if (!b._dragged) closeSheet(); b._dragged = false; }); });
  sheet.addEventListener("click", function (e) { if (e.target === sheet) closeSheet(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && sheet.classList.contains("is-open")) closeSheet(); });

  function dragger(handle, opening) {
    var startY = 0, dy = 0, active = false, moved = false;
    handle.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      active = true; moved = false; startY = e.clientY; dy = 0;
      try { handle.setPointerCapture(e.pointerId); } catch (err) { /* zonder capture werkt de tik nog */ }
    });
    handle.addEventListener("pointermove", function (e) {
      if (!active) return;
      dy = e.clientY - startY;
      if (!moved && Math.abs(dy) < 6) return;
      if (!moved) {
        moved = true;
        if (opening) { sheet.hidden = false; void sheet.offsetWidth; }
        sheet.classList.add("is-dragging");
      }
      var h = panel.offsetHeight || window.innerHeight;
      var y = opening ? Math.max(0, h + dy) : Math.max(0, dy);           // 1:1 met de vinger, nooit voorbij de bovenkant
      panel.style.transform = "translateY(" + y + "px)";
    });
    function end() {
      if (!active) return;
      active = false;
      sheet.classList.remove("is-dragging");
      if (!moved) return;                                                  // een tik: de klik doet het werk
      handle._dragged = true;
      var h = panel.offsetHeight || window.innerHeight;
      if (opening) { if (-dy > Math.min(120, h * 0.2)) openSheet(); else { panel.style.transform = ""; sheet.classList.remove("is-open"); setTimeout(function () { sheet.hidden = true; }, rm ? 0 : 260); } }
      else if (dy > Math.min(120, h * 0.2)) closeSheet();
      else panel.style.transform = "";
    }
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  }
  if (opener) {
    dragger(opener, true);
    opener.addEventListener("click", function () { if (opener._dragged) { opener._dragged = false; return; } openSheet(); });
  }
  var grab = sheet.querySelector(".nu-sheet-grab");
  if (grab) dragger(grab, false);
})();
