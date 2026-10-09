/* Candlegrafiek met de niveaus van een plan, op elke radar-kaart en op Vandaag. Een element met data-levelchart (JSON uit
   trade_plan.chart_spec: stop, take, limit, zone_low, zone_high, entry, price, direction), data-coin en data-tf krijgt een
   echte grafiek van lightweight-charts (vendor/lightweight-charts-4.2.0.*). De server stuurt getallen, hier wordt getekend.
   - Lazy: de grafiek wordt pas gemaakt als de kaart bijna in beeld komt en weer weggehaald als hij ver weg scrolt; nooit meer
     dan MAX_LIVE tegelijk, zodat een lange pagina op een telefoon soepel blijft.
   - Geen gebaren: scrollen en zoomen staan uit, een veeg over de grafiek scrolt gewoon de pagina (iOS).
   - Live: update(el, spec) verschuift de laatste candle en de Nu-lijn; de grafiek wordt niet opnieuw gemaakt.
   - Candles komen van /api/radar_candles (een minuut gecachet op de server en hier per coin+tijdframe gedeeld).
   De lightweight-charts-bibliotheek tekent zonder animatie, dus er is niets dat prefers-reduced-motion hoeft te dempen. */
(function () {
  var MAX_LIVE = 8;
  var CANDLE_LIMIT = 96;
  var REFRESH_MS = 60000;
  var LC = window.LightweightCharts;
  var api = { update: function () {}, screenshot: function () { return Promise.resolve(null); } };
  window.hesLevelChart = api;
  var els = document.querySelectorAll("[data-levelchart]");
  if (!LC || !els.length) return;

  var live = new Set();          // elementen met een echte grafiek
  var wanted = new Set();        // bijna in beeld, maar nog zonder grafiek (cap bereikt of ophalen mislukt)
  var memo = {};                 // "COIN|tf" -> {at, promise}

  function css(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function spec(el) {
    if (!el._spec) { try { el._spec = JSON.parse(el.getAttribute("data-levelchart")); } catch (e) { el._spec = null; } }
    return el._spec;
  }

  function levels(s) {
    return [s.stop, s.take, s.limit, s.zone_low, s.zone_high, s.entry, s.price].filter(function (v) { return typeof v === "number" && isFinite(v); });
  }

  function precision(s) {
    var ref = Math.abs(s.entry != null ? s.entry : s.limit);
    return ref >= 100 ? 2 : ref >= 1 ? 4 : 6;
  }

  function fetchCandles(coin, tf) {
    var key = coin + "|" + tf, hit = memo[key];
    if (hit && Date.now() - hit.at < REFRESH_MS - 2000) return hit.promise;
    var promise = fetch("/api/radar_candles/" + encodeURIComponent(coin) + "?tf=" + encodeURIComponent(tf) + "&limit=" + CANDLE_LIMIT, { credentials: "same-origin" })
      .then(function (resp) { if (!resp.ok) throw new Error("candles " + resp.status); return resp.json(); })
      .then(function (body) {
        return body.candles.map(function (c) { return { time: c[0], open: c[1], high: c[2], low: c[3], close: c[4] }; });
      });
    memo[key] = { at: Date.now(), promise: promise };
    promise.catch(function () { if (memo[key] && memo[key].promise === promise) delete memo[key]; });
    return promise;
  }

  function tickLabel(time, type) {
    var d = new Date(time * 1000);
    if (type <= 2) return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
    return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
  }

  function setLine(lc, key, price, options) {
    if (price === null || price === undefined) {
      if (lc.lines[key]) { lc.series.removePriceLine(lc.lines[key]); delete lc.lines[key]; }
      return;
    }
    var opts = Object.assign({ price: price, lineWidth: 1, lineStyle: 0, axisLabelVisible: true }, options);
    if (lc.lines[key]) lc.lines[key].applyOptions(opts);
    else lc.lines[key] = lc.series.createPriceLine(opts);
  }

  function applyLevels(lc) {
    var s = spec(lc.el);
    if (!s) return;
    var green = css("--green", "#33d69f"), red = css("--red", "#f2685c"), accent = css("--accent", "#17e5d6");
    var bg = css("--panel", "#131a1b");
    setLine(lc, "take", s.take, { color: green, title: "Doel", axisLabelTextColor: bg });
    setLine(lc, "stop", s.stop, { color: red, title: "Stop", axisLabelTextColor: bg });
    var open = s.entry !== null && s.entry !== undefined;
    setLine(lc, "limit", open ? null : s.limit, { color: accent, title: "Limiet", axisLabelTextColor: bg });
    setLine(lc, "entry", open ? s.entry : null, { color: accent, title: "Entry", axisLabelTextColor: bg });
    setLine(lc, "now", s.price, { color: css("--text-dim", "#b7c4c2"), lineStyle: 2, title: "Nu", axisLabelTextColor: bg });
    lc.el.setAttribute("aria-label", s.label || "");
    lc.band.applyOptions({ baseValue: { type: "price", price: s.zone_low != null ? s.zone_low : 0 } });
  }

  // De zone als vlak tussen zone_low en zone_high. Is hij te dun om te zien (minder dan ZONE_MIN_PX hoog), dan toont de limietlijn alleen.
  function syncBand(lc) {
    var s = spec(lc.el);
    var show = false;
    if (s && s.zone_low != null && s.zone_high != null && lc.candles.length) {
      var a = lc.series.priceToCoordinate(s.zone_low), b = lc.series.priceToCoordinate(s.zone_high);
      show = a !== null && b !== null && Math.abs(a - b) >= 6;
    }
    lc.band.setData(show ? lc.candles.map(function (c) { return { time: c.time, value: s.zone_high }; }) : []);
  }

  function overlayPrice(lc) {
    var s = spec(lc.el);
    if (!s || s.price == null || !lc.candles.length) return;
    var last = lc.candles[lc.candles.length - 1];
    last.close = s.price;
    last.high = Math.max(last.high, s.price);
    last.low = Math.min(last.low, s.price);
    lc.series.update(last);
  }

  function load(lc) {
    var el = lc.el;
    return fetchCandles(el.getAttribute("data-coin"), el.getAttribute("data-tf") || "15m").then(function (candles) {
      if (lc.dead) return;
      lc.candles = candles.map(function (c) { return Object.assign({}, c); });   // kopie: overlayPrice past de laatste aan
      lc.series.setData(lc.candles);
      overlayPrice(lc);
      lc.chart.timeScale().fitContent();
      syncBand(lc);
    });
  }

  function create(el, temp) {
    var s = spec(el);
    if (!s || el._lc) return el._lc ? el._lc.ready : Promise.resolve();
    el.classList.remove("is-failed");
    var panel = css("--panel", "#131a1b"), green = css("--green", "#33d69f"), red = css("--red", "#f2685c");
    var chart = LC.createChart(el, {
      autoSize: true,
      layout: { background: { type: "solid", color: panel }, textColor: css("--muted", "#7d8c8a"), fontSize: 10, fontFamily: css("--mono", "monospace").replace(/"/g, "") },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 12, fixLeftEdge: true, tickMarkFormatter: tickLabel },
      crosshair: { vertLine: { visible: false, labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
      handleScroll: false, handleScale: false,
    });
    var lc = { el: el, chart: chart, lines: {}, candles: [], dead: false };
    // De zone eerst: een baselineserie met als grondlijn zone_low en overal zone_high als waarde vult precies het vlak ertussen.
    lc.band = chart.addBaselineSeries({
      baseValue: { type: "price", price: s.zone_low != null ? s.zone_low : 0 },
      topLineColor: "rgba(0,0,0,0)", topFillColor1: "rgba(23,229,214,0.16)", topFillColor2: "rgba(23,229,214,0.16)",
      bottomLineColor: "rgba(0,0,0,0)", bottomFillColor1: "rgba(0,0,0,0)", bottomFillColor2: "rgba(0,0,0,0)",
      lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      autoscaleInfoProvider: function () { return null; },
    });
    lc.series = chart.addCandlestickSeries({
      upColor: green, downColor: red, borderVisible: false, wickUpColor: green, wickDownColor: red,
      priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: "price", precision: precision(s), minMove: Math.pow(10, -precision(s)) },
      // Stop, limiet en doel horen er altijd op, naast de candles: de schaal is de unie van beide.
      autoscaleInfoProvider: function (original) {
        var r = original(), cur = spec(el);
        var lv = cur ? levels(cur) : [];
        if (!lv.length) return r;
        var lo = Math.min.apply(null, lv), hi = Math.max.apply(null, lv);
        if (r && r.priceRange) { lo = Math.min(lo, r.priceRange.minValue); hi = Math.max(hi, r.priceRange.maxValue); }
        return { priceRange: { minValue: lo, maxValue: hi }, margins: r ? r.margins : undefined };
      },
    });
    el._lc = lc;
    if (!temp) live.add(el);
    applyLevels(lc);
    lc.ready = load(lc).catch(function () {
      if (lc.dead) return;
      destroy(el);
      el.classList.add("is-failed");
      if (!temp) wanted.add(el);
    });
    return lc.ready;
  }

  function destroy(el) {
    var lc = el._lc;
    if (!lc) return;
    lc.dead = true;
    try { lc.chart.remove(); } catch (e) { /* al weg */ }
    el._lc = null;
    live.delete(el);
    el.innerHTML = "";
  }

  function fill() {
    wanted.forEach(function (el) {
      if (live.size >= MAX_LIVE) return;
      wanted.delete(el);
      create(el, false);
    });
  }

  function want(el) {
    if (el._lc) return;
    if (live.size < MAX_LIVE) create(el, false); else wanted.add(el);
  }

  function onIntersect(entries) {
    entries.forEach(function (entry) {
      var el = entry.target;
      if (entry.isIntersecting) { want(el); return; }
      wanted.delete(el);
      el.classList.remove("is-failed");
      destroy(el);
    });
    fill();
  }

  api.update = function (el, next) {
    if (!next) return;
    el._spec = next;
    var lc = el._lc;
    if (!lc) { el.setAttribute("aria-label", next.label || ""); return; }
    applyLevels(lc);
    overlayPrice(lc);
    lc.chart.priceScale("right").applyOptions({ autoScale: true });     // de schaal opnieuw bepalen met de nieuwe niveaus
    syncBand(lc);
  };

  // Voor de deelafbeelding (share.js): het canvas van de grafiek zoals hij er nu staat. Staat hij nog niet (kaart ver weg), dan
  // wordt hij even gemaakt en daarna weer weggehaald.
  api.screenshot = function (el) {
    var temp = !el._lc;
    var ready = temp ? create(el, true) : el._lc.ready;
    return ready.then(function () {
      var lc = el._lc;
      if (!lc) return null;
      var canvas = lc.chart.takeScreenshot();
      if (temp) destroy(el);
      return canvas;
    }).catch(function () { return null; });
  };

  setInterval(function () {
    if (document.hidden) return;
    live.forEach(function (el) { if (el._lc) load(el._lc).catch(function () { /* laatste stand blijft staan */ }); });
    fill();
  }, REFRESH_MS);

  var observer = "IntersectionObserver" in window ? new IntersectionObserver(onIntersect, { rootMargin: "300px 0px" }) : null;
  els.forEach(function (el) { if (observer) observer.observe(el); else want(el); });
})();
