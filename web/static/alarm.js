// Prijsalarm vanaf een kaart: een tik op de bel naast een niveau zet een alarm, nog een tik haalt het weg. De controle draait op de server
// (app/level_check.py, elke 15 minuten), dus de melding komt ook als de app dicht is.
(function () {
  var groups = document.querySelectorAll("[data-chips-coin]");
  if (!groups.length) return;
  var byKey = {};

  function key(coin, price) { return coin + "|" + Number(price).toPrecision(10); }
  function toast(text) { if (window.hesToast) window.hesToast(text); }

  function mark() {
    groups.forEach(function (g) {
      var coin = g.getAttribute("data-chips-coin");
      g.querySelectorAll(".level-bell").forEach(function (b) {
        var on = !!byKey[key(coin, b.getAttribute("data-alarm-price"))];
        b.setAttribute("aria-pressed", on ? "true" : "false");
        b.classList.toggle("is-on", on);
      });
    });
  }

  fetch("/api/prijsalarm", { credentials: "same-origin", cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      d.alerts.forEach(function (a) { byKey[key(a.coin, a.price)] = a.id; });
      mark();
    })
    .catch(function () {});

  function create(b, g, k) {
    return fetch("/api/prijsalarm", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coin: g.getAttribute("data-chips-coin"), price: Number(b.getAttribute("data-alarm-price")),
                             label: b.getAttribute("data-alarm-label"), url: g.getAttribute("data-chips-url") }),
    }).then(function (r) {
      return r.json().then(function (d) {
        if (r.ok) { byKey[k] = d.id; toast(d.message); } else { toast(d.error || "Alarm zetten lukte niet"); }
      });
    });
  }

  function remove(k) {
    return fetch("/api/prijsalarm/" + byKey[k], { method: "DELETE", credentials: "same-origin" }).then(function (r) {
      if (r.ok || r.status === 404) { delete byKey[k]; toast("Alarm weg"); }
    });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".level-bell");
    if (!b) return;
    var g = b.closest("[data-chips-coin]"), k = key(g.getAttribute("data-chips-coin"), b.getAttribute("data-alarm-price"));
    b.disabled = true;
    (byKey[k] ? remove(k) : create(b, g, k))
      .catch(function () { toast("Geen verbinding"); })
      .then(function () { b.disabled = false; mark(); });
  });
})();
