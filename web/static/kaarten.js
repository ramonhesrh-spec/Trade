// Kansen (ontwerp V4): een tik op de kop van een kaart, of op de kaart naast de grafiek, opent het detailblad van die kans. Het blad volgt de
// vinger 1:1 als je het aan de greep omlaag trekt en sluit bij loslaten; Escape en de knop sluiten ook. De ladders in het blad schuiven live mee:
// de koers komt van /api/radar (radar.js haalt die al op, hier alleen de prijs) en tussendoor van de koersstroom van live.js als die vers is.
(function () {
  window.hesKansenSummary = summary;
  window.hesHiddenText = hiddenText;
  window.hesHiddenLabel = hiddenLabel;
  var sheet = document.querySelector("[data-kd]");
  if (!sheet) return;
  var panel = sheet.querySelector("[data-kd-panel]");
  var rm = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var lastFocus = null;
  // In <main> zou het blad onder het dok vallen (main heeft een eigen stapel); aan body ligt het erboven.
  document.body.appendChild(sheet);

  function openSheet(key, opener) {
    var item = null;
    sheet.querySelectorAll("[data-kd-item]").forEach(function (s) {
      var on = s.getAttribute("data-kd-item") === key;
      s.hidden = !on;
      if (on) item = s;
    });
    if (!item) return;
    lastFocus = opener || document.activeElement;
    sheet.hidden = false;
    void sheet.offsetWidth;
    panel.scrollTop = 0;
    panel.style.transform = "";
    sheet.classList.add("is-open");
    document.documentElement.classList.add("kd-lock");
    var title = item.querySelector(".kd-title");
    if (title) title.focus({ preventScroll: true });
    live();
  }
  function closeSheet() {
    if (!sheet.classList.contains("is-open")) return;
    sheet.classList.remove("is-open");
    panel.style.transform = "";
    document.documentElement.classList.remove("kd-lock");
    setTimeout(function () { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, rm ? 0 : 260);
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }

  document.addEventListener("click", function (e) {
    if (hideClick(e)) return;
    var head = e.target.closest && e.target.closest("[data-kc-open]");
    if (head) { openSheet(head.getAttribute("data-kc-open"), head); return; }
    var card = e.target.closest && e.target.closest("[data-kc]");
    // Een levelchart-grafiek is van levelchart.js (tik = groot), links en knoppen doen hun eigen werk; een getekende kaart (svg) opent het blad.
    if (card && !e.target.closest(".lc .level-chart, a, button")) openSheet(card.getAttribute("data-kc"), card.querySelector("[data-kc-open]"));
  });
  sheet.querySelectorAll("[data-kd-close]").forEach(function (b) {
    b.addEventListener("click", function () { if (b._dragged) { b._dragged = false; return; } closeSheet(); });
  });
  sheet.addEventListener("click", function (e) { if (e.target === sheet) closeSheet(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeSheet(); });

  // Omlaag trekken aan de greep: 1:1 met de vinger, bij loslaten dicht of terug.
  var grab = sheet.querySelector(".kd-grab");
  if (grab) {
    var startY = 0, dy = 0, active = false, moved = false;
    grab.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      active = true; moved = false; startY = e.clientY; dy = 0;
      try { grab.setPointerCapture(e.pointerId); } catch (err) { /* zonder capture werkt de tik nog */ }
    });
    grab.addEventListener("pointermove", function (e) {
      if (!active) return;
      dy = Math.max(0, e.clientY - startY);
      if (!moved && dy < 6) return;
      moved = true;
      sheet.classList.add("is-dragging");
      panel.style.transform = "translateY(" + dy + "px)";
    });
    function end() {
      if (!active) return;
      active = false;
      sheet.classList.remove("is-dragging");
      if (!moved) return;
      grab._dragged = true;
      if (dy > Math.min(120, (panel.offsetHeight || innerHeight) * 0.2)) closeSheet();
      else panel.style.transform = "";
    }
    grab.addEventListener("pointerup", end);
    grab.addEventListener("pointercancel", end);
  }

  // ===== Live koers op de ladders =====
  function live() {
    if (!window.hesLadder || !window.__livePrices) return;
    Object.keys(window.__livePrices).forEach(function (coin) { window.hesLadder.updateCoin(coin, window.__livePrices[coin]); });
  }
  setInterval(function () {
    if (document.hidden || sheet.hidden || !(window.hesLiveFresh && window.hesLiveFresh())) return;
    live();
  }, 1000);
  function poll() {
    if (document.hidden || sheet.hidden) return;
    fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        if (!payload || !window.hesLadder || (window.hesLiveFresh && window.hesLiveFresh())) return;
        Object.keys(payload).forEach(function (k) {
          var d = payload[k], card = document.querySelector('[data-kc="' + k + '"] [data-live-coin]');
          if (d && d.price && card) window.hesLadder.updateCoin(card.getAttribute("data-live-coin"), d.price);
        });
      })
      .catch(function () { /* de laatste stand blijft staan */ });
  }
  setInterval(poll, 15000);

  // ===== De eigen kaartgrafiek van Zone-radar en Zone-sweep (/api/kaart_svg, app/card_chart.py) =====
  // Pas als de kaart bijna in beeld is, en hoogstens MAX_SVG tegelijk onderweg: een lange tab op een telefoon haalt niet alles in één keer op.
  var MAX_SVG = 4, busy = 0, queue = [];
  function pump() {
    while (busy < MAX_SVG && queue.length) {
      var fig = queue.shift(), box = fig.querySelector(".kc-svg-box");
      if (!box || fig._svgDone) continue;
      fig._svgDone = true;
      busy++;
      fetch(fig.getAttribute("data-kc-svg"), { cache: "no-store", credentials: "same-origin" })
        .then((function (b, f) { return function (r) {
          // Geen eigen tekening (een signaal zonder setup-rij): dan de gewone kaartgrafiek, die levelchart.js tekent zodra hij zichtbaar is.
          var lc = f.querySelector("[data-levelchart]");
          if (r.status === 404 && lc) {
            b.hidden = true; lc.hidden = false; f.classList.add("is-fallback");
            var cap = f.querySelector(".lc-cap");
            if (cap) cap.textContent = "15 min per candle \u00b7 jouw tijd";
            return "fallback";
          }
          return r.ok ? r.text() : "";
        }; })(box, fig))
        .then((function (b, f) { return function (svg) {
          if (svg === "fallback") return;
          if (svg && svg.indexOf("<svg") === 0) { b.innerHTML = svg; f.classList.add("is-drawn"); }
          else { b.querySelector(".kc-svg-wait").textContent = "Grafiek nu niet beschikbaar"; f._svgDone = false; }
        }; })(box, fig))
        .catch((function (b, f) { return function () { b.querySelector(".kc-svg-wait").textContent = "Grafiek nu niet beschikbaar"; f._svgDone = false; }; })(box, fig))
        .then(function () { busy--; pump(); });
    }
  }
  var figs = document.querySelectorAll("[data-kc-svg]");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { io.unobserve(en.target); queue.push(en.target); } });
      pump();
    }, { rootMargin: "300px 0px" });
    figs.forEach(function (f) { io.observe(f); });
  } else {
    figs.forEach(function (f) { queue.push(f); });
    pump();
  }

  // ===== Tellers boven de kansen =====
  // De server zet de getallen (app/kansen.py, tabs[].n en in_zone); hier alleen opnieuw tellen wat er op de pagina staat zodra radar.js een
  // kaart van stand laat wisselen. Dezelfde woorden als kansen.summary (tests/test_static_js.py).
  function summary(n, zone, open) {
    if (!n && !open) return "Geen kansen";
    var parts = n ? [n + (n === 1 ? " kans klaar" : " kansen klaar")] : [];
    if (zone) parts.push(zone + " in de zone");
    if (open) parts.push(open + " open");
    return parts.join(" \u00b7 ");
  }
  function recount() {
    var tn = 0, tz = 0, to = 0;
    document.querySelectorAll('[data-utabs-panels="kansen"] > [data-utab-panel]').forEach(function (panel) {
      var plans = panel.querySelectorAll("[data-kt-plans] > .kc:not(.is-moot)"), zone = 0;
      plans.forEach(function (c) { if (c.querySelector(".kc-head .state-pill.is-in_zone")) zone++; });
      var open = panel.querySelectorAll("[data-kt-trades] > .kc").length, n = plans.length;
      tn += n; tz += zone; to += open;
      var sum = panel.querySelector(".kt-sum");
      if (sum) sum.textContent = summary(n, zone, open);
      var tab = document.getElementById(panel.id + "-tab");
      if (!tab) return;
      var num = tab.querySelector("[data-ut-num]");
      if (num) num.textContent = n;
      var badge = tab.querySelector("[data-ut-badge]");
      if (zone && !badge) {
        badge = document.createElement("i");
        badge.className = "ut-badge";
        badge.setAttribute("data-ut-badge", "");
        tab.appendChild(badge);
      }
      if (badge && !zone) badge.remove();
      else if (badge) badge.innerHTML = zone + '<span class="sr-only"> in de zone</span>';
    });
    var total = document.querySelector("[data-kansen-total]");
    if (total) {
      var next = summary(tn, tz, to);
      if (total.textContent !== next) total.textContent = next;
    }
    groups();
  }
  document.addEventListener("hp:radar", recount);

  // ===== Verbergen (kans_hidden, POST /api/kans/verberg en /api/kans/toon) =====
  // Alleen de weergave van deze gebruiker. De kaart klapt meteen weg (eerst tonen, dan opslaan) en schuift naar de onzichtbare voorraad van zijn
  // tab, met een rij onder "Verborgen (N)"; een balk van 5 s biedt Ongedaan. Een verborgen kaart staat buiten [data-kt-plans] en
  // [data-kt-trades], dus recount telt hem nergens mee. Dezelfde woorden als app/kansen.py (tests/test_static_js.py).
  function hiddenText(titles) { return titles.length === 1 ? titles[0] + " verborgen" : titles.length + " kaarten verborgen"; }
  function hiddenLabel(n) { return n ? "Verborgen (" + n + ")" : ""; }
  function send(url, keys) {
    return fetch(url, { method: "POST", credentials: "same-origin", keepalive: true, headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ keys: keys }) })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r; });
  }
  function keysOf(card) { return (card.getAttribute("data-kc-keys") || card.getAttribute("data-kc")).split(","); }
  function panelOf(el) { return el.closest("[data-utab-panel]"); }
  function listOf(panel, group) { return panel.querySelector("[data-kt-" + group + "]"); }

  function groups() {
    document.querySelectorAll('[data-utabs-panels="kansen"] > [data-utab-panel]').forEach(function (panel) {
      panel.querySelectorAll("[data-kt-group]").forEach(function (g) {
        var n = g.querySelectorAll(".kc-list > .kc").length, all = g.querySelector("[data-kt-hide-all]");
        g.hidden = !n;
        if (all) all.hidden = n < 2;
      });
      var box = panel.querySelector("[data-kt-hidden]");
      if (!box) return;
      var rows = box.querySelectorAll("[data-kh]").length;
      box.hidden = !rows;
      if (!rows) box.open = false;
      box.querySelector("[data-kt-hidden-label]").textContent = hiddenLabel(rows);
    });
  }

  function addRow(panel, card) {
    var rows = panel.querySelector("[data-kt-hidden-rows]"), key = card.getAttribute("data-kc");
    if (!rows || rows.querySelector('[data-kh="' + key + '"]')) return;
    var li = document.createElement("li"), b = document.createElement("b"), st = document.createElement("span"), btn = document.createElement("button");
    var pill = card.querySelector(".kc-head .state-pill");
    li.className = "kt-hid-row";
    li.setAttribute("data-kh", key);
    li.setAttribute("data-kh-keys", keysOf(card).join(","));
    li.setAttribute("data-kh-group", card.getAttribute("data-kc-group"));
    b.textContent = card.getAttribute("data-kc-title");
    st.textContent = pill ? pill.textContent : "";
    btn.type = "button"; btn.className = "kt-show"; btn.setAttribute("data-kt-show", ""); btn.textContent = "Toon weer";
    li.appendChild(b); li.appendChild(st); li.appendChild(btn);
    rows.insertBefore(li, rows.firstChild);
  }

  // Klapt de kaarten dicht (hoogte vast, dan nul) en zet ze daarna in de voorraad. Zonder beweging meteen.
  function collapse(cards, done) {
    if (rm) { done(); return; }
    cards.forEach(function (c) { c.style.height = c.offsetHeight + "px"; });
    void document.body.offsetWidth;
    cards.forEach(function (c) { c.classList.add("is-leaving"); c.style.height = "0px"; c.style.paddingBottom = "0px"; c.style.borderWidth = "0px"; });
    setTimeout(done, 200);
  }
  function stash(card) {
    var panel = panelOf(card), box = panel && panel.querySelector("[data-kt-stash]");
    card.classList.remove("is-leaving", "is-back");
    card.style.height = card.style.paddingBottom = card.style.borderWidth = "";
    if (box) box.appendChild(card);
    if (panel) addRow(panel, card);
  }
  // Terug in de lijst: op zijn oude plek als die er nog is (Ongedaan), anders onderaan zijn groep (Toon weer; de volgende keer staat hij weer op volgorde).
  function unstash(card, parent, next) {
    var panel = panelOf(card), row = panel && panel.querySelector('[data-kh="' + card.getAttribute("data-kc") + '"]');
    if (row) row.remove();
    var list = parent || (panel && listOf(panel, card.getAttribute("data-kc-group")));
    if (!list) return;
    if (next && next.parentNode === list) list.insertBefore(card, next); else list.appendChild(card);
    card.classList.remove("is-leaving");
    card.style.height = card.style.paddingBottom = card.style.borderWidth = "";
    if (!rm) { card.classList.remove("is-back"); void card.offsetWidth; card.classList.add("is-back"); }
  }

  var toastEl = null, toastTimer = 0;
  function toast(text, onUndo) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "kt-toast";
      toastEl.setAttribute("role", "status");
      toastEl.setAttribute("aria-live", "polite");
      toastEl.innerHTML = '<span class="kt-toast-text"></span><button type="button" class="kt-toast-undo">Ongedaan</button><i class="kt-toast-time" aria-hidden="true"></i>';
      document.body.appendChild(toastEl);
    }
    var undo = toastEl.querySelector(".kt-toast-undo"), time = toastEl.querySelector(".kt-toast-time");
    toastEl.querySelector(".kt-toast-text").textContent = text;
    undo.hidden = !onUndo;
    undo.onclick = function () { hideToast(); if (onUndo) onUndo(); };
    clearTimeout(toastTimer);
    toastEl.classList.remove("is-on");
    time.style.animation = "none"; void time.offsetWidth; time.style.animation = "";
    toastEl.hidden = false;
    void toastEl.offsetWidth;
    toastEl.classList.add("is-on");
    toastTimer = setTimeout(hideToast, 5000);
  }
  function hideToast() {
    clearTimeout(toastTimer);
    if (!toastEl) return;
    toastEl.classList.remove("is-on");
    setTimeout(function () { if (!toastEl.classList.contains("is-on")) toastEl.hidden = true; }, rm ? 0 : 200);
  }

  // Het getal op Kansen in het dok en op het appicoon komt van de server (radar.in_zone_count zonder jouw verborgen kaarten): na een wijziging opnieuw vragen.
  function refreshBadge() {
    fetch("/api/system_status", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s || typeof s.in_zone !== "number") return;
        var tab = document.querySelector('.tabbar a[href="/smc"]'), badge = tab && tab.querySelector(".tab-badge");
        if (tab && s.in_zone && !badge) {
          badge = document.createElement("i");
          badge.className = "tab-badge";
          tab.appendChild(badge);
        }
        if (badge && !s.in_zone) badge.remove();
        else if (badge) { badge.textContent = s.in_zone; badge.setAttribute("aria-label", s.in_zone + " in de zone"); }
        try {
          if ("setAppBadge" in navigator) (s.in_zone > 0 ? navigator.setAppBadge(s.in_zone) : navigator.clearAppBadge()).catch(function () {});
        } catch (e) { /* geen appicoon */ }
      })
      .catch(function () { /* de volgende statuspoll van base.html zet het goed */ });
  }

  function hide(cards) {
    cards = cards.filter(function (c) { return c && !c.closest("[data-kt-stash]"); });
    if (!cards.length) return;
    var spots = cards.map(function (c) { return { card: c, parent: c.parentNode, next: c.nextElementSibling }; });
    var keys = [].concat.apply([], cards.map(keysOf)), titles = cards.map(function (c) { return c.getAttribute("data-kc-title"); });
    var back = function () {
      spots.slice().reverse().forEach(function (s) { unstash(s.card, s.parent, s.next); });
      recount();
    };
    collapse(cards, function () { cards.forEach(stash); recount(); });
    var saved = send("/api/kans/verberg", keys).then(refreshBadge).catch(function () { back(); toast("Verbergen lukte niet, de kaart staat er weer", null); });
    toast(hiddenText(titles), function () {
      back();
      // Pas na het verbergen: anders kan Toon de server eerder bereiken en blijft de kaart daar verborgen.
      saved.then(function () { return send("/api/kans/toon", keys); }).then(refreshBadge).catch(function () { location.reload(); });
    });
  }
  function show(rows) {
    if (!rows.length) return;
    var keys = [];
    rows.forEach(function (row) {
      keys = keys.concat(row.getAttribute("data-kh-keys").split(","));
      var panel = panelOf(row), card = panel && panel.querySelector('[data-kt-stash] [data-kc="' + row.getAttribute("data-kh") + '"]');
      if (card) unstash(card); else row.remove();
    });
    recount();
    send("/api/kans/toon", keys).then(refreshBadge).catch(function () { location.reload(); });
  }

  function hideClick(e) {
    var t = e.target.closest && e.target.closest("[data-kc-hide], [data-kd-hide], [data-kt-hide-all], [data-kt-show], [data-kt-show-all]");
    if (!t) return false;
    e.preventDefault();
    if (t.hasAttribute("data-kc-hide")) hide([t.closest("[data-kc]")]);
    else if (t.hasAttribute("data-kd-hide")) {
      closeSheet();
      var key = t.getAttribute("data-kd-hide");
      hide([].filter.call(document.querySelectorAll('[data-kc="' + key + '"]'), function (c) { return !c.closest("[data-kt-stash]"); }));
    } else if (t.hasAttribute("data-kt-hide-all")) hide([].slice.call(t.closest("[data-kt-group]").querySelectorAll(".kc-list > .kc")));
    else if (t.hasAttribute("data-kt-show")) show([t.closest("[data-kh]")]);
    else show([].slice.call(t.closest("[data-kt-hidden]").querySelectorAll("[data-kh]")));
    return true;
  }

  // Een melding die naar een verborgen kaart wijst (/smc#radar-zone-8): utabs.js opent de tab, hier klapt "Verborgen" open op die rij.
  function revealHashed() {
    var id = decodeURIComponent((location.hash || "").slice(1)), el = id && document.getElementById(id);
    var box = el && el.closest("[data-kt-stash]") && panelOf(el).querySelector("[data-kt-hidden]");
    if (!box) return;
    box.open = true;
    var row = box.querySelector('[data-kh="' + el.getAttribute("data-kc") + '"]');
    if (row) row.scrollIntoView({ block: "center" });
  }
  revealHashed();
  window.addEventListener("hashchange", revealHashed);
})();
