// Koersen die echt live bewegen: de browser luistert rechtstreeks naar de koersstroom van de beurt (eens per seconde per coin) en werkt
// prijzen en afstanden bij zodra er een nieuwe koers is. De server blijft de bron voor kaarten en uitkomsten, dit maakt alleen het getal levend.
// Valt de verbinding weg of staat het tabblad verborgen, dan verversen de gewone polls het weer.
(function (root) {
  var LIVE_FRESH_MS = 8000;
  // Versheid per coin: vroeger één gedeeld tijdstip (__liveAt) voor alle coins, zodat één tikkende coin een stille coin vers liet lijken en
  // radar.js de serverafstand van die stille coin oversloeg. Zonder coin: pas vers als elke coin op de pagina vers is.
  function freshAt(byCoin, coins, now, coin) {
    var list = coin ? [coin] : coins;
    if (!list.length) return false;
    return list.every(function (c) { return byCoin[c] !== undefined && now - byCoin[c] < LIVE_FRESH_MS; });
  }
  root.hesLiveFreshAt = freshAt;

  // Dezelfde markt als de candles (app/candle_source.py): perps op fstream, spot op de spotstroom. `map` (meta live-symbols) geeft per
  // afwijkende coin [streamsymbool, schaal, markt]: 1000PEPEUSDT noteert 1000 munten, dus de koers wordt gedeeld door 1000 (prijs per munt,
  // zoals de kaarten). Eén verbinding per markt die echt nodig is.
  var HOSTS = { perp: "wss://fstream.binance.com/stream?streams=", spot: "wss://stream.binance.com:9443/stream?streams=" };
  function streams(list, market, map, quote) {
    var groups = {}, order = [];
    list.forEach(function (c) {
      var m = map[c], sym = m ? m[0] : (c + quote).toUpperCase(), scale = m ? m[1] : 1, mk = m ? m[2] : market;
      if (!HOSTS[mk]) mk = "spot";
      if (!groups[mk]) { groups[mk] = { names: [], symbols: {} }; order.push(mk); }
      groups[mk].names.push(sym.toLowerCase() + "@miniTicker");
      groups[mk].symbols[sym] = [c, scale];
    });
    return order.map(function (mk) { return { url: HOSTS[mk] + groups[mk].names.join("/"), symbols: groups[mk].symbols }; });
  }
  root.hesLiveStreams = streams;
  if (typeof document === "undefined") return;

  function meta(name) { var m = document.querySelector('meta[name="' + name + '"]'); return m ? m.getAttribute("content") : ""; }
  var exchange = meta("live-exchange"), quote = (meta("live-quote") || "usdt").toLowerCase();
  var market = meta("live-market") || "spot", symbolMap = {};
  try { symbolMap = JSON.parse(meta("live-symbols") || "{}"); } catch (e) { symbolMap = {}; }
  if (exchange !== "binance") return;

  var coins = {};
  document.querySelectorAll("[data-vd-price]").forEach(function (el) { coins[el.getAttribute("data-vd-price")] = 1; });
  document.querySelectorAll("[data-live-coin]").forEach(function (el) { coins[el.getAttribute("data-live-coin")] = 1; });
  document.querySelectorAll("[data-chart-coin]").forEach(function (el) { coins[el.getAttribute("data-chart-coin")] = 1; });
  var list = Object.keys(coins);
  if (!list.length) return;

  window.__livePrices = {};
  window.__liveAtByCoin = {};
  window.__liveCoins = list;
  window.hesLiveFresh = function (coin) { return freshAt(window.__liveAtByCoin, list, Date.now(), coin); };

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
    document.querySelectorAll('[data-vd-price="' + coin + '"]').forEach(function (el) {
      var next = fmtPrice(p, coin), before = parseFloat(el.getAttribute("data-px"));
      if (el.textContent === next) return;
      el.textContent = next;
      el.setAttribute("data-px", String(p));
      if (!isNaN(before) && before !== p) {
        el.classList.remove("px-up", "px-down");
        void el.offsetWidth;
        el.classList.add(p > before ? "px-up" : "px-down");
      }
    });
    document.querySelectorAll('[data-live-coin="' + coin + '"]').forEach(function (el) {
      var level = parseFloat(el.getAttribute("data-live-level"));
      if (isNaN(level)) return;
      var v = distance(el.getAttribute("data-live-mode"), level, p);
      el.textContent = (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
      if (el.parentElement && el.parentElement.hasAttribute("hidden")) el.parentElement.removeAttribute("hidden");
    });
  }

  // Per markt een eigen verbinding met eigen herstart, zodat een haperende spotstroom de perpstroom niet stillegt.
  var conns = streams(list, market, symbolMap, quote).map(function (g) { return { g: g, ws: null, retry: 1000, timer: null }; });
  function connect(c) {
    if (document.hidden || c.ws) return;
    try { c.ws = new WebSocket(c.g.url); } catch (e) { c.ws = null; return; }
    c.ws.onopen = function () { c.retry = 1000; };
    c.ws.onmessage = function (e) {
      try {
        var d = JSON.parse(e.data).data, hit = c.g.symbols[d.s];
        if (!hit) return;
        var coin = hit[0], p = parseFloat(d.c) / hit[1];
        if (isNaN(p)) return;
        window.__liveAtByCoin[coin] = Date.now();
        window.__livePrices[coin] = p;
        apply(coin, p);
      } catch (err) { /* een kapot bericht slaan we over */ }
    };
    c.ws.onclose = function () { c.ws = null; if (!document.hidden) { c.timer = setTimeout(function () { connect(c); }, c.retry); c.retry = Math.min(c.retry * 2, 15000); } };
    c.ws.onerror = function () { try { c.ws.close(); } catch (e) {} };
  }
  document.addEventListener("visibilitychange", function () {
    conns.forEach(function (c) {
      if (document.hidden) { clearTimeout(c.timer); if (c.ws) c.ws.close(); } else { c.retry = 1000; connect(c); }
    });
  });
  conns.forEach(connect);
})(typeof window !== "undefined" ? window : globalThis);
