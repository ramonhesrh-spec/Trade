/* Candlegrafiek met de niveaus van een plan, op elke radar-kaart en op Vandaag. Een element met data-levelchart (JSON uit
   trade_plan.chart_spec: stop, take, limit, zone_low, zone_high, entry, price, direction), data-coin en data-tf krijgt een
   echte grafiek van lightweight-charts (vendor/lightweight-charts-4.2.0.*). De server stuurt getallen, hier wordt getekend.
   - Lazy: de grafiek wordt pas gemaakt als de kaart bijna in beeld komt en weer weggehaald als hij ver weg scrolt; nooit meer
     dan MAX_LIVE tegelijk, zodat een lange pagina op een telefoon soepel blijft.
   - Geen gebaren: scrollen en zoomen staan uit, een veeg over de grafiek scrolt gewoon de pagina (iOS).
   - Live: update(el, spec) verschuift de laatste candle en de Nu-lijn; de grafiek wordt niet opnieuw gemaakt.
   - Rood vlak van instap (of limiet) tot stop, groen van instap tot doel (areas): de niveaus van het plan, geen schatting.
   - Candles komen van /api/radar_candles (een minuut gecachet op de server en hier per coin+tijdframe gedeeld).
   - Schermvullend: een tik op de grafiek of op "Groot" opent een dialoog (telt niet mee voor MAX_LIVE, weg bij sluiten) op het tijdframe waar
     het niveau vandaan komt (spec.zone.tf van de zone-radar, anders 1u), met een keuze 15m/1u/4u. Daar staan de zone en de doelzone als vlak
     vanaf de candle waar de zone ontstond, met een markering en de uitleg uit zone_radar.chart_zone eronder.
   De lightweight-charts-bibliotheek tekent zonder animatie, dus er is niets dat prefers-reduced-motion hoeft te dempen. */
(function () {
  var MAX_LIVE = 8;
  var CANDLE_LIMIT = 60;            // 60 candles: op een telefoon blijft elke candle zichtbaar breed genoeg
  var REFRESH_MS = 60000;
  var AREA_ALPHA = 0.07;            // risico- en winstvlak: zacht, de candles en zones moeten erdoor leesbaar blijven
  var FULL_TFS = ["15m", "1h", "4h"];
  var TF_TEXT = { "15m": "15m", "1h": "1u", "4h": "4u" };
  var TF_SEC = { "15m": 900, "1h": 3600, "4h": 14400 };
  // Genoeg historie om een zone te zien ontstaan; de server levert er hooguit 200 (RADAR_CANDLE_FETCH in web/main.py).
  var FULL_BASE = { "15m": 160, "1h": 120, "4h": 120 };
  var FULL_MAX = 200;
  var LINE_LABEL_ROOM = 96;         // css-px aan de rechterkant van de grafiek waar de titels van de prijslijnen staan
  var LC = window.LightweightCharts;
  var api = { update: function () {}, screenshot: function () { return Promise.resolve(null); } };
  window.hesLevelChart = api;
  api.areas = areas;
  api.rgba = rgba;
  api.candleLimit = candleLimit;
  api.originBar = originBar;
  api.fullTf = fullTf;
  api.fullNote = fullNote;
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
    return ref >= 100 ? 2 : ref >= 0.1 ? 4 : 6;
  }

  // Risico en beloning van het plan zelf: van instap (of limiet) tot stop, en van instap tot doel. Geen schatting, alleen de niveaus.
  function num(v) { return typeof v === "number" && isFinite(v); }

  function areas(s) {
    var base = typeof s.entry === "number" && isFinite(s.entry) ? s.entry : s.limit;
    if (typeof base !== "number" || !isFinite(base)) return [];
    var out = [], hasStop = num(s.stop), hasTake = num(s.take);
    // Een stop of doel aan de verkeerde kant van de instap zou een vlak tekenen dat het plan tegenspreekt (bijvoorbeeld bij een verouderd of omgekeerd plan): dan liever geen vlak.
    var opposite = hasStop && hasTake && (s.stop - base) * (s.take - base) < 0;
    var lossSide = s.direction === "long" ? s.stop < base : s.direction === "short" ? s.stop > base : true;
    var winSide = s.direction === "long" ? s.take > base : s.direction === "short" ? s.take < base : true;
    if (hasStop && s.stop !== base && lossSide && (!hasTake || opposite)) out.push({ key: "risk", base: base, value: s.stop });
    if (hasTake && s.take !== base && winSide && (!hasStop || opposite)) out.push({ key: "reward", base: base, value: s.take });
    return out;
  }

  // Hoeveel candles de schermvullende grafiek vraagt: de basis per tijdframe, of meer als de zone ouder is, zodat de candle waar hij ontstond
  // er nog op staat (plus een marge links); nooit meer dan de server levert.
  function candleLimit(tf, origin, nowSec) {
    var base = FULL_BASE[tf] || CANDLE_LIMIT, step = TF_SEC[tf];
    if (!num(origin) || !step) return base;
    return Math.min(FULL_MAX, Math.max(base, Math.ceil((nowSec - origin) / step) + 12));
  }

  // De candle (openmoment) waarin het ontstaansmoment valt, of null als het voor de eerste candle ligt of er geen candles zijn.
  function originBar(times, origin, tf) {
    if (!num(origin) || !times.length || origin < times[0]) return null;
    var hit = null;
    for (var i = 0; i < times.length && times[i] <= origin; i++) hit = times[i];
    if (hit !== null && TF_SEC[tf] && origin >= hit + TF_SEC[tf]) return null;      // na de laatste candle: niet op deze grafiek
    return hit;
  }

  function fullTf(s) {
    return s && s.zone && TF_SEC[s.zone.tf] ? s.zone.tf : "1h";
  }

  // Welke uitleg onder de grafiek staat: alleen als de herkomst van de zone bekend is, en eerlijk over waar de markering staat.
  function fullNote(s, tf, bar) {
    var z = s && s.zone;
    if (!z || !num(z.origin)) return "";
    if (bar === null) return z.note_outside || "";
    return tf === z.tf ? (z.note || "") : (z.note_other_tf || "");
  }

  // De themakleur kan een ander formaat zijn dan 6-cijferige hex (rgb(), hsl(), leeg); de aanroeper geeft dan een vaste rgba mee in plaats van dat de invoer ongewijzigd terugkomt, want dat zou een dekkend vlak over de candles leggen.
  function rgba(hex, a, fallback) {
    var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex).trim());
    return m ? "rgba(" + parseInt(m[1], 16) + "," + parseInt(m[2], 16) + "," + parseInt(m[3], 16) + "," + a + ")" : (fallback || "transparent");
  }

  // Een baselineserie met een prijsgrondlijn blijft aan de prijzen vastzitten als de schaal verschuift of de grafiek van maat wisselt.
  function areaSeries(chart, color, fallback, priceFormat) {
    var fill = rgba(color, AREA_ALPHA, fallback), none = "rgba(0,0,0,0)";
    return chart.addBaselineSeries({
      baseValue: { type: "price", price: 0 },
      topLineColor: none, bottomLineColor: none,
      topFillColor1: fill, topFillColor2: fill, bottomFillColor1: fill, bottomFillColor2: fill,
      lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: priceFormat,
      autoscaleInfoProvider: function () { return null; },
    });
  }

  function syncAreas(lc) {
    var s = spec(lc.el), wanted = {};
    (s ? areas(s) : []).forEach(function (a) { wanted[a.key] = a; });
    ["risk", "reward"].forEach(function (k) {
      var a = wanted[k], series = lc.areas[k];
      if (!a || !lc.candles.length) { series.setData([]); return; }
      series.applyOptions({ baseValue: { type: "price", price: a.base } });
      series.setData(lc.candles.map(function (c) { return { time: c.time, value: a.value }; }));
    });
  }

  function fetchCandles(coin, tf, limit) {
    var key = coin + "|" + tf + "|" + limit, hit = memo[key];
    if (hit && Date.now() - hit.at < REFRESH_MS - 2000) return hit.promise;
    var promise = fetch("/api/radar_candles/" + encodeURIComponent(coin) + "?tf=" + encodeURIComponent(tf) + "&limit=" + limit, { credentials: "same-origin" })
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
    var green = css("--green", "#33d69f"), red = css("--red", "#f2685c"), accent = css("--accent", "#0ABAB5");
    var bg = css("--panel", "#131a1b");
    setLine(lc, "take", s.take, { color: green, title: "Doel", axisLabelTextColor: bg });
    setLine(lc, "stop", s.stop, { color: red, title: "Stop", axisLabelTextColor: bg });
    var open = s.entry !== null && s.entry !== undefined;
    // Gewone woorden op de lijnen: je limietorder en je gevulde entry zijn allebei "Instap".
    setLine(lc, "limit", open ? null : s.limit, { color: accent, title: "Instap", axisLabelTextColor: bg });
    setLine(lc, "entry", open ? s.entry : null, { color: accent, title: "Instap", axisLabelTextColor: bg });
    setLine(lc, "now", s.price, { color: css("--text-dim", "#b7c4c2"), lineStyle: 2, title: "Koers nu", axisLabelTextColor: bg });
    lc.el.setAttribute("aria-label", s.label || "");
    lc.band.applyOptions({ baseValue: { type: "price", price: s.zone_low != null ? s.zone_low : 0 } });
    if (lc.full) syncZones(lc);
  }

  // Schermvullend: de zone en de doelzone als vlak met een dunne rand, getekend als primitive op de candleserie zodat ze aan prijs en tijd vastzitten
  // en tot de rechterrand doorlopen (een serie stopt bij de laatste candle). De zone begint bij de candle waar hij ontstond als die op de grafiek staat.
  function syncZones(lc) {
    var s = spec(lc.el), z = s && s.zone, boxes = [];
    var accent = css("--accent", "#0ABAB5"), green = css("--green", "#33d69f"), plate = rgba(css("--panel", "#131a1b"), 0.85, "rgba(19,26,27,0.85)");
    var times = lc.candles.map(function (c) { return c.time; });
    lc.originBar = z ? originBar(times, z.origin, lc.tf) : null;
    if (z && num(s.zone_low) && num(s.zone_high)) {
      boxes.push({ low: s.zone_low, high: s.zone_high, time: lc.originBar, label: z.label, text: accent, plate: plate,
                   fill: rgba(accent, 0.12, "rgba(10,186,181,0.12)"), edge: rgba(accent, 0.6, "rgba(10,186,181,0.6)") });
    }
    if (z && num(z.target_low) && num(z.target_high)) {
      boxes.push({ low: z.target_low, high: z.target_high, time: null, label: z.target_label, text: green, plate: plate,
                   fill: rgba(green, 0.07, "rgba(51,214,159,0.07)"), edge: rgba(green, 0.45, "rgba(51,214,159,0.45)") });
    }
    lc.boxes = boxes;
    var marks = [];
    if (z && lc.originBar !== null) {
      var bull = z.kind === "bull";
      marks.push({ time: lc.originBar, position: bull ? "belowBar" : "aboveBar", shape: bull ? "arrowUp" : "arrowDown", color: accent, text: "Zone" });
    }
    lc.series.setMarkers(marks);
    if (lc.onNote && lc.candles.length) lc.onNote(fullNote(s, lc.tf, lc.originBar));
    if (lc.redraw) lc.redraw();
  }

  function zonePrimitive(lc) {
    var font = css("--mono", "monospace").replace(/"/g, "");
    // Twee lagen: de vlakken onder de candles, de labels erboven (anders lopen candles door de tekst).
    function draw(target, labels) {
      var boxes = lc.boxes || [];
      if (!boxes.length) return;
      target.useBitmapCoordinateSpace(function (scope) {
        var ctx = scope.context, hr = scope.horizontalPixelRatio, vr = scope.verticalPixelRatio, W = scope.bitmapSize.width;
        var ts = lc.chart.timeScale(), half = (ts.options().barSpacing || 6) / 2;
        boxes.forEach(function (b) {
          var y1 = lc.series.priceToCoordinate(b.high), y2 = lc.series.priceToCoordinate(b.low);
          if (y1 === null || y2 === null) return;
          var x = b.time !== null ? ts.timeToCoordinate(b.time) : null;
          var left = x === null ? 0 : Math.max(0, Math.round((x - half) * hr));
          var top = Math.round(Math.min(y1, y2) * vr), h = Math.max(Math.round(Math.abs(y2 - y1) * vr), Math.round(2 * vr));
          var line = Math.max(1, Math.round(hr));
          if (labels) { drawLabel(ctx, b, left, top, h, W, hr, vr); return; }
          ctx.fillStyle = b.fill;
          ctx.fillRect(left, top, W - left, h);
          ctx.fillStyle = b.edge;
          ctx.fillRect(left, top, W - left, line);
          ctx.fillRect(left, top + h - line, W - left, line);
          if (x !== null) ctx.fillRect(left, top, line, h);
        });
      });
    }
    function drawLabel(ctx, b, left, top, h, W, hr, vr) {
      if (!b.label) return;
      ctx.font = "500 " + Math.round(11 * vr) + "px " + font;
      // Rechts staan de labels van Instap, Stop en Doel; begint het vlak daar te dichtbij, dan komt het label links van zijn begin.
      var tw = ctx.measureText(b.label).width, gap = Math.round(6 * hr), lx = left + gap;
      if (lx + tw > W - Math.round(LINE_LABEL_ROOM * hr)) lx = left - gap - tw >= 0 ? left - gap - tw : Math.min(lx, W - tw - gap);
      // Past het label niet in het vlak, dan erboven; zo blijft het los van de candles in de zone.
      var inside = h >= Math.round(20 * vr), lh = Math.round(15 * vr), pad = Math.round(4 * hr);
      var ly = inside ? top + Math.round(3 * vr) : top - lh - Math.round(2 * vr);
      lx = Math.max(0, lx);
      // Een vlak in de achtergrondkleur achter het label: zo blijft het leesbaar boven candles die door de zone lopen.
      ctx.fillStyle = b.plate;
      ctx.fillRect(lx - pad, ly, tw + 2 * pad, lh);
      ctx.fillStyle = b.text;
      ctx.textBaseline = "middle";
      ctx.fillText(b.label, lx, ly + lh / 2);
    }
    var below = { zOrder: function () { return "bottom"; }, renderer: function () { return { draw: function (t) { draw(t, false); } }; } };
    var above = { zOrder: function () { return "top"; }, renderer: function () { return { draw: function (t) { draw(t, true); } }; } };
    return {
      paneViews: function () { return [below, above]; },
      updateAllViews: function () {},
      attached: function (p) { lc.redraw = p.requestUpdate; },
      detached: function () { lc.redraw = null; },
    };
  }

  // De zone als vlak tussen zone_low en zone_high. Is hij te dun om te zien (minder dan ZONE_MIN_PX hoog), dan toont de limietlijn alleen.
  function syncBand(lc) {
    var s = spec(lc.el);
    var show = false;
    // Schermvullend met een zone-radar-zone tekent syncZones het vlak, met rand en vanaf zijn ontstaan.
    if (s && !(lc.full && s.zone) && s.zone_low != null && s.zone_high != null && lc.candles.length) {
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
    var tf = el.getAttribute("data-tf") || "15m", s = spec(el);
    var limit = lc.full ? candleLimit(tf, s && s.zone ? s.zone.origin : null, Date.now() / 1000) : CANDLE_LIMIT;
    return fetchCandles(el.getAttribute("data-coin"), tf, limit).then(function (candles) {
      if (lc.dead) return;
      lc.candles = candles.map(function (c) { return Object.assign({}, c); });   // kopie: overlayPrice past de laatste aan
      lc.series.setData(lc.candles);
      overlayPrice(lc);
      lc.chart.timeScale().fitContent();
      syncBand(lc);
      syncAreas(lc);
      if (lc.full) syncZones(lc);
    });
  }

  function create(el, temp, full) {
    var s = spec(el);
    if (!s || el._lc) return el._lc ? el._lc.ready : Promise.resolve();
    el.classList.remove("is-failed");
    var panel = css("--panel", "#131a1b"), green = css("--green", "#33d69f"), red = css("--red", "#f2685c");
    var up = css("--candle-up", "#0ABAB5"), down = css("--candle-down", "#f4f8f7");
    var chart = LC.createChart(el, {
      autoSize: true,
      layout: { background: { type: "solid", color: panel }, textColor: css("--text-dim", "#b7c4c2"), fontSize: 12, fontFamily: css("--mono", "monospace").replace(/"/g, "") },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: full ? 8 : 12, fixLeftEdge: true, tickMarkFormatter: tickLabel },
      crosshair: { vertLine: { visible: false, labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
      handleScroll: false, handleScale: false,
    });
    var lc = { el: el, chart: chart, lines: {}, candles: [], dead: false, areas: {}, full: !!full, tf: el.getAttribute("data-tf") || "15m",
               boxes: [], originBar: null, onNote: full ? full.onNote : null };
    // Eerst toegevoegd, dus onderop: zone en candles blijven er leesbaar overheen.
    // Elke serie op de schaal krijgt het prijsformaat van de candles: de schaal neemt het formaat van de eerst toegevoegde serie, en met de
    // standaard van twee decimalen stond een instap van 0,162 als "0.16" op de as.
    var pf = { type: "price", precision: precision(s), minMove: Math.pow(10, -precision(s)) };
    lc.areas.risk = areaSeries(chart, red, "rgba(242,104,92,0.07)", pf);
    lc.areas.reward = areaSeries(chart, green, "rgba(51,214,159,0.07)", pf);
    // De zone eerst: een baselineserie met als grondlijn zone_low en overal zone_high als waarde vult precies het vlak ertussen.
    lc.band = chart.addBaselineSeries({
      baseValue: { type: "price", price: s.zone_low != null ? s.zone_low : 0 },
      topLineColor: "rgba(0,0,0,0)", topFillColor1: "rgba(10,186,181,0.16)", topFillColor2: "rgba(10,186,181,0.16)",
      bottomLineColor: "rgba(0,0,0,0)", bottomFillColor1: "rgba(0,0,0,0)", bottomFillColor2: "rgba(0,0,0,0)",
      lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: pf,
      autoscaleInfoProvider: function () { return null; },
    });
    lc.series = chart.addCandlestickSeries({
      upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down,
      priceLineVisible: false, lastValueVisible: false,
      priceFormat: pf,
      // Stop, limiet en doel horen er altijd op, naast de candles: de schaal is de unie van beide.
      autoscaleInfoProvider: function (original) {
        var r = original(), cur = spec(el);
        var lv = cur ? levels(cur) : [];
        // Schermvullend horen de hele zone en doelzone in beeld, anders valt een rand van het vlak buiten de grafiek.
        if (full && cur && cur.zone) lv = lv.concat([cur.zone.target_low, cur.zone.target_high].filter(num));
        if (!lv.length) return r;
        var lo = Math.min.apply(null, lv), hi = Math.max.apply(null, lv);
        if (r && r.priceRange) { lo = Math.min(lo, r.priceRange.minValue); hi = Math.max(hi, r.priceRange.maxValue); }
        return { priceRange: { minValue: lo, maxValue: hi }, margins: r ? r.margins : undefined };
      },
    });
    if (full) lc.series.attachPrimitive(zonePrimitive(lc));
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

  function update(el, next) {
    el._spec = next;
    var lc = el._lc;
    if (!lc) { el.setAttribute("aria-label", next.label || ""); return; }
    applyLevels(lc);
    overlayPrice(lc);
    lc.chart.priceScale("right").applyOptions({ autoScale: true });     // de schaal opnieuw bepalen met de nieuwe niveaus
    syncBand(lc);
    syncAreas(lc);
  }

  api.update = function (el, next) {
    if (!next) return;
    update(el, next);
    if (full && full.src === el) update(full.el, next);
  };

  // Schermvullend: een eigen element met dezelfde gegevens, tijdelijk gemaakt (niet in `live`) en bij sluiten weer weggehaald. Een ander tijdframe
  // kiezen maakt de grafiek opnieuw op dat tijdframe; de niveaus blijven dezelfde.
  var full = null;

  function node(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function legendItem(cls, text) {
    var item = node("span", "lc-key " + cls);
    item.textContent = text;
    return item;
  }

  function openFull(src) {
    if (full || !spec(src)) return;
    var s = spec(src), coin = src.getAttribute("data-coin"), dlg = node("dialog", "lc-full");
    dlg.setAttribute("aria-label", "Grafiek " + coin);
    var head = node("div", "lc-full-head");
    var title = node("p", "lc-full-title", coin + " ");
    if (s.direction) title.appendChild(node("span", "lc-full-dir", s.direction === "long" ? "Long" : "Short"));
    var seg = node("div", "lc-seg");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Tijdframe van de candles");
    var close = node("button", "lc-full-close");
    close.type = "button";
    close.setAttribute("aria-label", "Grafiek sluiten");
    close.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>';
    head.appendChild(title);
    head.appendChild(seg);
    head.appendChild(close);
    var el = node("div", "level-chart");
    ["data-coin", "role", "aria-label"].forEach(function (a) { if (src.hasAttribute(a)) el.setAttribute(a, src.getAttribute(a)); });
    el._spec = s;
    var foot = node("div", "lc-full-foot");
    var note = node("p", "lc-full-note");
    note.setAttribute("aria-live", "polite");
    var legend = node("p", "lc-full-legend");
    if (s.zone) {
      legend.appendChild(legendItem("is-zone", s.zone.label));
      if (s.zone.target_label) legend.appendChild(legendItem("is-target", s.zone.target_label));
    } else if (num(s.zone_low) && num(s.zone_high)) {
      legend.appendChild(legendItem("is-zone", "Zone"));
    }
    legend.appendChild(legendItem("is-risk", "Risico"));
    legend.appendChild(legendItem("is-reward", "Winst"));
    foot.appendChild(note);
    foot.appendChild(legend);
    dlg.appendChild(head);
    dlg.appendChild(el);
    dlg.appendChild(foot);
    document.body.appendChild(dlg);
    full = { dlg: dlg, el: el, src: src };
    var opts = { onNote: function (text) { note.textContent = text; note.hidden = !text; } };
    note.hidden = true;

    function show(tf) {
      destroy(el);
      el.setAttribute("data-tf", tf);
      Array.prototype.forEach.call(seg.children, function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-tf") === tf)); });
      create(el, true, opts);
    }
    FULL_TFS.forEach(function (tf) {
      var b = node("button", "lc-seg-btn", TF_TEXT[tf]);
      b.type = "button";
      b.setAttribute("data-tf", tf);
      b.setAttribute("aria-label", "Candles van " + { "15m": "15 minuten", "1h": "1 uur", "4h": "4 uur" }[tf]);
      b.addEventListener("click", function () { if (b.getAttribute("aria-pressed") !== "true") show(tf); });
      seg.appendChild(b);
    });

    document.documentElement.classList.add("lc-lock");
    close.addEventListener("click", function () { if (dlg.close) dlg.close(); else done(); });
    function done() {
      destroy(el);
      dlg.remove();
      full = null;
      document.documentElement.classList.remove("lc-lock");
      var back = src.closest(".lc") && src.closest(".lc").querySelector("[data-lc-expand]");
      if (back) back.focus();
    }
    dlg.addEventListener("close", done);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    show(fullTf(s));
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-lc-expand], .lc .level-chart");
    if (!t) return;
    var src = t.matches("[data-lc-expand]") ? t.closest(".lc").querySelector("[data-levelchart]") : t;
    if (src) openFull(src);
  });

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
