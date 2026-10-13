// Tik op instap, stop of doel: het getal staat op het klembord. De bevestiging is nodig omdat je op een telefoon het klembord niet ziet.
// navigator.clipboard bestaat alleen op https en localhost; daarbuiten valt het terug op een verborgen tekstveld.
(function () {
  var toast = null, timer = null;

  function show(text) {
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "copy-toast";
      toast.setAttribute("role", "status");
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.add("is-on");
    clearTimeout(timer);
    timer = setTimeout(function () { toast.classList.remove("is-on"); }, 1800);
  }
  window.hesToast = show;

  function fallback(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-copy]");
    if (!btn) return;
    var text = btn.getAttribute("data-copy");
    var done = function (ok) { show(ok ? "Gekopieerd: " + text : "Kopiëren lukte niet"); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallback(text)); });
    } else {
      done(fallback(text));
    }
  });
})();
