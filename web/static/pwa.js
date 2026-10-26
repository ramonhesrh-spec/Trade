// De geïnstalleerde app: service worker, updatemelding, offline-balk, het wissen van bewaarde pagina's bij uitloggen en de themakleur.
(function () {
  var hasSW = "serviceWorker" in navigator;

  // Offline-balk. Twee gevallen: de browser meldt geen verbinding (navigator.onLine, niet waterdicht maar vangt vliegtuigmodus meteen), of de
  // service worker serveert de laatst bekende Radar of Vandaag (meta hp-offline-at). Die tweede blijft staan zolang je naar die oude pagina
  // kijkt. Meldt de browser wel verbinding, dan is de balk ook een knop om opnieuw te laden; "weer online" zeggen we niet, want de server kan
  // onbereikbaar zijn terwijl het toestel bereik heeft (zo kwam deze pagina juist uit de cache).
  var banner = document.getElementById("offline-banner");
  var savedMeta = document.querySelector('meta[name="hp-offline-at"]');
  function hhmm(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
  }
  if (banner && savedMeta) {
    var at = hhmm(savedMeta.getAttribute("content"));
    var offlineText = "Offline, laatst bijgewerkt om " + (at || "onbekend") + ".";
    banner.classList.add("is-saved");
    var showSaved = function () {
      banner.hidden = false;
      if (navigator.onLine) {
        banner.textContent = offlineText + " Tik om opnieuw te laden.";
        banner.setAttribute("role", "button");
        banner.tabIndex = 0;
      } else {
        banner.textContent = offlineText + " Koersen en kansen kunnen verouderd zijn.";
        banner.removeAttribute("role");
        banner.removeAttribute("tabindex");
      }
    };
    var reload = function () { if (navigator.onLine) location.reload(); };
    banner.addEventListener("click", reload);
    banner.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); reload(); } });
    window.addEventListener("online", showSaved);
    window.addEventListener("offline", showSaved);
    showSaved();
  } else if (banner) {
    var update = function () { banner.hidden = navigator.onLine; };
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    update();
  }

  // Bewaarde pagina's horen bij één kijker. Bij uitloggen, en op elke pagina zonder sessie (het inlogscherm), gaan ze weg.
  function clearSavedPages() {
    try {
      if (hasSW && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ type: "hp-logout" });
      if (window.caches) caches.keys().then(function (keys) {
        keys.forEach(function (k) { if (k.indexOf("hespulse-pages") === 0) caches.delete(k); });
      }).catch(function () {});
    } catch (e) { /* zonder Cache API is er ook niets bewaard */ }
  }
  if (document.body && document.body.hasAttribute("data-hp-anon")) clearSavedPages();
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form && form.getAttribute && form.getAttribute("action") === "/logout") clearSavedPages();
  }, true);

  // Updatemelding: een nieuwe service worker wacht (hij doet zelf geen skipWaiting) tot je hier tikt; daarna één keer herladen.
  var updateBtn = document.getElementById("sw-update");
  function offerUpdate(worker) {
    if (!updateBtn || !worker) return;
    updateBtn.hidden = false;
    updateBtn.onclick = function () {
      updateBtn.disabled = true;
      updateBtn.textContent = "Nieuwe versie laden";
      worker.postMessage({ type: "SKIP_WAITING" });
    };
  }
  if (hasSW) {
    var reloading = false;
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      // Alleen na een tik: bij de allereerste installatie neemt de service worker ook de controle over, en dan hoeft er niets te herladen.
      if (reloading || !updateBtn || !updateBtn.disabled) return;
      reloading = true;
      location.reload();
    });
    window.addEventListener("load", function () {
      // Op de root geserveerd (/service-worker.js), niet onder /static/: een service worker beheert alleen pagina's binnen zijn eigen pad, en
      // vanaf /static/ bleef navigator.serviceWorker.ready op de andere pagina's voor altijd hangen (zie de route in web/main.py).
      navigator.serviceWorker.register("/service-worker.js").then(function (reg) {
        if (reg.waiting && navigator.serviceWorker.controller) offerUpdate(reg.waiting);
        reg.addEventListener("updatefound", function () {
          var next = reg.installing;
          if (!next) return;
          next.addEventListener("statechange", function () {
            if (next.state === "installed" && navigator.serviceWorker.controller) offerUpdate(next);
          });
        });
        // Een geïnstalleerde app blijft dagen open; zo komt een nieuwe versie ook binnen zonder de app te sluiten.
        document.addEventListener("visibilitychange", function () { if (!document.hidden) reg.update().catch(function () {}); });
      }).catch(function () {});
    });
  }

  // Themakleur: de statusbalk van de geïnstalleerde app volgt de echte achtergrond (--bg). Een themawissel in Account (theme.js) roept
  // window.HP.applyThemeColor() aan; met Systeem (data-theme="system") volgen de twee media-varianten in _pwa_head.html het toestel.
  function applyThemeColor() {
    var bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    if (!bg) return;
    var theme = document.documentElement.getAttribute("data-theme");
    var explicit = theme === "dark" || theme === "light";
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) {
      var media = m.getAttribute("media") || "";
      var light = media.indexOf("light") !== -1;
      // Met een gekozen thema geldt één kleur, wat het systeem ook zegt; zonder keuze alleen de variant die nu actief is.
      if (explicit || window.matchMedia(media || "all").matches || (!light && !media)) m.setAttribute("content", bg);
    });
  }
  window.HP = window.HP || {};
  window.HP.applyThemeColor = applyThemeColor;
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyThemeColor);
  } catch (e) { /* oudere Safari: geen change-event op matchMedia, het thema volgt dan bij de volgende pagina */ }
})();
