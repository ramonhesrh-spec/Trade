// Tekst-tabs: toont alleen het paneel van de actieve tab. Zonder dit script staan alle panelen onder elkaar en springen de tabs
// als ankers, dus niets is ooit onbereikbaar. De gekozen tab staat in de hash, zodat terug-navigeren en een gedeelde link kloppen.
(function () {
  function init(group) {
    var name = group.getAttribute("data-utabs");
    var panels = document.querySelector('[data-utabs-panels="' + name + '"]');
    if (!panels) return;
    var tabs = Array.prototype.filter.call(group.querySelectorAll(".ut-tab"), function (t) { return t.getAttribute("href").charAt(0) === "#"; });
    if (!tabs.length) return;
    function show(id, push) {
      var found = false;
      tabs.forEach(function (t) {
        var on = t.getAttribute("href") === "#" + id;
        found = found || on;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      if (!found) return false;
      panels.querySelectorAll("[data-utab-panel]").forEach(function (p) { p.classList.toggle("is-shown", p.id === id); });
      if (push) history.replaceState(null, "", "#" + id);
      // levelchart.js tekent pas als een grafiek in beeld komt; een net getoond paneel moet dat zelf kunnen melden.
      window.dispatchEvent(new Event("resize"));
      return true;
    }
    // Een hash kan ook een element in een niet-getoond paneel zijn (alarm.js linkt naar /smc#radar-signal-N): toon dan dat paneel.
    function reveal() {
      var id = decodeURIComponent(location.hash.slice(1));
      if (!id) return false;
      if (show(id, false)) return true;
      var el = document.getElementById(id);
      var panel = el && el.closest && el.closest("[data-utab-panel]");
      if (!panel || !show(panel.id, false)) return false;
      if (el.scrollIntoView) el.scrollIntoView();
      return true;
    }
    panels.classList.add("is-js");
    if (!reveal()) {
      var active = group.querySelector(".ut-tab.is-active");
      show((tabs.indexOf(active) === -1 ? tabs[0] : active).getAttribute("href").slice(1), false);
    }
    window.addEventListener("hashchange", reveal);
    group.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest(".ut-tab");
      if (!t || tabs.indexOf(t) === -1) return;
      e.preventDefault();
      show(t.getAttribute("href").slice(1), true);
    });
  }
  window.hpUtabsInit = init;
  document.querySelectorAll("[data-utabs]").forEach(init);

  // Het drie-puntjesmenu sluit bij een tik ernaast en met Escape.
  function closeMenus(except) {
    document.querySelectorAll("details.ut-more[open]").forEach(function (d) { if (d !== except) d.removeAttribute("open"); });
  }
  document.addEventListener("click", function (e) { closeMenus(e.target.closest && e.target.closest("details.ut-more")); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenus(null); });
})();
