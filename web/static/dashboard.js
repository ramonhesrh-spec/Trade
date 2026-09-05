// Live prijs en PnL van open posities, elke 20 seconden bijgewerkt zonder
// de pagina opnieuw te laden. Een kort oplicht-moment (groen omhoog, rood
// omlaag) alleen als de waarde echt anders is dan de vorige poll, niet bij
// elke tick, en niet bij de allereerste keer laden.
(function () {
  const priceEls = document.querySelectorAll("[data-price]");
  if (!priceEls.length) return;

  const previous = {};
  const vibrated = new Set();
  const defaultTitle = document.title;
  const faviconEl = document.querySelector('link[rel="icon"]');
  const defaultFaviconHref = faviconEl ? faviconEl.getAttribute("href") : null;

  function flash(el, up) {
    el.classList.remove("flash-up", "flash-down");
    void el.offsetWidth; // herstart de animatie ook als dezelfde richting twee keer op rij voorkomt
    el.classList.add(up ? "flash-up" : "flash-down");
  }

  // Tabblad-titel en favicon tonen je live resultaat zonder dat je het
  // tabblad hoeft te bekijken, alleen op echte trades, oefengeld hoort
  // niet in dat glimpje mee te tellen.
  function setFavicon(color) {
    if (!faviconEl) return;
    if (!color) {
      if (defaultFaviconHref) faviconEl.setAttribute("href", defaultFaviconHref);
      return;
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" fill="${color}"/></svg>`;
    faviconEl.setAttribute("href", "data:image/svg+xml," + encodeURIComponent(svg));
  }

  function updateTitleAndFavicon(positions) {
    const real = positions.filter((p) => !p.is_practice && p.pnl_eur !== null);
    if (!real.length) {
      document.title = defaultTitle;
      setFavicon(null);
      return;
    }
    const total = real.reduce((sum, p) => sum + p.pnl_eur, 0);
    const sign = total >= 0 ? "+" : "";
    document.title = `${sign}€${total.toFixed(0)} · HesPulse`;
    setFavicon(total > 0 ? "%2333d69f" : total < 0 ? "%23f2685c" : "%2317e5d6");
  }

  // Korte triltik op het moment dat een echte trade zijn stop loss of
  // take profit raakt, terwijl je het tabblad open hebt. Eenmalig per
  // trade, niet elke 20 seconden herhalen zolang hij eroverheen blijft.
  function checkVibration(p) {
    if (p.is_practice || p.current_price === null || !p.stop_loss || !p.take_profit || !navigator.vibrate) return;
    const hit = p.direction === "long"
      ? (p.current_price <= p.stop_loss || p.current_price >= p.take_profit)
      : (p.current_price >= p.stop_loss || p.current_price <= p.take_profit);
    if (hit && !vibrated.has(p.id)) {
      vibrated.add(p.id);
      navigator.vibrate([80, 40, 80]);
    } else if (!hit) {
      vibrated.delete(p.id);
    }
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
            pnlPctEl.textContent = p.pnl_pct !== null ? `(${p.pnl_pct.toFixed(1)}%)` : "";
          }
          // Spanningsgloed: hoe dichter de koers nu bij de stop loss of
          // take profit zit, hoe sterker de kaart oplicht. Server zet de
          // beginwaarde bij het laden, dit houdt 'm live tijdens het
          // pollen, zonder de pagina te hoeven herladen.
          var card = document.querySelector(`.tension-glow[data-entry-id="${p.id}"]`);
          if (card && p.tension !== undefined) {
            card.style.setProperty("--tension", p.tension);
            card.style.setProperty("--tension-color", p.tension_color);
          }
          checkVibration(p);
        });
        updateTitleAndFavicon(positions);
      })
      .catch(() => {});
  }

  refresh();
  setInterval(refresh, 20000);
})();

// Exit-tijd vult zichzelf in met het huidige moment, en de "nu"-knop zet de
// laatst bekende live koers in het exit-prijsveld. Een datum en tijd met de
// hand intikken op een telefoon is omslachtig, terwijl het op het moment
// dat je een trade sluit vrijwel altijd toch "nu" is.
(function () {
  function pad(n) { return String(n).padStart(2, "0"); }
  function nowLocal() {
    const d = new Date();
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function prefillExitTimes(scope) {
    scope.querySelectorAll('.close-form input[name="exit_time"]').forEach(function (el) {
      if (!el.value) el.value = nowLocal();
    });
  }

  prefillExitTimes(document);
  window.hpPrefillExitTimes = prefillExitTimes;

  document.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-fill-price]");
    if (!btn) return;
    const id = btn.getAttribute("data-fill-price");
    const priceEl = document.querySelector(`[data-price="${id}"]`);
    const form = btn.closest(".close-form");
    const input = form ? form.querySelector('input[name="exit_price"]') : null;
    if (priceEl && input && priceEl.textContent !== "-") {
      input.value = priceEl.textContent;
    }
  });
})();

// Deel-knop op een gesloten trade: via het native deelmenu als de browser
// dat ondersteunt, anders naar het klembord, met korte bevestiging in de
// knoptekst zelf zodat je weet dat het gelukt is.
(function () {
  document.addEventListener("click", function (e) {
    const btn = e.target.closest(".share-btn");
    if (!btn) return;
    const text = btn.dataset.share;
    if (!text) return;

    const original = btn.textContent;
    function confirmed(label) {
      btn.textContent = label;
      setTimeout(function () { btn.textContent = original; }, 1800);
    }

    if (navigator.share) {
      navigator.share({ text: text }).catch(function () {});
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { confirmed("Gekopieerd"); }).catch(function () {});
    }
  });
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
      form.matches(".status-form, .close-form, .reset-form, .levels-form") &&
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
      const resp = await fetch(form.action, { method: "POST", body: new FormData(form), cache: "no-store" });
      if (!resp.ok) throw new Error("verzoek mislukt");
      const html = await resp.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById("open-nu-body");
      const current = document.getElementById("open-nu-body");
      if (!fresh || !current) throw new Error("open-nu-body niet gevonden in respons");
      if (window.hpPrefillExitTimes) window.hpPrefillExitTimes(fresh);

      current.style.transition = "opacity .16s ease";
      current.style.opacity = "0";
      await new Promise((r) => setTimeout(r, 160));
      current.replaceWith(fresh);
      fresh.style.opacity = "0";
      requestAnimationFrame(() => {
        fresh.style.transition = "opacity .2s ease";
        fresh.style.opacity = "1";
      });
      if (window.HP) window.HP.progressDone();
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
      // Geen verbinding: een gewone form.submit() zou hier gegarandeerd
      // ook mislukken, met een kale browserfoutmelding als resultaat.
      // Toon in plaats daarvan een duidelijk bericht in de kaart zelf,
      // de gebruiker kan het opnieuw proberen zodra hij weer online is.
      if (!navigator.onLine) {
        if (window.HP) window.HP.progressDone();
        showInlineError(form, "Geen verbinding. Probeer het opnieuw zodra je weer online bent.");
        return;
      }
      // Valt terug op een echte paginaherlaad: de balk mag gewoon door
      // blijven lopen, die navigatie ruimt hem vanzelf op.
      form.submit();
    }
  }

  function showInlineError(form, message) {
    let el = form.querySelector(".ajax-error");
    if (!el) {
      el = document.createElement("p");
      el.className = "error ajax-error";
      form.insertBefore(el, form.firstChild);
    }
    el.textContent = message;
  }

  document.addEventListener("submit", handleSubmit);
})();

// Instellingen opslaan zonder volledige paginaherlaad: zelfde aanpak als
// hierboven (server-gerenderde fragment ophalen, vervangen met een fade),
// nu voor de portfolio-kaart. Bij een fout gewoon een echte paginaherlaad,
// nooit een stille mislukking bij iets dat het risicobedrag van elke
// toekomstige melding beinvloedt.
//
// Luistert op document zelf (niet op het formulier direct): na een
// geslaagde opslag wordt #portfolio-card, inclusief het formulier erin,
// vervangen door een verse servergerenderde versie. Een listener op het
// oude formulier-element zou daarna dood zijn, deze blijft werken omdat
// hij bij elke submit opnieuw kijkt welk element er nu staat.
(function () {
  async function handlePortfolioSubmit(e) {
    const form = e.target;
    if (e.defaultPrevented) return;
    if (!(form instanceof HTMLFormElement) || form.getAttribute("action") !== "/settings/portfolio") return;
    e.preventDefault();

    const btn = form.querySelector("button[type=submit]");
    const originalLabel = btn ? btn.textContent : null;
    if (btn) { btn.disabled = true; btn.textContent = "Bezig..."; }

    try {
      const resp = await fetch(form.action, { method: "POST", body: new FormData(form), cache: "no-store" });
      if (!resp.ok) throw new Error("verzoek mislukt");
      const html = await resp.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById("portfolio-card");
      const current = document.getElementById("portfolio-card");
      if (!fresh || !current) throw new Error("portfolio-card niet gevonden in respons");

      current.style.transition = "opacity .16s ease";
      current.style.opacity = "0";
      await new Promise((r) => setTimeout(r, 160));
      current.replaceWith(fresh);
      fresh.style.opacity = "0";
      requestAnimationFrame(() => {
        fresh.style.transition = "opacity .2s ease";
        fresh.style.opacity = "1";
      });
      if (window.HP) window.HP.progressDone();
    } catch (err) {
      if (btn) { btn.disabled = false; btn.textContent = originalLabel; }
      if (window.HP) window.HP.progressDone();
      form.submit();
    }
  }

  document.addEventListener("submit", handlePortfolioSubmit);
})();
