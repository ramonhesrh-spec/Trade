// Koersen die echt live bewegen: de browser luistert rechtstreeks naar de koersstroom van de beurt (eens per seconde per coin) en werkt
// prijzen en afstanden bij zodra er een nieuwe koers is. De server blijft de bron voor kaarten en uitkomsten, dit maakt alleen het getal levend.
// Valt de verbinding weg of staat het tabblad verborgen, dan verversen de gewone polls het weer.
(function () {
  function meta(name) { var m = document.querySelector('meta[name="' + name + '"]'); return m ? m.getAttribute("content") : ""; }
  var exchange = meta("live-exchange"), quote = (meta("live-quote") || "usdt").toLowerCase();
  if (exchange !== "binance") return;

  var coins = {};
  document.querySelectorAll("[data-vd-price]").forEach(function (el) { coins[el.getAttribute("data-vd-price")] = 1; });
  document.querySelectorAll("[data-live-coin]").forEach(function (el) { coins[el.getAttribute("data-live-coin")] = 1; });
  document.querySelectorAll("[data-chart-coin]").forEach(function (el) { coins[el.getAttribute("data-chart-coin")] = 1; });
  var list = Object.keys(coins);
  if (!list.length) return;

  window.__livePrices = {};
  window.hesLiveFresh = function () { return !!window.__liveAt && Date.now() - window.__liveAt < 8000; };

  function fmtPrice(value, coin) {
    if (coin === "BTC") return Math.round(value).toLocaleString("nl-NL");
    return value < 100 ? value.toFixed(4) : value.toFixed(2);
  }

  function distance(mode, level, p) {
    if (mode === "pl") return (p - level) / level * 100;
    if (mode === "ll") return (level - p) / level * 100;
    return (level - p) / p * 100;
  }

  var SVGNS = "http://www.w3.org/2000/svg", NEAR_LIMIT_PCT = 0.3;

  // De prijslijn op de grafiek schuift mee met de koers. Staat er nog geen prijslijn (de kaart kwam zonder prijs), dan maken we hem aan.
  function moveChart(svg, p) {
    var hi = parseFloat(svg.getAttribute("data-hi")), lo = parseFloat(svg.getAttribute("data-lo"));
    var padT = parseFloat(svg.getAttribute("data-pad-t")), plotH = parseFloat(svg.getAttribute("data-plot-h")), level = parseFloat(svg.getAttribute("data-level"));
    if ([hi, lo, padT, plotH].some(isNaN) || hi === lo) return;
    var y = Math.max(padT, Math.min(padT + plotH, padT + (hi - p) / (hi - lo) * plotH));
    var line = svg.querySelector("line.sc-price"), label = svg.querySelector("text.sc-price");
    var ref = svg.querySelector("line.sc-limit");
    if (!line && ref) {
      line = document.createElementNS(SVGNS, "line");
      line.setAttribute("class", "sc-line sc-price");
      line.setAttribute("x1", ref.getAttribute("x1")); line.setAttribute("x2", ref.getAttribute("x2"));
      label = document.createElementNS(SVGNS, "text");
      label.setAttribute("class", "sc-label sc-price");
      label.setAttribute("x", ref.nextElementSibling ? ref.nextElementSibling.getAttribute("x") : ref.getAttribute("x2"));
      svg.appendChild(line); svg.appendChild(label);
    }
    if (!line) return;
    line.setAttribute("y1", y.toFixed(1)); line.setAttribute("y2", y.toFixed(1));
    if (label) { label.setAttribute("y", (y + 4).toFixed(1)); label.textContent = "Nu " + fmtPrice(p, svg.getAttribute("data-chart-coin")); }
    if (!isNaN(level)) svg.classList.toggle("is-near", Math.abs(p - level) / level * 100 <= NEAR_LIMIT_PCT);
  }

  function apply(coin, p) {
    document.querySelectorAll('svg.sc[data-chart-coin="' + coin + '"]').forEach(function (svg) { moveChart(svg, p); });
    document.querySelectorAll('[data-vd-price="' + coin + '"]').forEach(function (el) { el.textContent = fmtPrice(p, coin); });
    document.querySelectorAll('[data-live-coin="' + coin + '"]').forEach(function (el) {
      var level = parseFloat(el.getAttribute("data-live-level"));
      if (isNaN(level)) return;
      var v = distance(el.getAttribute("data-live-mode"), level, p);
      el.textContent = (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
      if (el.parentElement && el.parentElement.hasAttribute("hidden")) el.parentElement.removeAttribute("hidden");
    });
  }

  var ws = null, retry = 1000, timer = null;
  function connect() {
    if (document.hidden || ws) return;
    var url = "wss://stream.binance.com:9443/stream?streams=" + list.map(function (c) { return c.toLowerCase() + quote + "@miniTicker"; }).join("/");
    try { ws = new WebSocket(url); } catch (e) { ws = null; return; }
    ws.onopen = function () { retry = 1000; };
    ws.onmessage = function (e) {
      try {
        var d = JSON.parse(e.data).data;
        var coin = d.s.slice(0, d.s.length - quote.length), p = parseFloat(d.c);
        if (isNaN(p)) return;
        window.__liveAt = Date.now();
        window.__livePrices[coin] = p;
        apply(coin, p);
      } catch (err) { /* een kapot bericht slaan we over */ }
    };
    ws.onclose = function () { ws = null; if (!document.hidden) { timer = setTimeout(connect, retry); retry = Math.min(retry * 2, 15000); } };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { clearTimeout(timer); if (ws) ws.close(); } else { retry = 1000; connect(); }
  });
  connect();
})();
