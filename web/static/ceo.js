// Twee dingen voor de CEO. (1) Op de CEO-pagina regent geld, maar alleen als het resultaat van de week positief is: meer resultaat, meer biljetten.
// (2) Tik vijf keer op het logo en het regent confetti met "Bonus geboekt". Beide gebeuren op een echte aanleiding, niet om te versieren.
(function () {
  var mc = document.getElementById("masterclass");
  if (mc) mc.addEventListener("click", function () {
    if (window.ceoShower) window.ceoShower(48, ["💸", "💰", "🍾", "🛥️"]);
    var t = document.createElement("div");
    t.className = "ceo-toast";
    t.textContent = "Je staat op de wachtlijst, leerling";
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2800);
  });

  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  function shower(n, glyphs) {
    var layer = document.createElement("div");
    layer.className = "money-layer";
    layer.setAttribute("aria-hidden", "true");
    for (var i = 0; i < n; i++) {
      var s = document.createElement("span");
      s.textContent = glyphs[i % glyphs.length];
      s.style.left = Math.round(Math.random() * 100) + "%";
      s.style.animationDelay = (Math.random() * 1.2).toFixed(2) + "s";
      s.style.animationDuration = (2.4 + Math.random() * 1.8).toFixed(2) + "s";
      s.style.fontSize = (18 + Math.round(Math.random() * 16)) + "px";
      layer.appendChild(s);
    }
    document.body.appendChild(layer);
    setTimeout(function () { layer.remove(); }, 6000);
  }

  window.ceoShower = shower;
  var page = document.querySelector(".ceo-page");
  if (page) {
    var rain = parseInt(page.getAttribute("data-rain") || "0", 10);
    if (rain > 0) shower(rain, ["💸", "💶", "💰"]);
  }

  var logo = document.querySelector(".topbar .logo, .topbar a[href='/vandaag'], .topbar svg");
  var taps = [], toastTimer = null;
  if (logo) logo.addEventListener("click", function () {
    var now = Date.now();
    taps = taps.filter(function (t) { return now - t < 3000; }).concat(now);
    if (taps.length < 5) return;
    taps = [];
    shower(36, ["🎉", "💸", "🍾", "💰", "🛥️"]);
    var toast = document.createElement("div");
    toast.className = "ceo-toast";
    toast.textContent = "Bonus geboekt";
    document.body.appendChild(toast);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.remove(); }, 2600);
  });
})();
