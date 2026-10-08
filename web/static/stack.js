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
  var bar = document.getElementById("stack-bar"), count = document.getElementById("stack-count");
  var on = false, startX = null, current = null;

  function pending() { return cards.filter(function (c) { return !state[c.id]; }); }
  function render() {
    var left = pending();
    cards.forEach(function (c) {
      c.hidden = on && c !== left[0];
      c.classList.toggle("is-kept", state[c.id] === "keep");
    });
    if (count) count.textContent = left.length ? "Kaart " + (cards.length - left.length + 1) + " van " + cards.length : "Alle kaarten gehad";
    if (bar) bar.hidden = !on;
    grid.classList.toggle("is-stack", on);
  }
  function decide(card, verdict) {
    state[card.id] = verdict; save();
    card.style.transition = "transform .22s ease-out, opacity .22s ease-out";
    card.style.transform = "translateX(" + (verdict === "keep" ? 120 : -120) + "%) rotate(" + (verdict === "keep" ? 8 : -8) + "deg)";
    card.style.opacity = "0";
    setTimeout(function () { card.style.transition = card.style.transform = card.style.opacity = ""; render(); }, 230);
  }
  toggle.addEventListener("click", function () { on = !on; toggle.setAttribute("aria-pressed", on ? "true" : "false"); toggle.textContent = on ? "Toon lijst" : "Toon als stapel"; render(); });
  document.getElementById("stack-reset").addEventListener("click", function () { state = {}; save(); render(); });
  document.getElementById("stack-skip").addEventListener("click", function () { var c = pending()[0]; if (c) decide(c, "skip"); });
  document.getElementById("stack-keep").addEventListener("click", function () { var c = pending()[0]; if (c) decide(c, "keep"); });

  grid.addEventListener("pointerdown", function (e) { if (!on || e.target.closest("a, button")) return; current = pending()[0]; if (!current) return; startX = e.clientX; });
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
