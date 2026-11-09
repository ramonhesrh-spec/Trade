// Marktsessie als zachte tint op de achtergrond: Azië, Londen, New York of nacht, naar de UTC-klok. Hangt aan een echte waarde (waar
// de markt zit), beweegt niet en verandert maximaal een paar keer per dag.
(function () {
  function session(h) {
    if (h >= 13 && h < 21) return "newyork";
    if (h >= 7 && h < 13) return "londen";
    if (h >= 0 && h < 7) return "azie";
    return "nacht";
  }
  var NAMES = { azie: "Azië", londen: "Londen", newyork: "New York", nacht: "Rustig" };
  function set() {
    var s = session(new Date().getUTCHours());
    document.documentElement.setAttribute("data-session", s);
    var el = document.querySelector("[data-session-name]");
    if (el) el.textContent = NAMES[s];
  }
  set();
  setInterval(set, 60000);
})();
