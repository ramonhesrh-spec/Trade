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

  function apply(coin, p) {
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
