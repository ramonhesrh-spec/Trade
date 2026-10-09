/* Ververst een strook met R:R (app/trade_plan.py:strip_html) zonder hem opnieuw op te bouwen: staan stop, instap en doel
   nog hetzelfde, dan schuift alleen de stip en verandert het koerslabel, zodat de CSS-overgang op `left` kan lopen. */
(function () {
  window.hesStripSwap = function (container, html) {
    var tpl = document.createElement("template");
    tpl.innerHTML = html;
    var next = tpl.content.firstElementChild;
    var cur = container.querySelector(".trade-strip");
    var same = cur && next && cur.getAttribute("data-strip-key") === next.getAttribute("data-strip-key") &&
      cur.hasAttribute("data-bar") === next.hasAttribute("data-bar") &&
      !!cur.querySelector('[data-strip="dot"]') === !!next.querySelector('[data-strip="dot"]');
    if (!same) { container.innerHTML = html; return; }
    ["aria-label", "data-dot", "data-now"].forEach(function (a) {
      if (next.hasAttribute(a)) cur.setAttribute(a, next.getAttribute(a)); else cur.removeAttribute(a);
    });
    ["dot", "now"].forEach(function (name) {
      var from = next.querySelector('[data-strip="' + name + '"]'), to = cur.querySelector('[data-strip="' + name + '"]');
      if (!from || !to) return;
      to.style.left = from.style.left;
      to.style.setProperty("--p", from.style.getPropertyValue("--p"));
      to.innerHTML = from.innerHTML;
    });
    var line = cur.querySelector(".strip-line"), nline = next.querySelector(".strip-line");
    if (line && nline) line.textContent = nline.textContent;
  };
})();
