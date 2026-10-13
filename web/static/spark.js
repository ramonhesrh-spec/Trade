// Minigrafiek per kaart: de koers van de laatste 24 uur (1u-candles). Eén aanroep voor alle coins op de pagina, elke 5 minuten opnieuw.
// De server rekent het pad uit (radar.spark), hier wordt het alleen ingevuld.
(function () {
  var svgs = document.querySelectorAll("[data-spark-coin]");
  var chgs = document.querySelectorAll("[data-spark-chg]");
  if (!svgs.length && !chgs.length) return;   // een markt-rij heeft alleen de verandering, geen minigrafiek
  var coins = {};
  svgs.forEach(function (s) { coins[s.getAttribute("data-spark-coin")] = 1; });
  chgs.forEach(function (s) { coins[s.getAttribute("data-spark-chg")] = 1; });

  function apply(data) {
    svgs.forEach(function (svg) {
      var d = data[svg.getAttribute("data-spark-coin")], path = svg.querySelector("path");
      if (!d || !path) return;
      path.setAttribute("d", d.path);
      svg.classList.toggle("is-up", d.change_pct > 0);   // change_pct is al op één decimaal afgerond: 0 is neutraal
      svg.classList.toggle("is-down", d.change_pct < 0);
      svg.classList.add("has-data");
    });
    chgs.forEach(function (el) {
      var d = data[el.getAttribute("data-spark-chg")];
      if (!d) return;
      el.classList.toggle("is-up", d.change_pct > 0);
      el.classList.toggle("is-down", d.change_pct < 0);
      el.textContent = el.hasAttribute("data-spark-short") ? d.change_text.replace(" 24u", "") : d.change_text;
    });
  }

  function load() {
    if (document.hidden) return;
    fetch("/api/sparklines?coins=" + encodeURIComponent(Object.keys(coins).join(",")), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) apply(d); })
      .catch(function () { /* geen minigrafiek is beter dan een foute */ });
  }

  load();
  setInterval(load, 300000);
})();
