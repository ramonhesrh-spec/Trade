// Kaartenstapel op Setups: één kaart per keer, veeg links om te negeren en rechts om te bewaren. Zonder JS blijft het een gewone lijst.
// Wat je negeert of bewaart onthoudt alleen deze browser (localStorage), de kansen zelf veranderen niet.
(function () {
  var grid = document.querySelector(".setup-grid");
  var toggle = document.getElementById("stack-toggle");
  if (!grid || !toggle) return;
  var KEY = "hespulse-stack", cards = Array.prototype.slice.call(grid.querySelectorAll(".setup-card"));
  if (cards.length < 2) { toggle.hidden = true; return; }
  var state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function el(id) { return document.getElementById(id); }
  var bar = el("stack-bar"), count = el("stack-count"), prev = el("stack-prev"), next = el("stack-next");
  var skip = el("stack-skip"), keep = el("stack-keep");
  // pos wijst in de nog open kaarten: met de pijltjes blader je zonder een oordeel te geven.
  var on = false, pos = 0, startX = null, current = null;

  function pending() { return cards.filter(function (c) { return !state[c.id]; }); }
  function render() {
    var left = pending();
    pos = Math.max(0, Math.min(pos, left.length - 1));
    cards.forEach(function (c) {
      c.hidden = on && c !== left[pos];
      c.classList.toggle("is-kept", state[c.id] === "keep");
    });
    if (count) count.textContent = left.length ? "Kaart " + (cards.length - left.length + pos + 1) + " van " + cards.length : "Alle kaarten gehad";
    if (prev) prev.disabled = pos <= 0;
    if (next) next.disabled = pos >= left.length - 1;
    if (skip) skip.disabled = !left.length;
    if (keep) keep.disabled = !left.length;
    if (bar) bar.hidden = !on;
    grid.classList.toggle("is-stack", on);
  }
  function decide(card, verdict) {
    state[card.id] = verdict; save();
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) { render(); return; }
    card.style.transition = "transform .22s ease-out, opacity .22s ease-out";
    card.style.transform = "translateX(" + (verdict === "keep" ? 120 : -120) + "%) rotate(" + (verdict === "keep" ? 8 : -8) + "deg)";
    card.style.opacity = "0";
    setTimeout(function () { card.style.transition = card.style.transform = card.style.opacity = ""; render(); }, 230);
  }
  function shown() { return pending()[pos]; }
  toggle.addEventListener("click", function () {
    on = !on;
    toggle.setAttribute("aria-pressed", on ? "true" : "false");
    toggle.textContent = on ? "Lijst" : "Stapel";
    render();
  });
  el("stack-reset").addEventListener("click", function () { state = {}; pos = 0; save(); render(); });
  if (skip) skip.addEventListener("click", function () { var c = shown(); if (c) decide(c, "skip"); });
  if (keep) keep.addEventListener("click", function () { var c = shown(); if (c) decide(c, "keep"); });
  if (prev) prev.addEventListener("click", function () { pos -= 1; render(); });
  if (next) next.addEventListener("click", function () { pos += 1; render(); });

  grid.addEventListener("pointerdown", function (e) { if (!on || e.target.closest("a, button")) return; current = shown(); if (!current) return; startX = e.clientX; });
  grid.addEventListener("pointermove", function (e) {
    if (startX === null || !current) return;
    var dx = e.clientX - startX;
    current.style.transform = "translateX(" + dx + "px) rotate(" + (dx / 25) + "deg)";
    current.classList.toggle("is-swipe-keep", dx > 40); current.classList.toggle("is-swipe-skip", dx < -40);
  });
  function end(e) {
    if (startX === null || !current) return;
    var dx = e.clientX - startX, card = current;
    startX = null; current = null;
    card.classList.remove("is-swipe-keep", "is-swipe-skip");
    if (Math.abs(dx) > 100) decide(card, dx > 0 ? "keep" : "skip");
    else { card.style.transition = "transform .18s ease-out"; card.style.transform = ""; setTimeout(function () { card.style.transition = ""; }, 190); }
  }
  grid.addEventListener("pointerup", end);
  grid.addEventListener("pointercancel", end);
  render();
})();
