// De prijsladder in het detailblad: de server tekent de lijnen op hun prijs (app/ladder.py, macro `ladder`); hier schuift alleen de koers mee.
// Dezelfde formules als app/ladder.py (tests/test_static_js.py legt ze naast elkaar): y in procent van de ladderhoogte, het koerslabel in zijn
// eigen kolom (labelY), afstand zoals trade_plan.distance_to_limit_pct, de balk van de dichtstbijzijnde zonerand naar de koers. Bij reduced
// motion springt de lijn en wisselt alleen de opacity van het getal (120 ms).
// Daarnaast: houd een getal vast om het te kopiëren ([data-hold-copy]): een balk loopt in 450 ms vol, dan staat het op het klembord.
(function (root) {
  var PRICE_EDGE = 34 / 2 / 240 * 100;          // ladder.PRICE_EDGE: PRICE_PX / 2 / HEIGHT_PX
  function y(p, hi, lo) { return Math.min(100, Math.max(0, (hi - p) / (hi - lo) * 100)); }
  function labelY(py) { return Math.min(100 - PRICE_EDGE, Math.max(PRICE_EDGE, py)); }
  function distance(dir, limit, p) { return dir === "long" ? (p - limit) / limit * 100 : (limit - p) / limit * 100; }
  // app/price_text.py: 2 decimalen vanaf 10, 3 vanaf 1, 4 vanaf 0,01, daaronder 6 maar altijd drie cijfers die tellen.
  function decimals(v) {
    var a = Math.abs(v);
    if (a >= 10) return 2;
    if (a >= 1) return 3;
    if (a >= 0.01) return 4;
    if (a === 0) return 0;
    return Math.max(6, 2 - Math.floor(Math.log10(a)));
  }
  function plain(v) { return v.toFixed(decimals(v)); }
  function nl(v) { return plain(v).replace(".", ","); }
  function pct(v) { return v.toFixed(2).replace(".", ",") + "%"; }
  function rText(v) { return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).replace(".", ",") + " R"; }
  // De balk loopt van de zonerand die het dichtst bij de koers ligt (of de instap, zonder zone) naar de koers; in de zone is hij weg.
  function gap(zlo, zhi, entry, p, hi, lo) {
    var edge, inZone = false;
    if (zlo != null && zhi != null) {
      inZone = p >= zlo && p <= zhi;
      edge = p > zhi ? zhi : p < zlo ? zlo : p;
    } else {
      edge = entry;
    }
    var ey = y(edge, hi, lo), py = y(p, hi, lo);
    return { top: Math.min(ey, py), height: Math.abs(py - ey), inZone: inZone };
  }
  // ladder.stale_text: pas een koers ouder dan 30 s krijgt een regel.
  function stale(age) {
    if (age == null || age <= 30) return "";
    if (age < 120) return "Koers " + Math.floor(age) + " s oud";
    if (age < 3600) return "Koers " + Math.floor(age / 60) + " min oud";
    return "Koers " + Math.floor(age / 3600) + " u oud";
  }
  root.hesLadderMath = { y: y, labelY: labelY, distance: distance, nl: nl, plain: plain, gap: gap, stale: stale, pct: pct, rText: rText };
  if (typeof document === "undefined") return;

  var rm = !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function num(el, name) { var v = parseFloat(el.getAttribute(name)); return isNaN(v) ? null : v; }
  function setText(el, text) {
    if (!el || el.textContent === text) return;
    el.textContent = text;
    if (rm) {                                   // reduced motion: geen verschuiving, alleen een korte opacity-wissel
      el.style.transition = "none"; el.style.opacity = "0.4";
      void el.offsetWidth;
      el.style.transition = "opacity 120ms linear"; el.style.opacity = "1";
    }
  }

  function update(el, price) {
    if (!el || !price || !isFinite(price)) return;
    var hi = num(el, "data-lad-hi"), lo = num(el, "data-lad-lo");
    if (hi === null || lo === null || hi === lo) return;
    var dir = el.getAttribute("data-lad-dir"), py = y(price, hi, lo);
    var line = el.querySelector('[data-lad="price"]');
    if (line) line.style.top = py + "%";
    var lab = el.querySelector('[data-lad="price-label"]');
    if (lab) lab.style.top = labelY(py) + "%";
    el.querySelectorAll('[data-lad="price-text"]').forEach(function (t) { setText(t, nl(price)); });
    var zlo = num(el, "data-lad-zlo"), zhi = num(el, "data-lad-zhi"), entry = num(el, "data-lad-entry"), limit = num(el, "data-lad-limit");
    var bar = el.querySelector('[data-lad="gap"]');
    if (bar) {
      var g = gap(zlo, zhi, entry !== null ? entry : limit, price, hi, lo);
      bar.style.top = g.top + "%";
      bar.style.height = g.height + "%";
      el.classList.toggle("is-in-zone", g.inZone);
    }
    if (limit !== null) {
      var d = distance(dir, limit, price);
      if (d > 0) setText(el.querySelector('[data-lad="distance"]'), pct(d));     // voorbij de limiet beslist de server (herladen)
    }
    var stop = num(el, "data-lad-stop");
    if (el.getAttribute("data-ladder") === "trade" && entry !== null && stop !== null && entry !== stop) {
      var r = (dir === "long" ? price - entry : entry - price) / Math.abs(entry - stop);
      var rEl = el.querySelector('[data-lad="live_r"]');
      setText(rEl, rText(r));
      if (rEl) rEl.className = "lad-num " + (r > 0 ? "pos" : r < 0 ? "neg" : "");
    }
  }

  function updateCoin(coin, price) {
    document.querySelectorAll('[data-ladder][data-lad-coin="' + coin + '"]').forEach(function (el) { update(el, price); });
  }
  root.hesLadder = { update: update, updateCoin: updateCoin };

  // ===== Houd vast om te kopiëren =====
  // Safari staat het klembord alleen toe binnen een gebaar; lukt het na de 450 ms niet, dan nog een keer bij het loslaten (ook een gebaar).
  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, text.length);
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }
  function copyText(text) {
    try {
      if (navigator.clipboard && root.isSecureContext) return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallbackCopy(text); });
    } catch (e) { /* valt terug */ }
    return Promise.resolve(fallbackCopy(text));
  }

  var HOLD_MS = 450, SHOWN_MS = 1600;
  var holding = null;

  function label(btn, text, on) {
    var lab = btn.querySelector("[data-hold-label]");
    if (!lab) return;
    if (!lab.hasAttribute("data-hold-orig")) lab.setAttribute("data-hold-orig", lab.textContent);
    lab.textContent = on ? text : lab.getAttribute("data-hold-orig");
  }
  function done(btn, ok) {
    btn.classList.remove("is-holding");
    btn.classList.add(ok ? "is-copied" : "is-failed");
    label(btn, ok ? "Gekopieerd" : "Kopiëren lukte niet", true);
    clearTimeout(btn._holdShown);
    btn._holdShown = setTimeout(function () { btn.classList.remove("is-copied", "is-failed"); label(btn, "", false); }, SHOWN_MS);
  }
  function cancel() {
    if (!holding) return;
    clearTimeout(holding.timer);
    if (!holding.fired) holding.btn.classList.remove("is-holding");
    holding = null;
  }

  document.addEventListener("pointerdown", function (e) {
    var btn = e.target.closest && e.target.closest("[data-hold-copy]");
    if (!btn || (e.pointerType === "mouse" && e.button !== 0)) return;
    cancel();
    btn.classList.remove("is-copied", "is-failed");
    btn.classList.add("is-holding");
    var h = holding = { btn: btn, fired: false, pending: false, x: e.clientX, y: e.clientY };
    h.timer = setTimeout(function () {
      h.fired = true;
      copyText(btn.getAttribute("data-hold-copy")).then(function (ok) { if (ok) done(btn, true); else h.pending = true; });
    }, HOLD_MS);
  });
  document.addEventListener("pointermove", function (e) {
    if (holding && !holding.fired && (Math.abs(e.clientX - holding.x) > 10 || Math.abs(e.clientY - holding.y) > 10)) cancel();   // scrollen is geen vasthouden
  });
  document.addEventListener("pointerup", function () {
    if (holding && holding.pending) {
      var b = holding.btn;
      done(b, fallbackCopy(b.getAttribute("data-hold-copy")));
    }
    cancel();
  });
  document.addEventListener("pointercancel", cancel);
  document.addEventListener("contextmenu", function (e) { if (e.target.closest && e.target.closest("[data-hold-copy]")) e.preventDefault(); });
  // Toetsenbord en schermlezer: Enter of spatie kopieert meteen (detail 0 = geen aanwijzer), vasthouden kan daar niet.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-hold-copy]");
    if (!btn || e.detail !== 0) return;
    copyText(btn.getAttribute("data-hold-copy")).then(function (ok) { done(btn, ok); });
  });
})(typeof window !== "undefined" ? window : this);
