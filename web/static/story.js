// Het verhaal "Wat is nieuw" (web/templates/_announce.html). Vegen werkt via scroll-snap, de stippen en de knop springen naar een kaart.
// Gezien wordt onthouden op de server (per gebruiker) en in localStorage: zegt dit toestel al gezien, dan opent het niet en hoort de server
// het alsnog. Op /wat-is-nieuw (data-page) staat het meteen open en gaat sluiten terug naar Nu.
(function () {
  var root = document.getElementById("wn-story");
  if (!root) return;
  var KEY = "hp_story_seen";
  var version = root.getAttribute("data-version");
  var isPage = root.hasAttribute("data-page");
  var track = root.querySelector("[data-wn-track]");
  var cards = root.querySelectorAll(".wn-card");
  var dots = root.querySelectorAll("[data-wn-dot]");
  var next = root.querySelector("[data-wn-next]");
  var nextLabel = next.textContent;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var current = 0, opener = document.activeElement;

  function seenHere() {
    try { return localStorage.getItem(KEY) === version; } catch (e) { return false; }
  }

  function remember() {
    try { localStorage.setItem(KEY, version); } catch (e) { /* privévenster: de server onthoudt het */ }
    try {
      fetch("/api/wat-is-nieuw/gezien", { method: "POST", credentials: "same-origin", keepalive: true }).catch(function () {});
    } catch (e) {}
  }

  if (!isPage && seenHere()) {
    remember();
    root.parentNode.removeChild(root);
    return;
  }

  function mark(i) {
    current = i;
    Array.prototype.forEach.call(dots, function (d, j) {
      if (j === i) d.setAttribute("aria-current", "step"); else d.removeAttribute("aria-current");
    });
    Array.prototype.forEach.call(cards, function (c, j) { c.setAttribute("aria-hidden", j === i ? "false" : "true"); });
    next.textContent = i === cards.length - 1 ? next.getAttribute("data-last") : nextLabel;
  }

  function go(i) {
    i = Math.max(0, Math.min(cards.length - 1, i));
    track.scrollTo({ left: i * track.clientWidth, behavior: reduce ? "auto" : "smooth" });
    mark(i);
  }

  function close() {
    if (isPage) {
      location.href = root.getAttribute("data-return") || "/vandaag";
      return;
    }
    document.documentElement.classList.remove("wn-lock");
    root.parentNode.removeChild(root);
    if (opener && opener.focus) opener.focus();
  }

  var scrollTimer = null;
  track.addEventListener("scroll", function () {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(function () {
      var i = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
      if (i !== current) mark(i);
    }, 60);
  }, { passive: true });

  root.addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("button") : null;
    if (!t || !root.contains(t)) return;
    if (t.hasAttribute("data-wn-close")) close();
    else if (t.hasAttribute("data-wn-dot")) go(Number(t.getAttribute("data-wn-dot")));
    else if (t.hasAttribute("data-wn-next")) { if (current >= cards.length - 1) close(); else go(current + 1); }
  });

  root.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key === "ArrowRight") { go(current + 1); return; }
    if (e.key === "ArrowLeft") { go(current - 1); return; }
    if (e.key !== "Tab") return;
    // Focus blijft in het verhaal zolang het open staat.
    var f = root.querySelectorAll("button");
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  root.hidden = false;
  document.documentElement.classList.add("wn-lock");
  mark(0);
  // Gezien zodra het opent: wie de app sluit zonder te tikken, krijgt het niet nog eens.
  if (!isPage) remember();
  next.focus({ preventScroll: true });
})();
