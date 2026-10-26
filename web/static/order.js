// Order-checklist (/nu/order/...): een tik op een getal kopieert het met een punt als decimaal, vinkt de stap af en licht de volgende op.
// Kopiëren kan op drie manieren mislukken (geen https, geen toestemming, oude browser); dan het verborgen tekstveld, en als ook dat niet
// lukt blijft het getal geselecteerd staan zodat je het zelf kopieert. Koers en zone-stand komen elke 15 seconden van /api/radar.
(function () {
  var root = document.querySelector("[data-ck]");
  if (!root) return;
  var steps = [].slice.call(root.querySelectorAll("[data-ck-step]"));
  var segs = [].slice.call(root.querySelectorAll(".ck-seg"));
  var label = root.querySelector("[data-ck-label]"), next = root.querySelector("[data-ck-next]"), done = root.querySelector("[data-ck-done]");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var cur = 0, finished = [];

  function render() {
    var all = cur >= steps.length;
    steps.forEach(function (li, i) {
      li.classList.toggle("is-cur", i === cur);
      li.classList.toggle("is-done", !!finished[i]);
      li.classList.toggle("is-later", !finished[i] && i > cur);
      var dot = li.querySelector(".ck-dot");
      if (dot) dot.textContent = finished[i] ? "✓" : String(i + 1);
    });
    segs.forEach(function (seg, i) {
      seg.classList.toggle("is-done", !!finished[i]);
      seg.classList.toggle("is-cur", i === cur);
    });
    if (label) label.textContent = all ? "Klaar" : "Stap " + (cur + 1) + " van " + steps.length;
    if (next) next.hidden = all;
    if (done) done.hidden = !all;
  }

  function focusStep(i) {
    var li = steps[i];
    if (!li) return;
    if (li.scrollIntoView) li.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }

  function finish(i) {
    finished[i] = true;
    if (cur <= i) {
      cur = i + 1;
      while (cur < steps.length && finished[cur]) cur++;
    }
    render();
    focusStep(cur);
  }

  function selectText(el) {
    try {
      var range = document.createRange();
      range.selectNodeContents(el);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (e) {}
  }

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    var ok = false;
    try {
      ta.select();
      ta.setSelectionRange(0, text.length);
      ok = document.execCommand("copy");
    } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  function copy(text, numEl, done) {
    var after = function (ok) {
      if (!ok && numEl) selectText(numEl);
      done(ok);
    };
    try {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { after(true); }, function () { after(fallbackCopy(text)); });
        return;
      }
    } catch (e) { /* valt door naar het tekstveld */ }
    after(fallbackCopy(text));
  }

  render();
  // Met JavaScript loop je de stappen door; de eindknop komt pas als alles staat.
  if (next) next.hidden = false;
  if (done) done.hidden = true;

  root.addEventListener("click", function (e) {
    var t = e.target;
    var li = t.closest && t.closest("[data-ck-step]");
    var i = li ? steps.indexOf(li) : -1;
    var val = t.closest && t.closest("[data-ck-copy]");
    if (val && i !== -1) {
      var text = val.getAttribute("data-ck-copy"), cta = val.querySelector("[data-ck-cta]");
      copy(text, val.querySelector("[data-ck-num]"), function (ok) {
        if (cta) cta.textContent = ok ? "Gekopieerd" : "Geselecteerd, kopieer zelf";
        val.classList.toggle("is-copied", ok);
        setTimeout(function () { if (cta) cta.textContent = "Tik om te kopiëren"; val.classList.remove("is-copied"); }, 1800);
      });
      finish(i);
      return;
    }
    var choice = t.closest && t.closest("[data-ck-choice]");
    if (choice && li) {
      li.querySelectorAll("[data-ck-choice]").forEach(function (b) { b.setAttribute("aria-pressed", b === choice ? "true" : "false"); });
      var target = li.querySelector("[data-ck-copy]");
      if (target) {
        target.setAttribute("data-ck-copy", choice.getAttribute("data-ck-choice"));
        var num = target.querySelector("[data-ck-num]");
        if (num) num.textContent = choice.getAttribute("data-ck-text");
      }
      return;
    }
    if (t.closest && t.closest("[data-ck-go]") && i !== -1) {
      // Een stap zonder getal (instrument en richting) vink je af met een tik; bij een stap met getal zet een tik hem alleen voorop.
      if (!li.querySelector("[data-ck-copy]")) finish(i);
      else { cur = i; render(); }
      return;
    }
    if (t.closest && t.closest("[data-ck-next]")) {
      if (cur < steps.length) finish(cur);
      return;
    }
    if (t.closest && t.closest("[data-ck-back]") && cur > 0) {
      e.preventDefault();
      cur = cur - 1;
      finished[cur] = false;
      render();
      focusStep(cur);
    }
  });

  // Koers nu en of hij nog in de zone staat: dezelfde stand als op de Radar. Een Setups-plan heeft geen radarkaart; dan blijft de serverregel staan.
  var key = root.getAttribute("data-ck-key");
  if (!key || key.indexOf("structuur:") === 0) return;
  var priceEl = root.querySelector('[data-ck="price"]'), noteEl = root.querySelector('[data-ck="note"]');
  function fmt(v) {
    if (Math.abs(v) < 1) { var d = 4 - Math.floor(Math.log10(Math.abs(v))); return v.toFixed(d).replace(/0+$/, "").replace(/\.$/, "").replace(".", ","); }
    return (Math.abs(v) < 100 ? v.toFixed(4) : v.toFixed(2)).replace(".", ",");
  }
  function note(d) {
    if (d.state === "in_zone") return "nog in zone";
    if (d.state === "wacht" && d.distance_pct !== null && d.distance_pct !== undefined) return "nog " + d.distance_pct.toFixed(2).replace(".", ",") + "% tot instap";
    if (d.state === "door_zone") return "door de zone heen";
    if (d.state === "ongeldig") return "plan vervallen, stop geraakt";
    return "";
  }
  function refresh() {
    if (document.hidden) return;
    fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        var d = payload && payload[key];
        if (!d) return;
        if (priceEl && d.price) priceEl.textContent = fmt(d.price);
        if (noteEl) noteEl.textContent = note(d);
      })
      .catch(function () { /* de laatste stand blijft staan */ });
  }
  setInterval(refresh, 15000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
