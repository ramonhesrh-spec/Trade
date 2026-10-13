// Pauzeknop: een tik zet alle pushes twee uur stil, nog een tik heft de pauze op. De server bewaart de eindtijd (users.push_paused_until),
// zodat de pauze ook geldt voor meldingen die komen terwijl de app dicht is. De resterende tijd komt van de server, de klok van de telefoon telt niet.
(function () {
  var btn = document.getElementById("push-pause"), label = document.getElementById("push-pause-label");
  if (!btn || !label) return;
  var timer = null;

  function show(state) {
    var paused = state.minutes_left > 0;
    btn.classList.toggle("is-paused", paused);
    btn.setAttribute("aria-pressed", paused ? "true" : "false");
    btn.title = paused ? "Tik om meldingen weer aan te zetten" : "Meldingen 2 uur stil";
    label.textContent = state.label;
    clearTimeout(timer);
    if (paused) timer = setTimeout(poll, 60000);
  }

  function call(method) {
    return fetch("/api/push/pauze", { method: method, credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) { if (s) show(s); })
      .catch(function () { /* geen verbinding: de knop houdt zijn laatste stand */ });
  }

  function poll() {
    if (document.hidden) { timer = setTimeout(poll, 60000); return; }
    call("GET");
  }

  btn.addEventListener("click", function () {
    btn.disabled = true;
    call("POST").then(function () { btn.disabled = false; });
  });
  if (btn.classList.contains("is-paused")) timer = setTimeout(poll, 60000);
})();
