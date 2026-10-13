// Menu "Meer" als blad onderaan. Sluit bij een tik ernaast, op Escape en bij het openen van een link.
(function () {
  var toggle = document.getElementById("more-toggle"), sheet = document.getElementById("more-sheet");
  if (!toggle || !sheet) return;
  function setOpen(open) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) { sheet.hidden = false; requestAnimationFrame(function () { sheet.classList.add("is-open"); }); }
    else { sheet.classList.remove("is-open"); setTimeout(function () { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, 220); }
  }
  toggle.addEventListener("click", function () { setOpen(toggle.getAttribute("aria-expanded") !== "true"); });
  sheet.addEventListener("click", function (e) { if (e.target === sheet || e.target.closest("a")) setOpen(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });
})();

// De onderbalk schuift weg bij omlaag scrollen en komt terug bij omhoog scrollen of bovenaan.
// De drempel van 8px voorkomt dat iOS-rubberband en kleine trillingen de balk laten flikkeren.
(function () {
  var bar = document.querySelector(".tabbar");
  if (!bar) return;
  var last = window.scrollY, ticking = false;
  function update() {
    ticking = false;
    var y = window.scrollY, max = document.documentElement.scrollHeight - window.innerHeight;
    if (y <= 0 || y >= max - 2) { bar.classList.remove("is-hidden"); last = y; return; }
    if (Math.abs(y - last) < 8) return;
    bar.classList.toggle("is-hidden", y > last);
    last = y;
  }
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
})();
