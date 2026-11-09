// Aftelklok op /nieuw. De server zet het doel en zijn eigen tijd in de pagina: een telefoonklok die een paar minuten afwijkt, telt zo toch
// naar hetzelfde moment af. Elk cijfer is een strook 0-9 die naar zijn waarde rolt; met minder beweging springt hij er meteen heen (CSS).
// Bij nul laadt de pagina opnieuw en schrijft de server de live-versie.
(function () {
  var clock = document.querySelector("[data-countdown]");
  if (!clock) return;
  var target = Date.parse(clock.getAttribute("data-target"));
  var offset = Date.parse(clock.getAttribute("data-now")) - Date.now();
  if (isNaN(target) || isNaN(offset)) return;
  var units = {};
  Array.prototype.forEach.call(clock.querySelectorAll("[data-unit]"), function (el) { units[el.getAttribute("data-unit")] = el; });
  var lastMinute = null, reloading = false;

  function strip() {
    var dg = document.createElement("span");
    dg.className = "nw-dg";
    var s = document.createElement("span");
    s.className = "nw-strip";
    for (var i = 0; i < 10; i++) {
      var n = document.createElement("span");
      n.textContent = String(i);
      s.appendChild(n);
    }
    dg.appendChild(s);
    return dg;
  }

  function show(el, value) {
    var text = String(value);
    if (text.length < 2) text = "0" + text;
    if (el.children.length !== text.length) {
      el.textContent = "";
      for (var i = 0; i < text.length; i++) el.appendChild(strip());
    }
    for (var j = 0; j < text.length; j++) {
      el.children[j].firstChild.style.transform = "translateY(" + (-Number(text[j])) + "em)";
    }
  }

  function tick() {
    var left = Math.max(0, Math.ceil((target - (Date.now() + offset)) / 1000));
    var d = Math.floor(left / 86400), h = Math.floor(left % 86400 / 3600), m = Math.floor(left % 3600 / 60), s = left % 60;
    show(units.days, d); show(units.hours, h); show(units.minutes, m); show(units.seconds, s);
    // Het label voor een schermlezer alleen per minuut: elke seconde voorlezen zou niemand willen.
    var minute = d + ":" + h + ":" + m;
    if (minute !== lastMinute) {
      lastMinute = minute;
      clock.setAttribute("aria-label", "Nog " + d + " dagen, " + h + " uur en " + m + " minuten");
    }
    if (left === 0) {
      if (!reloading) { reloading = true; setTimeout(function () { location.reload(); }, 1200); }
      return;
    }
    setTimeout(tick, 1000 - ((Date.now() + offset) % 1000) + 20);
  }

  tick();
})();
