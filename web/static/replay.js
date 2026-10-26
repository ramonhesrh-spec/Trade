// Replay van een afgeronde trade (/logboek/replay/<id>): schuifbalk, knoppen per moment, vorige/volgende en Speel af. Alle getallen komen
// van de server (frames: tijd, R-label, R, stap, zin, x van de cursor per candle); dit script kiest alleen welke candle nu geldt.
(function () {
  var root = document.querySelector("[data-rp]");
  var data = root && root.querySelector('[data-rp="frames"]');
  if (!data) return;
  var frames;
  try { frames = JSON.parse(data.textContent); } catch (e) { return; }
  var q = function (k) { return root.querySelector('[data-rp="' + k + '"]'); };
  var range = q("range"), ctrl = q("ctrl"), play = q("play");
  var candles = [].slice.call(root.querySelectorAll(".rp-candle"));
  var cursor = root.querySelector(".rp-cursor");
  var moms = [].slice.call(root.querySelectorAll("[data-rp-go]"));
  var stops = moms.map(function (b) { return +b.getAttribute("data-rp-go"); });
  var cur = +range.value, timer = null;

  range.hidden = false;
  ctrl.hidden = false;

  function set(i) {
    cur = Math.max(0, Math.min(frames.length - 1, i));
    var f = frames[cur];
    range.value = cur;
    q("time").textContent = f.time;
    q("rlabel").textContent = f.r_label;
    q("r").textContent = f.r_text;
    q("step").textContent = f.step;
    q("event").textContent = f.event;
    if (cursor) { cursor.setAttribute("x1", f.x); cursor.setAttribute("x2", f.x); }
    candles.forEach(function (c, k) { c.classList.toggle("is-future", k > cur); });
    var active = -1;
    stops.forEach(function (s, k) { if (s <= cur) active = k; });
    moms.forEach(function (b, k) { b.classList.toggle("is-cur", k === active); b.setAttribute("aria-pressed", k === active ? "true" : "false"); });
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    play.textContent = "Speel af";
  }

  range.addEventListener("input", function () { stop(); set(+range.value); });
  moms.forEach(function (b) { b.addEventListener("click", function () { stop(); set(+b.getAttribute("data-rp-go")); }); });
  q("prev").addEventListener("click", function () {
    stop();
    var p = stops.filter(function (s) { return s < cur; });
    set(p.length ? p[p.length - 1] : 0);
  });
  q("next").addEventListener("click", function () {
    stop();
    var n = stops.filter(function (s) { return s > cur; });
    set(n.length ? n[0] : frames.length - 1);
  });
  // Afspelen loopt candle voor candle; een tik stopt het. Het is een bediening, geen versiering, en verschuift alleen de cursor.
  play.addEventListener("click", function () {
    if (timer) { stop(); return; }
    if (cur >= frames.length - 1) set(0);
    play.textContent = "Pauze";
    timer = setInterval(function () {
      if (cur >= frames.length - 1) { stop(); return; }
      set(cur + 1);
    }, Math.max(60, Math.min(220, 9000 / frames.length)));
  });
  set(cur);
})();
