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
