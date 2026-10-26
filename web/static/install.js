// Installatiehulp "Zet HesPulse op je beginscherm" (macro install_help): op iPhone en iPad de drie stappen via Delen, op Android en Chrome een
// eigen knop via beforeinstallprompt. Weg zodra de app vanaf het beginscherm draait. De banner op Vandaag is weg te klikken en onthoudt dat;
// de kaart op Account blijft, zodat de uitleg altijd terug te vinden is.
(function () {
  var KEY = "hp_install_dismissed";

  function isIOS(env) {
    // iPadOS doet zich voor als een Mac; het verschil is het aanraakscherm.
    return /iPhone|iPad|iPod/.test(env.ua || "") || (env.platform === "MacIntel" && (env.maxTouchPoints || 0) > 1);
  }

  function mode(env) {
    if (env.standalone) return "installed";
    if (env.dismissed) return "dismissed";
    if (isIOS(env)) return "ios";
    if (env.hasPrompt) return "prompt";
    return "menu";
  }

  window.HPInstall = { mode: mode };

  var deferred = null, installed = false;
  function standalone() {
    if (installed) return true;
    try {
      return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
    } catch (e) { return false; }
  }
  function dismissed() {
    try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; }
  }
  function env(isCard) {
    return { standalone: standalone(), dismissed: !isCard && dismissed(), ua: navigator.userAgent, platform: navigator.platform,
             maxTouchPoints: navigator.maxTouchPoints, hasPrompt: !!deferred };
  }
  function toggle(box, selector, on) {
    box.querySelectorAll(selector).forEach(function (el) { el.hidden = !on; });
  }
  function render() {
    document.querySelectorAll("[data-install]").forEach(function (box) {
      var isCard = box.getAttribute("data-install") === "card";
      var m = mode(env(isCard));
      // De banner alleen als er echt iets te doen is (stappen of knop); de kaart noemt ook de menuroute van andere browsers.
      box.hidden = !(m === "ios" || m === "prompt" || (isCard && m === "menu"));
      toggle(box, "[data-install-ios]", m === "ios");
      toggle(box, "[data-install-android]", m === "prompt");
      toggle(box, "[data-install-menu]", m === "menu");
    });
  }

  window.addEventListener("beforeinstallprompt", function (e) {
    // Geen mini-balk van Chrome zelf: onze knop staat op een rustige plek en vraagt het pas als je erop tikt.
    e.preventDefault();
    deferred = e;
    render();
  });
  window.addEventListener("appinstalled", function () { deferred = null; installed = true; render(); });

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target.closest("[data-install-prompt], [data-install-dismiss]") : null;
    if (!t) return;
    if (t.hasAttribute("data-install-dismiss")) {
      try { localStorage.setItem(KEY, "1"); } catch (err) { /* zonder opslag verdwijnt hij alleen voor deze pagina */ }
      var box = t.closest("[data-install]");
      if (box) box.hidden = true;
      return;
    }
    if (!deferred) return;
    var prompt = deferred;
    deferred = null;            // een beforeinstallprompt is maar één keer te gebruiken
    prompt.prompt();
    Promise.resolve(prompt.userChoice).then(function (choice) {
      if (choice && choice.outcome === "accepted") installed = true;
      render();
    }).catch(render);
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
})();
