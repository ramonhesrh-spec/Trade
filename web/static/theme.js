// Thema kiezen in Account: Systeem, Donker of Licht. De keuze geldt meteen (data-theme op <html>) en blijft op dit toestel in localStorage
// en in de cookie hp_theme; die cookie laat de server de volgende pagina al in het goede thema schrijven, zonder flits.
(function () {
  var KEY = "hp_theme", VALID = { system: 1, dark: 1, light: 1 };

  function save(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* privévenster of geblokkeerde opslag: de cookie draagt de keuze */ }
    try { document.cookie = KEY + "=" + theme + "; max-age=" + 400 * 86400 + "; path=/; samesite=lax"; } catch (e) {}
  }

  function apply(theme) {
    var root = document.documentElement;
    root.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute("content", theme === "system" ? "dark light" : theme);
    if (window.HP && window.HP.applyThemeColor) window.HP.applyThemeColor();
  }

  // Een gewiste cookie met een bewaarde keuze: zet hem terug, anders schrijft de server de volgende pagina weer donker.
  try {
    var stored = localStorage.getItem(KEY);
    if (VALID[stored] && document.cookie.indexOf(KEY + "=" + stored) === -1) save(stored);
  } catch (e) {}

  document.addEventListener("change", function (e) {
    var input = e.target;
    if (!input || input.name !== "thema" || !input.closest || !input.closest("[data-theme-pick]") || !VALID[input.value]) return;
    save(input.value);
    apply(input.value);
  });
})();
