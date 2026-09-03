// Live prijs en PnL van open posities, elke 20 seconden bijgewerkt zonder
// de pagina opnieuw te laden. Een kort oplicht-moment (groen omhoog, rood
// omlaag) alleen als de waarde echt anders is dan de vorige poll, niet bij
// elke tick, en niet bij de allereerste keer laden.
(function () {
  const priceEls = document.querySelectorAll("[data-price]");
  if (!priceEls.length) return;

  const previous = {};

  function flash(el, up) {
    el.classList.remove("flash-up", "flash-down");
    void el.offsetWidth; // herstart de animatie ook als dezelfde richting twee keer op rij voorkomt
    el.classList.add(up ? "flash-up" : "flash-down");
  }

  function refresh() {
    fetch("/api/open_positions")
      .then((r) => r.json())
      .then((positions) => {
        positions.forEach((p) => {
          const priceEl = document.querySelector(`[data-price="${p.id}"]`);
          const pnlEl = document.querySelector(`[data-pnl="${p.id}"]`);
          const pnlPctEl = document.querySelector(`[data-pnl-pct="${p.id}"]`);

          if (priceEl && p.current_price !== null) {
            const key = `price-${p.id}`;
            if (previous[key] !== undefined && previous[key] !== p.current_price) {
              flash(priceEl, p.current_price > previous[key]);
            }
            previous[key] = p.current_price;
            priceEl.textContent = p.current_price.toFixed(4);
          }
          if (pnlEl && p.pnl_eur !== null) {
            const key = `pnl-${p.id}`;
            if (previous[key] !== undefined && previous[key] !== p.pnl_eur) {
              flash(pnlEl, p.pnl_eur > previous[key]);
            }
            previous[key] = p.pnl_eur;
            pnlEl.firstChild.textContent = `€${p.pnl_eur.toFixed(2)} `;
            pnlEl.classList.toggle("pos", p.pnl_eur >= 0);
            pnlEl.classList.toggle("neg", p.pnl_eur < 0);
          }
          if (pnlPctEl) {
            pnlPctEl.textContent = `(${p.pnl_pct.toFixed(1)}%)`;
          }
        });
      })
      .catch(() => {});
  }

  refresh();
  setInterval(refresh, 20000);
})();

// Trade nemen/sluiten/terugzetten zonder volledige paginaherlaad: het
// "Open nu"-blok (risicogauge + kaarten) wordt na een formulier-submit
// vervangen door de verse servergerenderde versie, met een korte fade in
// plaats van een volledige reload. Bij een netwerkfout of onverwachte
// respons valt dit terug op een gewone formulier-submit met paginaherlaad,
// nooit een stille mislukking waarbij de gebruiker denkt dat er niets is
// gebeurd terwijl er wel iets over echt geld gaat.
(function () {
  if (!document.getElementById("open-nu-body")) return;

  function isTracked(form) {
    return (
      form instanceof HTMLFormElement &&
      form.matches(".status-form, .close-form, .reset-form") &&
      form.closest("#open-nu-body")
    );
  }

  async function handleSubmit(e) {
    const form = e.target;
    // Als het "Terugzetten?"-bevestigingsdialoogje net op Annuleren is
    // geklikt, is de submit al geannuleerd (defaultPrevented) voor deze
    // listener hem te zien krijgt. Dan hier ook niets doen, anders
    // negeert de AJAX-laag die annulering alsnog.
    if (e.defaultPrevented) return;
    if (!isTracked(form)) return;
    e.preventDefault();

    const btn = form.querySelector("button[type=submit]");
    const originalLabel = btn ? btn.textContent : null;
    if (btn) { btn.disabled = true; btn.textContent = "Bezig..."; }

    try {
      const resp = await fetch(form.action, { method: "POST", body: new FormData(form) });
      if (!resp.ok) throw new Error("verzoek mislukt");
      const html = await resp.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById("open-nu-body");
      const current = document.getElementById("open-nu-body");
      if (!fresh || !current) throw new Error("open-nu-body niet gevonden in respons");

      current.style.transition = "opacity .16s ease";
      current.style.opacity = "0";
      await new Promise((r) => setTimeout(r, 160));
      current.replaceWith(fresh);
      fresh.style.opacity = "0";
      requestAnimationFrame(() => {
        fresh.style.transition = "opacity .2s ease";
        fresh.style.opacity = "1";
      });
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
      form.submit();
    }
  }

  document.addEventListener("submit", handleSubmit);
})();
