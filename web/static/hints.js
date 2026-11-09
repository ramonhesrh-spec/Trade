// Uitleg bij een tik. Een title-attribuut verschijnt alleen met een muis, op een telefoon zie je niets. Dit toont dezelfde tekst bij een tik.
(function () {
  var pop = null, timer = null;
  document.addEventListener("click", function (e) {
    var el = e.target.closest(".signal-pct[title], .badge[title], .setup-grade[title]");
    if (pop) { pop.remove(); pop = null; clearTimeout(timer); }
    if (!el) return;
    pop = document.createElement("div");
    pop.className = "hint-pop";
    pop.textContent = el.getAttribute("title");
    document.body.appendChild(pop);
    var r = el.getBoundingClientRect();
    pop.style.top = (window.scrollY + r.bottom + 8) + "px";
    pop.style.left = Math.max(12, Math.min(window.innerWidth - pop.offsetWidth - 12, r.left)) + "px";
    timer = setTimeout(function () { if (pop) { pop.remove(); pop = null; } }, 5000);
  });
})();
