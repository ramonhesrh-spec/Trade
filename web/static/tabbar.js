// Menu "Meer" als blad onderaan. Sluit bij een tik ernaast, op Escape en bij het openen van een link.
(function () {
  var toggles = document.querySelectorAll("#more-toggle, [data-more-toggle]"), sheet = document.getElementById("more-sheet");
  if (!toggles.length || !sheet) return;
  function setOpen(open) {
    toggles.forEach(function (t) { t.setAttribute("aria-expanded", open ? "true" : "false"); });
    if (open) { sheet.hidden = false; requestAnimationFrame(function () { sheet.classList.add("is-open"); }); }
    else { sheet.classList.remove("is-open"); setTimeout(function () { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, 220); }
  }
  // Op desktop (de dock en het blad bestaan daar niet) is .ph-title geen knop: niet focusbaar en een klik doet niets.
  var phone = window.matchMedia("(max-width: 760px)");
  function syncPhone() {
    document.querySelectorAll(".ph-title[data-more-toggle]").forEach(function (t) {
      if (phone.matches) t.removeAttribute("tabindex"); else t.setAttribute("tabindex", "-1");
    });
  }
  syncPhone();
  if (phone.addEventListener) phone.addEventListener("change", syncPhone);
  toggles.forEach(function (t) {
    t.addEventListener("click", function () { if (phone.matches) setOpen(t.getAttribute("aria-expanded") !== "true"); });
  });
  // De zoekpalette sluit het blad eerst, zodat die er niet achter opent.
  document.addEventListener("hp:close-more", function () { setOpen(false); });
  sheet.addEventListener("click", function (e) { if (e.target === sheet || e.target.closest("a")) setOpen(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });
})();

// De onderbalk schuift weg bij omlaag scrollen en komt terug bij omhoog scrollen of bovenaan.
// Een drempel van 4px voorkomt flikkeren door iOS-rubberband. Onderaan de pagina komt de balk niet terug: op korte pagina's
// lag het scrollbereik zo klein dat de balk direct weer verscheen en het weglopen nooit te zien was.
(function () {
  var bar = document.querySelector(".dock") || document.querySelector(".tabbar");
  if (!bar) return;
  var last = window.scrollY, ticking = false;
  function update() {
    ticking = false;
    var y = window.scrollY;
    if (y <= 0) { bar.classList.remove("is-hidden"); last = y; return; }
    if (Math.abs(y - last) < 4) return;
    bar.classList.toggle("is-hidden", y > last);
    last = y;
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
})();

// Een tik op de tab van de pagina waar je al bent brengt je naar boven, zoals in elke telefoon-app. aria-current komt van de server;
// smooth.js zet is-active al bij pointerdown, dus daar kun je hier niet op vertrouwen.
(function () {
  var bar = document.querySelector(".tabbar");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var tab = e.target.closest && e.target.closest("a.tab[aria-current='page']");
    if (!tab) return;
    // Staat de tab op een andere url dan de pagina (bijvoorbeeld een ?filter), dan is een tik gewoon navigeren.
    if (tab.href.split("#")[0] !== location.href.split("#")[0]) return;
    e.preventDefault();
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
  });
})();
