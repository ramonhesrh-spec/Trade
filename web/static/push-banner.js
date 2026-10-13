// Banner bovenaan als dit apparaat geen meldingen krijgt. Zonder PushManager (Safari op iOS buiten een geïnstalleerde app) kan de knop
// niets, dus dan blijft de banner weg; staat de toestemming op geblokkeerd, dan kan alleen de telefoon zelf het herstellen.
// Wegtikken onthoudt dit apparaat 7 dagen.
(function () {
  var banner = document.getElementById("push-banner");
  if (!banner) return;
  var text = document.getElementById("push-banner-text"), btn = document.getElementById("push-banner-btn"), close = document.getElementById("push-banner-close");
  var KEY = "hespulse_push_banner_until", HIDE_MS = 7 * 24 * 3600 * 1000;

  function hiddenByUser() {
    try { return Number(localStorage.getItem(KEY) || 0) > Date.now(); } catch (e) { return false; }
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window) || hiddenByUser()) return;

  close.addEventListener("click", function () {
    banner.hidden = true;
    try { localStorage.setItem(KEY, String(Date.now() + HIDE_MS)); } catch (e) { /* privévenster: alleen voor nu weg */ }
  });
  btn.addEventListener("click", function () {
    if (!window.hesPushSubscribe) return;
    btn.disabled = true;
    window.hesPushSubscribe(function (t) { text.textContent = t; }).then(function (ok) {
      btn.disabled = false;
      if (ok) setTimeout(function () { banner.hidden = true; }, 1500);
    });
  });

  navigator.serviceWorker.ready
    .then(function (reg) { return reg.pushManager.getSubscription(); })
    .then(function (sub) {
      if (sub && Notification.permission === "granted") return;
      if (Notification.permission === "denied") {
        text.textContent = "Meldingen zijn geblokkeerd. Zet ze aan in de instellingen van je telefoon.";
        btn.hidden = true;
      }
      banner.hidden = false;
    })
    .catch(function () {});
})();
