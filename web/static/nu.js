// Nu leeft alleen waar de markt beweegt: koers, afstand tot de limiet, de balk en de live R. De keuze tussen rust en een kaart maakt de
// server (app/nu.py); verandert wat er in de zone staat of welke trades open zijn, dan laadt de pagina opnieuw in plaats van hier een
// tweede versie van die keuze te bouwen. Bron: /api/radar elke 15 seconden, tussendoor de koersstroom van live.js als die vers is.
(function () {
  var root = document.querySelector("[data-nu-mode]");
  if (!root) return;
  var sig = root.getAttribute("data-nu-sig") || "|";
  var skip = (root.getAttribute("data-nu-skip") || "").split(",").filter(Boolean);
  var cards = [].slice.call(root.querySelectorAll("[data-nu-key]"));
  var reloading = false;

  // Zelfde cijfers als chance_steps.fmt, met een komma zoals nu.nl.
  function nl(v) {
    if (Math.abs(v) < 1) {
      if (v === 0) return "0";
      var d = 4 - Math.floor(Math.log10(Math.abs(v)));
      return v.toFixed(d).replace(/0+$/, "").replace(/\.$/, "").replace(".", ",");
    }
    return (Math.abs(v) < 100 ? v.toFixed(4) : v.toFixed(2)).replace(".", ",");
  }
  function pct(v) { return v.toFixed(2).replace(".", ",") + "%"; }
  function rText(v) { return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2).replace(".", ",") + " R"; }
  // trade_plan.distance_to_limit_pct en approach_pct (schaal 3%).
  function distance(dir, limit, p) { return dir === "long" ? (p - limit) / limit * 100 : (limit - p) / limit * 100; }
  function approach(d) { return d <= 0 ? 100 : Math.max(0, 100 - d / 3 * 100); }

  function set(card, name, text) {
    var el = card.querySelector('[data-nu="' + name + '"]');
    if (el && el.textContent !== text) el.textContent = text;
    return el;
  }

  function show(card, price) {
    if (!price) return;
    set(card, "price", nl(price));
    var limit = parseFloat(card.getAttribute("data-nu-limit")), dir = card.getAttribute("data-nu-dir");
    if (!isNaN(limit) && card.querySelector('[data-nu="distance"]')) {
      var d = distance(dir, limit, price);
      if (d > 0) {
        set(card, "distance", pct(d));
        var bar = card.querySelector('[data-nu="bar"]');
        if (bar) bar.style.width = approach(d).toFixed(1) + "%";
      }
    }
    var entry = parseFloat(card.getAttribute("data-nu-entry")), stop = parseFloat(card.getAttribute("data-nu-stop"));
    if (!isNaN(entry) && !isNaN(stop) && entry !== stop) {
      var r = (dir === "long" ? price - entry : entry - price) / Math.abs(entry - stop);
      var el = set(card, "live_r", rText(r));
      if (el) el.className = "nu-r " + (r > 0 ? "pos" : r < 0 ? "neg" : "");
    }
  }

  function signature(payload) {
    var zone = [], trades = [];
    Object.keys(payload).forEach(function (k) {
      if (k.indexOf("signal:") === 0) trades.push(k);
      else if (payload[k].state === "in_zone" && skip.indexOf(k) === -1) zone.push(k);
    });
    return zone.sort().join(",") + "|" + trades.sort().join(",");
  }

  function apply(payload) {
    if (signature(payload) !== sig) {
      if (!reloading) { reloading = true; location.reload(); }
      return;
    }
    cards.forEach(function (card) {
      var d = payload[card.getAttribute("data-nu-key")];
      if (d) show(card, d.price);
    });
  }

  function refresh() {
    if (document.hidden || reloading) return;
    fetch("/api/radar", { cache: "no-store", credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return null;
        var age = r.headers.get("X-Price-Age");
        if (age !== null && window.hesPriceSeen) window.hesPriceSeen(age);
        if (age !== null) {
          var a = parseInt(age, 10), seen = root.querySelector('[data-nu="seen"]');
          if (seen && !isNaN(a)) seen.textContent = a < 60 ? "net" : a < 3600 ? Math.floor(a / 60) + " min" : Math.floor(a / 3600) + " u";
        }
        return r.json();
      })
      .then(function (payload) { if (payload) apply(payload); })
      .catch(function () { /* een mislukte verversing laat de laatste stand staan */ });
  }

  // De koersstroom (live.js) is sneller dan de poll; alleen gebruiken zolang hij vers is.
  setInterval(function () {
    if (document.hidden || !(window.hesLiveFresh && window.hesLiveFresh()) || !window.__livePrices) return;
    cards.forEach(function (card) { show(card, window.__livePrices[card.getAttribute("data-nu-coin")]); });
  }, 1000);

  setInterval(refresh, 15000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
