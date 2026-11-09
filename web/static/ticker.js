// Cijfers die live tikken: verandert een koers of resultaat, dan rollen alleen de cijfers die anders zijn omhoog of omlaag.
// Alleen bij een echte verandering van de waarde en niet bij verminderde beweging.
(function () {
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  var SEL = "[data-vd-price], [data-radar='live_r'], [data-vd='distance'], [data-radar='distance'], [data-tick]";

  function roll(el, before, after) {
    if (before === after || !before) return;
    var up = parseFloat(after.replace(/[^\d.,-]/g, "").replace(",", ".")) >= parseFloat(before.replace(/[^\d.,-]/g, "").replace(",", "."));
    var html = "";
    for (var i = 0; i < after.length; i++) {
      var changed = before[i] !== after[i];
      html += changed ? '<span class="tick-d ' + (up ? "tick-up" : "tick-down") + '">' + after[i] + "</span>" : after[i];
    }
    el.innerHTML = html;
  }

  var seen = new WeakMap();
  var observer = new MutationObserver(function (list) {
    list.forEach(function (m) {
      var el = m.target.nodeType === 3 ? m.target.parentElement : m.target;
      if (!el || !el.matches || !el.matches(SEL)) return;
      var now = el.textContent, before = seen.get(el);
      if (before === now) return;
      seen.set(el, now);
      if (before !== undefined) roll(el, before, now);
    });
  });
  document.querySelectorAll(SEL).forEach(function (el) { seen.set(el, el.textContent); observer.observe(el, { childList: true, characterData: true, subtree: true }); });
})();
